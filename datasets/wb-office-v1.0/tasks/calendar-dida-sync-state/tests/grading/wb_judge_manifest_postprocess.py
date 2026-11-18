#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

FORBIDDEN_PATTERNS = [
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("url", re.compile(r"https?://[^\s)\]}>]+", re.IGNORECASE)),
    ("private_path", re.compile(r"/(?:data/private|mnt/private|var/secrets|tmp/private|Users)/[^\s\"'`]+", re.IGNORECASE)),
    ("credential", re.compile(r"(?:api[_-]?key|secret|token|credential|password)\s*[:=]", re.IGNORECASE)),
]


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value in {"true", "True", "TRUE"}:
        return True
    if value in {"false", "False", "FALSE"}:
        return False
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def _sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _load_declared_artifacts(judge_yaml: Path) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_artifacts = False
    for raw_line in judge_yaml.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        top_level = raw_line == raw_line.lstrip()
        if top_level and stripped.endswith(":"):
            key = stripped[:-1]
            if key == "artifacts":
                in_artifacts = True
                continue
            if in_artifacts:
                break
        if not in_artifacts:
            continue
        if stripped.startswith("- id:"):
            if current is not None:
                artifacts.append(current)
            current = {"id": _parse_scalar(stripped[len("- id:"):])}
            continue
        if current is not None and ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            if key in {"path", "required", "type"}:
                current[key] = _parse_scalar(value)
    if current is not None:
        artifacts.append(current)
    return [item for item in artifacts if item.get("id") and item.get("path")]


def _load_rubric_artifact_refs(judge_yaml: Path) -> set[str]:
    refs: set[str] = set()
    lines = judge_yaml.read_text(encoding="utf-8").splitlines()
    for index, raw_line in enumerate(lines):
        if raw_line.strip() != "artifact_refs:":
            continue
        base_indent = _line_indent(raw_line)
        for following in lines[index + 1:]:
            stripped = following.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = _line_indent(following)
            if indent <= base_indent:
                break
            if stripped.startswith("-"):
                refs.add(str(_parse_scalar(stripped[1:])))
    return refs


def _load_judge_artifacts(judge_yaml: Path) -> list[dict[str, Any]]:
    refs = _load_rubric_artifact_refs(judge_yaml)
    artifacts = _load_declared_artifacts(judge_yaml)
    if not refs:
        return artifacts
    return [artifact for artifact in artifacts if str(artifact.get("id")) in refs]


def build_manifests(judge_yaml: Path, logs: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    records: list[dict[str, Any]] = []
    audit_records: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for artifact in _load_judge_artifacts(judge_yaml):
        artifact_id = str(artifact["id"])
        source_rel = str(artifact["path"])
        evidence_path = logs / source_rel
        text = evidence_path.read_text(encoding="utf-8", errors="replace") if evidence_path.exists() else ""
        hits = [label for label, pattern in FORBIDDEN_PATTERNS if pattern.search(text)]
        if hits:
            findings.append({"path": source_rel, "patterns": hits})
        ok = evidence_path.is_file() and evidence_path.stat().st_size > 0 and not hits
        record: dict[str, Any] = {
            "id": artifact_id,
            "source_path": source_rel,
            "text_path": source_rel,
            "type": str(artifact.get("type") or "md"),
            "required": bool(artifact.get("required", True)),
            "extract_status": "ok" if ok else "error",
            "sha256": _sha256(evidence_path),
            "producer": "case_local_curated_evidence",
        }
        if not ok:
            record["error"] = "missing_empty_or_unsafe_curated_evidence"
        records.append(record)
        audit_records.append({
            "id": artifact_id,
            "path": source_rel,
            "exists": evidence_path.exists(),
            "size_bytes": evidence_path.stat().st_size if evidence_path.exists() else 0,
            "sha256": record["sha256"],
            "sanitization_findings": hits,
        })

    required_errors = [record["id"] for record in records if record.get("required", True) and record.get("extract_status") != "ok"]
    status = "pass" if records and not required_errors else "needs_review"
    artifact_manifest = {
        "artifacts": records,
        "extract_status": "ok" if status == "pass" else "error",
        "extract_source": "case_local_curated_evidence",
        "curated_evidence_only": True,
        "required_artifact_errors": required_errors,
        "judge_activation_allowed": status == "pass",
        "deterministic_component_transparency_required": True,
        "deterministic_failure_policy": "preserve_failed_checks_and_do_not_mark_objective_failures_passed",
    }
    evaluator_manifest = {
        "schema_version": "wb_judge_evidence_manifest_v1",
        "status": status,
        "records": audit_records,
        "artifact_manifest_present": True,
        "raw_artifacts_dir_present": False,
        "artifact_text_dir_present": False,
        "findings": findings,
        "notes": [
            "Postprocess writes a minimal WB Judge artifact_manifest.json that points to verifier-local curated Markdown evidence.",
            "It does not invoke central extraction, mirror evidence into /workspace, perform semantic scoring, or read hidden gold/oracle outputs.",
        ],
    }
    return artifact_manifest, evaluator_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--judge-yaml", default="/tests/judge.yaml")
    parser.add_argument("--logs", default=None)
    parser.add_argument("--verifier-output", default=None)
    parser.add_argument("--workspace", default=None)
    args = parser.parse_args()

    logs = Path(args.logs or args.verifier_output or "/logs/verifier")
    logs.mkdir(parents=True, exist_ok=True)
    artifact_manifest, evaluator_manifest = build_manifests(Path(args.judge_yaml), logs)
    (logs / "artifact_manifest.json").write_text(json.dumps(artifact_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (logs / "evaluator_artifact_manifest.json").write_text(json.dumps(evaluator_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    score_path = logs / "score.json"
    score = _load_json(score_path)
    if score:
        score["judge_evidence_ready"] = evaluator_manifest["status"] == "pass"
        score["judge_evidence_manifest"] = "artifact_manifest.json"
        score["judge_evidence_status"] = evaluator_manifest["status"]
        score["judge_evidence_source"] = "case_local_curated_evidence"
        score["judge_extraction_required"] = False
        notes = score.setdefault("validity_notes", [])
        if evaluator_manifest["findings"]:
            notes.append("judge_evidence_sanitization_findings_need_review")
        score_path.write_text(json.dumps(score, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(evaluator_manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
