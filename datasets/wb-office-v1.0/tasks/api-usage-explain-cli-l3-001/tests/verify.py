#!/usr/bin/env python3
"""Composite verifier for wb-office tasks, Harbor-native.

Harbor contract: the task's ``tests/`` directory is uploaded to ``/tests``,
``tests/test.sh`` is executed inside the task container after the agent
finishes, and the reward is read from ``/logs/verifier/reward.json``.

Scoring replicates WorkBuddy Bench's office composite verifier:

1. Rule score — run the task's ``tests/grading`` pytest suite against the
   agent's workspace and read the pass rate from the JUnit XML.
2. LLM-judge score — for every rubric in ``tests/judge.json`` (converted from
   the task's ``judge.yaml``), ask the judge model for a pass/fail verdict
   over the artifact evidence, then take the mean (``rubric_binary_mean``).
3. Merge — ``weighted_sum`` with the weights declared in ``judge.yaml``
   (``score_merge.rule_weight`` / ``score_merge.llm_weight``).

Judge connection comes from the environment (Harbor ``verifier.env`` in the
bench config): ``JUDGE_BASE_URL``, ``JUDGE_API_KEY``, ``JUDGE_MODEL``.

Invalid verification never yields a score: when the rule pytest cannot produce
a result, the judge is not configured, or a judge request still fails after
retries, this script exits non-zero WITHOUT writing ``reward.json`` and Harbor
records the trial as errored.

Only the standard library is used: task images are not guaranteed to carry
pyyaml or openpyxl.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

TESTS_DIR = Path("/tests")
WORKSPACE_DIR = Path("/workspace")
VERIFIER_DIR = Path("/logs/verifier")
JUDGE_CONFIG_PATH = TESTS_DIR / "judge.json"
INSTRUCTION_PATH = TESTS_DIR / "instruction.md"

RULE_TIMEOUT_SEC = 1500
JUDGE_TIMEOUT_SEC = 180
JUDGE_RETRIES = 2
JUDGE_MAX_WORKERS = 4
MAX_EVIDENCE_CHARS = 12000
XLSX_PREVIEW_ROWS = 40

_SS_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_TEXT_TYPES = {"md", "markdown", "txt", "text", "json", "yaml", "yml", "csv", "html", "xml", "log"}


def log(message: str) -> None:
    print(f"[verify] {message}", flush=True)


# ── rule score ─────────────────────────────────────────────────────────


class InvalidVerification(RuntimeError):
    """The verifier could not produce a trustworthy score."""


def run_rule() -> tuple[float, dict]:
    """Run tests/grading with pytest and return (pass_rate, details)."""
    grading_dir = TESTS_DIR / "grading"
    junit_path = VERIFIER_DIR / "results.xml"
    env = dict(os.environ)
    env.setdefault("WB_BENCH_GOLD_PATH", str(TESTS_DIR / "gold" / "gold_answer.json"))
    env.setdefault("WB_BENCH_FIXTURES_DIR", str(TESTS_DIR / "gold" / "fixtures"))
    env["PYTHONPATH"] = f"{WORKSPACE_DIR}:{env.get('PYTHONPATH', '')}"

    cmd = [
        sys.executable, "-m", "pytest", str(grading_dir),
        "-p", "no:cacheprovider", "--tb=short",
        f"--junitxml={junit_path}",
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, env=env,
            timeout=RULE_TIMEOUT_SEC, cwd=str(WORKSPACE_DIR),
        )
    except subprocess.TimeoutExpired as exc:
        raise InvalidVerification(f"rule pytest timed out after {RULE_TIMEOUT_SEC}s") from exc

    (VERIFIER_DIR / "rule_pytest_output.txt").write_text(
        (proc.stdout or "") + "\n" + (proc.stderr or ""), encoding="utf-8"
    )

    if not junit_path.exists():
        raise InvalidVerification(f"no junit xml produced (pytest exit code {proc.returncode})")

    try:
        root = ET.parse(junit_path).getroot()
    except ET.ParseError as exc:
        raise InvalidVerification(f"junit xml unreadable: {exc}") from exc

    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = failures = errors = skipped = 0
    for suite in suites:
        total += int(suite.get("tests", 0))
        failures += int(suite.get("failures", 0))
        errors += int(suite.get("errors", 0))
        skipped += int(suite.get("skipped", 0))
    passed = total - failures - errors - skipped
    if not total:
        raise InvalidVerification("rule pytest collected no tests")
    rate = passed / total
    if proc.returncode not in (0, 1):
        raise InvalidVerification(f"pytest exit code {proc.returncode}")
    return rate, {
        "tests": total, "passed": passed, "failures": failures,
        "errors": errors, "skipped": skipped, "exit_code": proc.returncode,
    }


# ── artifact evidence ───────────────────────────────────────────────────


def _xlsx_evidence(path: Path) -> dict:
    """Read an xlsx with the standard library (zip + XML)."""
    sheets: list[dict] = []
    with zipfile.ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall(f"{_SS_NS}si"):
                shared.append("".join(
                    node.text or "" for node in item.iter(f"{_SS_NS}t")
                ))
        names = sorted(
            name for name in archive.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )
        for name in names:
            root = ET.fromstring(archive.read(name))
            rows: list[list] = []
            for row in root.iter(f"{_SS_NS}row"):
                values = []
                for cell in row.findall(f"{_SS_NS}c"):
                    kind = cell.get("t")
                    value = cell.find(f"{_SS_NS}v")
                    inline = cell.find(f"{_SS_NS}is")
                    if kind == "s" and value is not None:
                        values.append(shared[int(value.text)])
                    elif kind == "inlineStr" and inline is not None:
                        values.append("".join(
                            node.text or "" for node in inline.iter(f"{_SS_NS}t")
                        ))
                    elif value is not None:
                        values.append(value.text)
                    else:
                        values.append(None)
                rows.append(values)
                if len(rows) >= XLSX_PREVIEW_ROWS:
                    break
            sheets.append({"title": Path(name).stem, "preview_rows": rows})
    return {"kind": "xlsx", "sheet_count": len(sheets), "sheets": sheets}


def _manifest_records() -> dict[str, dict]:
    """Artifact records the grading stage wrote into /logs/verifier."""
    path = VERIFIER_DIR / "artifact_manifest.json"
    if not path.is_file():
        return {}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return {}
    records: dict[str, dict] = {}
    for key in ("artifacts", "created_artifacts", "judge_evidence"):
        for record in manifest.get(key) or []:
            if isinstance(record, dict) and record.get("id"):
                records.setdefault(str(record["id"]), record)
    return records


def collect_evidence(artifacts: list[dict]) -> dict:
    """Resolve judge.yaml artifact declarations to readable evidence.

    Resolution order mirrors the upstream office judge:
    1. artifact_manifest.json records written by the grading stage
       (text read from the verifier dir);
    2. the declaration path resolved against the verifier dir;
    3. the declaration path resolved against the agent workspace
       (binary artifacts such as xlsx).
    """
    records = _manifest_records()
    evidence: dict[str, Any] = {}
    for artifact in artifacts:
        art_id = str(artifact.get("id") or "")
        rel = str(artifact.get("path") or "")
        kind = str(artifact.get("type") or "").lower()
        entry: dict[str, Any] = {"path": rel, "type": kind}
        record = records.get(art_id)
        resolved: Path | None = None

        if record is not None:
            text_rel = record.get("text_path") or record.get("relative_path")
            if text_rel and str(record.get("extract_status", "ok")) == "ok":
                candidate = VERIFIER_DIR / str(text_rel)
                if candidate.is_file():
                    resolved = candidate
                    entry["source"] = f"manifest:{text_rel}"
        if resolved is None and rel:
            for base in (VERIFIER_DIR, WORKSPACE_DIR):
                candidate = base / rel
                if candidate.is_file():
                    resolved = candidate
                    entry["source"] = candidate.as_posix()
                    break

        if resolved is None:
            entry["missing"] = True
            evidence[art_id] = entry
            continue
        try:
            if kind == "xlsx":
                entry.update(_xlsx_evidence(resolved))
            else:
                entry["text"] = resolved.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001 - evidence failure is data
            entry["error"] = f"{type(exc).__name__}: {exc}"
        evidence[art_id] = entry
    text = json.dumps(evidence, ensure_ascii=False)
    if len(text) > MAX_EVIDENCE_CHARS:
        text = text[:MAX_EVIDENCE_CHARS] + "\n...[evidence truncated]..."
    return {"evidence_json": text, "manifest": {
        art_id: {k: v for k, v in entry.items() if k not in ("text", "preview_rows", "sheets")}
        for art_id, entry in evidence.items()
    }}


# ── LLM judge ───────────────────────────────────────────────────────────


def _judge_request(prompt: str) -> str:
    base = os.environ["JUDGE_BASE_URL"].rstrip("/")
    key = os.environ["JUDGE_API_KEY"]
    model = os.environ["JUDGE_MODEL"]
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4000,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=JUDGE_TIMEOUT_SEC) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["choices"][0]["message"].get("content") or ""


def build_prompt(rubric: dict, instruction: str, evidence_json: str, rule_reward: float) -> str:
    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items)

    return f"""你是 WorkBuddy Bench 的 LLM-as-Judge。请只基于下面给定的 evidence 判断单条 rubric，不要猜测 artifact 中没有出现的内容。

