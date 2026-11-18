#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

GRADING_DIR = Path(__file__).resolve().parent
GOLD_PATH = Path(os.environ.get("WB_BENCH_GOLD_PATH", "/tests/gold/gold_answer.json"))
CASE_DIR = Path(os.environ.get("WB_BENCH_CASE_DIR", "/workspace"))
OUTPUT_PATH = os.environ.get("WB_BENCH_OUTPUT_PATH", "/workspace")
VERIFIER_LOGS = Path(os.environ.get("WB_BENCH_VERIFIER_LOGS", "/logs/verifier"))

sys.path.insert(0, str(GRADING_DIR))
sys.path.insert(0, "/workspace")


def _persist_result(result: dict) -> None:
    try:
        VERIFIER_LOGS.mkdir(parents=True, exist_ok=True)
        (VERIFIER_LOGS / "eval_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _load_result() -> dict:
    try:
        from eval_core import evaluate
    except Exception as exc:
        result = {"checks": [{"name": "eval_core_import_failed", "passed": False, "detail": f"eval_core not importable: {exc!r}"}]}
        _persist_result(result)
        return result

    try:
        result = evaluate(OUTPUT_PATH, case_dir=CASE_DIR, verifier_logs=VERIFIER_LOGS)
    except TypeError:
        try:
            result = evaluate(OUTPUT_PATH, case_dir=CASE_DIR)
        except Exception as exc:
            result = {"checks": [{"name": "evaluator_runtime_error", "passed": False, "detail": f"evaluator raised: {exc!r}"}]}
    except Exception as exc:
        result = {"checks": [{"name": "evaluator_runtime_error", "passed": False, "detail": f"evaluator raised: {exc!r}"}]}

    if not isinstance(result, dict):
        result = {"checks": []}
    _persist_result(result)
    return result


_RESULT = _load_result()
_CHECKS = _RESULT.get("checks") or [{"name": "evaluator_emitted_no_checks", "passed": False, "detail": "evaluate() returned no checks"}]
_IDS = [f"{idx:03d}_{check.get('name', 'unnamed_check')}" for idx, check in enumerate(_CHECKS)]


@pytest.mark.parametrize("idx", range(len(_CHECKS)), ids=_IDS)
def test_atomic_check(idx):
    check = _CHECKS[idx]
    assert check.get("passed") is True, check.get("detail", "")
