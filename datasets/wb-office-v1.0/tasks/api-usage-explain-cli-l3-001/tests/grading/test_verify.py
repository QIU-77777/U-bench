#!/usr/bin/env python3
from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path

import pytest

GRADING_DIR = Path(__file__).resolve().parent
GOLD_PATH = Path(os.environ.get("WB_BENCH_GOLD_PATH", "/tests/gold/gold_answer.json"))
CASE_DIR = Path(os.environ.get("WB_BENCH_CASE_DIR", "/workspace"))
OUTPUT_PATH = os.environ.get("WB_BENCH_OUTPUT_PATH", "/workspace/final_answer.md")
VERIFIER_LOGS = Path(os.environ.get("WB_BENCH_VERIFIER_LOGS", "/logs/verifier"))

sys.path.insert(0, str(GRADING_DIR))
sys.path.insert(0, "/workspace")


def _persist_result(result: dict) -> None:
    try:
        VERIFIER_LOGS.mkdir(parents=True, exist_ok=True)
        (VERIFIER_LOGS / "eval_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _call_evaluate(evaluate):
    params = inspect.signature(evaluate).parameters
    kwargs = {}
    args = []
    if "case_dir" in params:
        kwargs["case_dir"] = CASE_DIR
    if "verifier_logs" in params:
        kwargs["verifier_logs"] = VERIFIER_LOGS
    if "verifier_logs_dir" in params:
        kwargs["verifier_logs_dir"] = VERIFIER_LOGS
    if "final_response" in params:
        final_path = Path("/workspace/final_answer.md")
        kwargs["final_response"] = final_path.read_text(encoding="utf-8") if final_path.exists() else ""
    if "answer_text" in params:
        final_path = Path(OUTPUT_PATH)
        kwargs["answer_text"] = final_path.read_text(encoding="utf-8") if final_path.exists() else ""
        kwargs["case_dir"] = CASE_DIR
        if "gold_path" in params:
            kwargs["gold_path"] = GOLD_PATH
        return evaluate(**kwargs)
    first_param = next(iter(params.values()), None)
    if first_param is not None and first_param.default is inspect._empty:
        args.append(OUTPUT_PATH)
    else:
        args.append(OUTPUT_PATH)
    return evaluate(*args, **kwargs)


def _load_result() -> dict:
    try:
        import eval_core
    except Exception as exc:
        result = {"checks": [{"name": "eval_core_import_failed", "passed": False, "detail": f"eval_core not importable: {exc!r}"}]}
        _persist_result(result)
        return result

    try:
        result = _call_evaluate(eval_core.evaluate)
        exporter = getattr(eval_core, "export_judge_evidence", None)
        if callable(exporter):
            evidence_dir = VERIFIER_LOGS / "judge_evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            try:
                exporter(Path(OUTPUT_PATH), evidence_dir, result)
            except TypeError:
                exporter(Path(OUTPUT_PATH), evidence_dir)
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
