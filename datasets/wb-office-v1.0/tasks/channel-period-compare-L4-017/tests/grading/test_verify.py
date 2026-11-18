#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

GRADING_DIR = Path(__file__).resolve().parent
GOLD_PATH = Path(os.environ.get("WB_BENCH_GOLD_PATH", "/tests/gold/gold_answer.json"))
DEFAULT_OUTPUT_PATH = '/workspace/output/result.xlsx'

sys.path.insert(0, str(GRADING_DIR))
sys.path.insert(0, "/workspace")


def _default_output_path() -> str:
    try:
        gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
        return str(gold.get("output_contract", {}).get("path") or DEFAULT_OUTPUT_PATH)
    except Exception:
        return DEFAULT_OUTPUT_PATH


OUTPUT_PATH = os.environ.get("WB_BENCH_OUTPUT_PATH", _default_output_path())


def _load_result() -> dict:
    try:
        from eval_core import evaluate
    except Exception as exc:
        return {"checks": [{
            "name": "eval_core_import_failed",
            "passed": False,
            "detail": f"eval_core not importable: {exc!r}",
        }]}

    try:
        result = evaluate(OUTPUT_PATH, str(GOLD_PATH))
    except TypeError:
        try:
            result = evaluate(OUTPUT_PATH)
        except Exception as exc:
            return {"checks": [{
                "name": "evaluator_runtime_error",
                "passed": False,
                "detail": f"evaluator raised: {exc!r}",
            }]}
    except Exception as exc:
        return {"checks": [{
            "name": "evaluator_runtime_error",
            "passed": False,
            "detail": f"evaluator raised: {exc!r}",
        }]}

    return result if isinstance(result, dict) else {"checks": []}


_RESULT = _load_result()
_CHECKS = _RESULT.get("checks") or [{
    "name": "evaluator_emitted_no_checks",
    "passed": False,
    "detail": "evaluate() returned no checks",
}]
_IDS = [f"{idx:03d}_{check.get('name', 'unnamed_check')}" for idx, check in enumerate(_CHECKS)]


@pytest.mark.parametrize("idx", range(len(_CHECKS)), ids=_IDS)
def test_atomic_check(idx):
    check = _CHECKS[idx]
    assert check.get("passed") is True, check.get("detail", "")