## Task instruction
{instruction}

## Rule reward
{rule_reward}

## Artifact evidence
{evidence_json}

## Rubric
ID: {rubric.get("id")}
Question: {rubric.get("question")}
Pass criteria:
{bullets(rubric.get("pass_criteria") or [])}
Fail criteria:
{bullets(rubric.get("fail_criteria") or [])}

只输出一行 JSON：{{"id":"{rubric.get("id")}","verdict":"pass","score":1.0,"reason":"简要说明"}}
verdict 只能是 "pass" 或 "fail"。score 只能是 1.0 或 0.0，并且必须和 verdict 一致。"""


def judge_one(rubric: dict, instruction: str, evidence_json: str, rule_reward: float) -> dict:
    rubric_id = str(rubric.get("id") or "")
    prompt = build_prompt(rubric, instruction, evidence_json, rule_reward)
    last_error = "no attempt made"
    for attempt in range(JUDGE_RETRIES + 1):
        try:
            content = _judge_request(prompt)
            match = re.search(r"\{.*\}", content, re.S)
            if not match:
                raise ValueError(f"no JSON object in response: {content[:200]!r}")
            verdict = json.loads(match.group(0))
            if verdict.get("verdict") not in ("pass", "fail"):
                raise ValueError(f"bad verdict field: {verdict!r}")
            score = 1.0 if verdict["verdict"] == "pass" else 0.0
            return {
                "id": rubric_id, "verdict": verdict["verdict"], "score": score,
                "reason": str(verdict.get("reason", ""))[:500],
            }
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            log(f"rubric {rubric_id} attempt {attempt + 1} failed: {last_error}")
    raise InvalidVerification(
        f"judge failed for rubric {rubric_id} after {JUDGE_RETRIES + 1} attempts: {last_error}"
    )


def run_llm_judge(cfg: dict, rule_reward: float) -> tuple[float | None, dict]:
    rubrics = [
        r for r in ((cfg.get("llm_judge") or {}).get("rubrics") or [])
        if isinstance(r, dict)
    ]
    if not rubrics:
        return None, {"status": "skipped", "reason": "no rubrics in judge config"}
    missing = [n for n in ("JUDGE_BASE_URL", "JUDGE_API_KEY", "JUDGE_MODEL") if not os.environ.get(n)]
    if missing:
        raise InvalidVerification(f"judge env not configured: {', '.join(missing)}")

    instruction = INSTRUCTION_PATH.read_text(encoding="utf-8") if INSTRUCTION_PATH.is_file() else ""
    evidence = collect_evidence(cfg.get("artifacts") or [])
    log(f"judging {len(rubrics)} rubrics with {os.environ['JUDGE_MODEL']}")

    with ThreadPoolExecutor(max_workers=JUDGE_MAX_WORKERS) as pool:
        verdicts = list(pool.map(
            lambda rubric: judge_one(rubric, instruction, evidence["evidence_json"], rule_reward),
            rubrics,
        ))

    passed = sum(1 for v in verdicts if v["verdict"] == "pass")
    score = round(passed / len(verdicts), 4) if verdicts else 0.0
    return score, {
        "status": "ok", "model": os.environ["JUDGE_MODEL"],
        "rubrics_passed": passed, "rubrics_total": len(verdicts),
        "artifact_manifest": evidence["manifest"], "verdicts": verdicts,
    }


# ── merge ───────────────────────────────────────────────────────────────


def merge_scores(rule: float, llm: float | None, score_merge: dict) -> tuple[float, dict]:
    method = str(score_merge.get("method") or "weighted_sum")
    if llm is None:
        return rule, {"method": method, "applied": False,
                      "reason": "llm judge unavailable; rule score stands"}
    rule_weight = float(score_merge.get("rule_weight", 0.85))
    llm_weight = float(score_merge.get("llm_weight", 0.15))
    total = rule_weight + llm_weight
    if total <= 0:
        return rule, {"method": method, "applied": False, "reason": "weights sum to zero"}
    final = (rule_weight * rule + llm_weight * llm) / total
    return round(final, 4), {
        "method": method, "applied": True,
        "rule_weight": rule_weight, "llm_weight": llm_weight,
    }


def main() -> int:
    VERIFIER_DIR.mkdir(parents=True, exist_ok=True)

    rule_score, rule_detail = run_rule()
    log(f"rule score: {rule_score} ({rule_detail})")

    try:
        cfg = json.loads(JUDGE_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidVerification(f"judge config unreadable: {exc!r}") from exc

    llm_score, judge_detail = run_llm_judge(cfg, rule_score)
    log(f"llm judge score: {llm_score}")

    final, merge_detail = merge_scores(rule_score, llm_score, cfg.get("score_merge") or {})
    log(f"final reward: {final} ({merge_detail})")

    (VERIFIER_DIR / "reward.json").write_text(
        json.dumps({"reward": final}), encoding="utf-8"
    )
    (VERIFIER_DIR / "score.json").write_text(json.dumps({
        "reward": final,
        "rule_score": rule_score, "rule_detail": rule_detail,
        "llm_score": llm_score, "judge_detail": judge_detail,
        "score_merge": merge_detail,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 - invalid verification: diagnose, write no reward
        import traceback
        VERIFIER_DIR.mkdir(parents=True, exist_ok=True)
        (VERIFIER_DIR / "score.json").write_text(json.dumps({
            "error": "verification invalid", "traceback": traceback.format_exc(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        traceback.print_exc()
        raise SystemExit(1)
