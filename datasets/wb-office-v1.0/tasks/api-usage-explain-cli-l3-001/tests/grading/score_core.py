#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _junit_counts(results_xml: Path, *, total_mode: str) -> dict[str, int]:
    raw = {"tests_collected": 0, "tests_failed": 0, "tests_error": 0, "tests_skipped": 0, "tests_passed": 0}
    if results_xml.exists():
        try:
            root = ET.parse(results_xml).getroot()
            suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
            collected = sum(int(s.get("tests", 0)) for s in suites)
            failed = sum(int(s.get("failures", 0)) for s in suites)
            errors = sum(int(s.get("errors", 0)) for s in suites)
            skipped = sum(int(s.get("skipped", 0)) for s in suites)
            raw = {
                "tests_collected": collected,
                "tests_failed": failed,
                "tests_error": errors,
                "tests_skipped": skipped,
                "tests_passed": max(0, collected - failed - errors - skipped),
            }
        except Exception:
            pass
    tests_total = raw["tests_collected"] if total_mode == "collected" else max(0, raw["tests_collected"] - raw["tests_skipped"])
    return {**raw, "tests_total": tests_total}


def _check_groups(checks: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    groups: dict[str, dict[str, int]] = {}
    for check in checks:
        group = str(check.get("group", "ungrouped"))
        item = groups.setdefault(group, {"passed": 0, "total": 0})
        item["total"] += 1
        if check.get("passed") is True:
            item["passed"] += 1
    return groups


def _failed_checks(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": str(check.get("name", "unnamed_check")),
            "group": str(check.get("group", "ungrouped")),
            "detail": check.get("detail", ""),
        }
        for check in checks
        if check.get("passed") is not True
    ]


def _eval_counts(eval_result: dict[str, Any], fallback: dict[str, int]) -> tuple[int, int, float]:
    checks = eval_result.get("checks") if isinstance(eval_result.get("checks"), list) else []
    total = int(eval_result.get("total_count") or len(checks) or fallback["tests_total"])
    passed = int(eval_result.get("passed_count") or sum(1 for check in checks if check.get("passed") is True))
    if eval_result.get("pass_rate") is not None:
        try:
            rate = round(float(eval_result.get("pass_rate")), 4)
        except Exception:
            rate = round(passed / total, 4) if total else 0.0
    else:
        rate = round(passed / total, 4) if total else 0.0
    return passed, total, rate


def _junit_rate(counts: dict[str, int]) -> tuple[int, int, float]:
    passed = counts["tests_passed"]
    total = counts["tests_total"]
    return passed, total, round(passed / total, 4) if total else 0.0


def _status(pytest_exit: int, total: int, rate: float, output_text: str, *, use_markers: bool) -> str:
    markers = ('ERROR: found no collectors', 'ImportError while loading conftest', "fixture '")
    if pytest_exit not in (0, 1) or total <= 0 or (use_markers and any(marker in output_text for marker in markers)):
        return "build_error"
    if rate >= 1.0:
        return "full_pass"
    if rate > 0:
        return "partial_pass"
    return "no_pass"


def _manifest_fields(logs: Path) -> dict[str, Any]:
    manifest = _load_json(logs / "artifact_manifest.json")
    if not manifest:
        return {}
    fields: dict[str, Any] = {}
    if "judge_planned" in manifest:
        fields["judge_planned"] = manifest.get("judge_planned")
    if "judge_activation_allowed" in manifest:
        fields["judge_activation_allowed"] = manifest.get("judge_activation_allowed")
    if "judge_activation_block_reason" in manifest:
        fields["judge_activation_block_reason"] = manifest.get("judge_activation_block_reason")
    return fields


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-xml", default="/logs/verifier/results.xml")
    parser.add_argument("--log-dir", default="/logs/verifier")
    parser.add_argument("--pytest-exit", default="0")
    parser.add_argument("--wall-time", default=None)
    parser.add_argument("--rate-source", choices=("junit", "eval-result"), default="junit")
    parser.add_argument("--junit-total-mode", choices=("collected", "non-skipped"), default="non-skipped")
    parser.add_argument("--build-error-markers", action="store_true")
    parser.add_argument("--include-artifact-manifest", action="store_true")
    args = parser.parse_args()

    logs = Path(args.log_dir)
    logs.mkdir(parents=True, exist_ok=True)
    counts = _junit_counts(Path(args.results_xml), total_mode=args.junit_total_mode)
    eval_result = _load_json(logs / "eval_result.json")
    checks = eval_result.get("checks") if isinstance(eval_result.get("checks"), list) else []
    if args.rate_source == "eval-result":
        passed, total, rate = _eval_counts(eval_result, counts)
    else:
        passed, total, rate = _junit_rate(counts)
    try:
        pytest_exit = int(args.pytest_exit)
    except Exception:
        pytest_exit = 1
    output_path = logs / "test_output.txt"
    output_text = output_path.read_text(encoding="utf-8", errors="replace") if output_path.exists() else ""
    score: dict[str, Any] = {
        "tests_passed": counts["tests_passed"],
        "tests_total": counts["tests_total"],
        "tests_collected": counts["tests_collected"],
        "tests_failed": counts["tests_failed"],
        "tests_error": counts["tests_error"],
        "tests_skipped": counts["tests_skipped"],
        "test_pass_rate": rate,
        "passed_count": passed,
        "total_count": total,
        "test_status": _status(pytest_exit, total, rate, output_text, use_markers=args.build_error_markers),
        "failed_checks": _failed_checks(checks),
        "check_groups": _check_groups(checks),
        "score_source": args.rate_source,
    }
    if args.wall_time is not None:
        try:
            score["wall_time_sec"] = round(float(args.wall_time), 2)
        except Exception:
            pass
    if args.include_artifact_manifest:
        score.update(_manifest_fields(logs))
    reward: dict[str, float | int] = {
        "reward": rate,
        "test_pass_rate": rate,
        "tests_passed": passed,
        "tests_total": total,
    }
    if "wall_time_sec" in score:
        reward["wall_time_sec"] = score["wall_time_sec"]
    (logs / "score.json").write_text(json.dumps(score, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (logs / "reward.json").write_text(json.dumps(reward, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (logs / "reward.txt").write_text(f"{rate}\n", encoding="utf-8")
    print(json.dumps(score, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
