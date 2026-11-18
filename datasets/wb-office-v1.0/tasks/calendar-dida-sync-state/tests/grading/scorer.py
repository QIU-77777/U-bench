#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        return {"json_load_error": repr(exc)}


def _junit_counts(xml_path: Path) -> tuple[int, int, int, int, int]:
    if not xml_path.exists():
        return 0, 0, 0, 0, 0
    try:
        root = ET.parse(xml_path).getroot()
        suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
        collected = sum(int(s.get("tests", 0)) for s in suites)
        failures = sum(int(s.get("failures", 0)) for s in suites)
        errors = sum(int(s.get("errors", 0)) for s in suites)
        skipped = sum(int(s.get("skipped", 0)) for s in suites)
        passed = max(0, collected - failures - errors - skipped)
        total = max(0, collected - skipped)
        return passed, total, failures, errors, skipped
    except Exception:
        return 0, 0, 0, 0, 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Write WB release verifier score and reward JSON")
    parser.add_argument("--results-xml", default="/logs/verifier/results.xml")
    parser.add_argument("--log-dir", default="/logs/verifier")
    parser.add_argument("--pytest-exit", default=os.environ.get("PYTEST_EXIT", "0"))
    parser.add_argument("--wall-time", default=os.environ.get("WALL_TIME", "0"))
    args = parser.parse_args()

    log_dir = Path(args.log_dir)
    output_text_path = log_dir / "test_output.txt"
    output_text = output_text_path.read_text(errors="replace") if output_text_path.exists() else ""
    passed, total, failures, errors, skipped = _junit_counts(Path(args.results_xml))
    rate = round(passed / total, 4) if total > 0 else 0.0
    try:
        exit_code = int(args.pytest_exit or 0)
    except ValueError:
        exit_code = 0
    try:
        wall = round(float(args.wall_time or 0), 2)
    except ValueError:
        wall = 0.0

    markers = ("ERROR: found no collectors", "ImportError while loading conftest", "fixture '")
    if exit_code not in (0, 1) or total <= 0 or any(marker in output_text for marker in markers):
        status = "build_error"
    elif rate >= 1.0:
        status = "full_pass"
    elif rate > 0:
        status = "partial_pass"
    else:
        status = "no_pass"

    raw = {
        "test_pass_rate": rate,
        "tests_passed": passed,
        "tests_total": total,
        "tests_failed": failures,
        "tests_error": errors,
        "tests_skipped": skipped,
        "wall_time_sec": wall,
    }
    score = dict(raw, test_status=status)

    eval_result = _load_json(log_dir / "eval_result.json")
    checks = eval_result.get("checks", []) if isinstance(eval_result.get("checks"), list) else []
    failed_checks = [check.get("name") for check in checks if isinstance(check, dict) and not check.get("passed")]
    if eval_result:
        deterministic_gated_pass = (
            eval_result.get("passed_count") == eval_result.get("total_count")
            and eval_result.get("preflight_passed_count", 0) == eval_result.get("preflight_total_count", 0)
        )
        score.update({
            "deterministic_component_score": eval_result.get("pass_rate"),
            "deterministic_pass_rate": eval_result.get("pass_rate"),
            "deterministic_gated_pass": deterministic_gated_pass,
            "failed_checks": failed_checks,
            "score_source_notes": "deterministic pytest wrapper over eval_core; WB Judge evidence is verifier-owned text artifacts",
        })

    manifest = _load_json(log_dir / "artifact_manifest.json")
    if manifest:
        score.update({
            "judge_planned": manifest.get("judge_planned", True),
            "judge_activation_allowed": manifest.get("judge_activation_allowed"),
            "judge_activation_block_reason": manifest.get("judge_activation_block_reason"),
            "score_merge": {"method": "weighted_sum", "rule_weight": 0.80, "llm_weight": 0.20},
        })

    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "score.json").write_text(json.dumps(score, ensure_ascii=False, indent=2), encoding="utf-8")
    (log_dir / "reward.json").write_text(json.dumps(dict(raw, reward=rate), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(score, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
