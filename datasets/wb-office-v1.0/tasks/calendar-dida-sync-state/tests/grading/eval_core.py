#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

CASE_DIR = Path(os.environ.get("WB_BENCH_CASE_DIR", "/workspace"))
GOLD_ANSWER = Path(os.environ.get("WB_BENCH_GOLD_PATH", "/tests/gold/gold_answer.json"))
FIXTURE_DIR = Path(os.environ.get("WB_BENCH_FIXTURES_DIR", "/tests/gold/fixtures"))
TASK_STATE_REL = Path("input/workspace/tasks/task_state.json")
SYNC_HISTORY_REL = Path("input/workspace/sync/sync_history.json")
SUMMARY_REL = Path("input/workspace/reports/sync_summary.md")
MUTABLE_RELS = {TASK_STATE_REL.as_posix(), SYNC_HISTORY_REL.as_posix(), SUMMARY_REL.as_posix()}
RUN_ID = "run-20260714-1820-local"
RUN_TIME = "2026-07-14T18:20:00+08:00"

REQUIRED_SUMMARY_HEADINGS = [
    "## 本轮同步结论",
    "## 新建待办",
    "## 更新已有同步项",
    "## 置为 inactive",
    "## 保持不变",
    "## 重复或排除",
    "## 手工/无关任务保留",
    "## 边界确认",
]

URL_RE = re.compile(r"(?:https?://|www\.)[^\s)\]}>，。；、]+", re.IGNORECASE)
SECRET_PATTERNS = [
    re.compile(r"\b(?:password|passwd|secret|token|api[_-]?key|credential|access[_-]?key)\s*[:=]", re.IGNORECASE),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
]
PRIVATE_PATTERNS = [
    re.compile(r"(?<![A-Za-z0-9_.-])/(?:data|home|Users|private|var/folders)/[^\s)\]}>，。；、]+", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_.-])[A-Za-z]:[\\/][^\s)\]}>，。；、]+"),
    re.compile(r"\b(?:private_source_access|source_locator|request_id|conversation_id|row_group|row_in_group)\b", re.IGNORECASE),
    re.compile(r"\b[a-f0-9]{32}\b", re.IGNORECASE),
    re.compile(r"\b[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\b", re.IGNORECASE),
]
LIVE_POSITIVE_PATTERNS = [
    re.compile(r"(?:调用|访问|查询|发送到|发送|连接|使用|接入|外呼|触发).{0,28}(?:真实|外部|live|real|Calendar|Dida|TickTick|browser|浏览器|API|URL|service|provider|vendor|账号|VPN|网络|日历服务|待办服务|提醒服务|通知服务)", re.IGNORECASE),
    re.compile(r"(?:真实|外部|live service|real service|external|Calendar|Dida|TickTick|日历服务|待办服务|提醒服务|通知服务).{0,22}(?:调用|访问|查询|发送|连接|接入|服务|provider|vendor|API|URL)", re.IGNORECASE),
    re.compile(r"(?:external\s+API|live\s+service|real\s+service|browser|VPN|private\s+account|web|network|calendar\s+service|task\s+service)\s+(?:was|were)\s+(?:contacted|called|used|accessed|connected|queried)", re.IGNORECASE),
]
NEGATION_TERMS = [
    "不", "未", "无", "没有", "不得", "不要", "不能", "禁止", "避免", "只", "仅", "not", "no ", "without", "do not", "did not", "never",
]

JUDGE_EVIDENCE_FILES = {
    "judge_scope_and_gate_status": Path("judge_evidence/judge_scope_and_gate_status.md"),
    "submitted_sync_summary_text": Path("judge_evidence/submitted_sync_summary_text.md"),
    "submitted_task_state_semantic_summary": Path("judge_evidence/submitted_task_state_semantic_summary.md"),
    "submitted_sync_history_semantic_summary": Path("judge_evidence/submitted_sync_history_semantic_summary.md"),
    "public_sync_policy_context": Path("judge_evidence/public_sync_policy_context.md"),
    "public_noop_preservation_context": Path("judge_evidence/public_noop_preservation_context.md"),
    "public_workspace_boundary_context": Path("judge_evidence/public_workspace_boundary_context.md"),
}

JUDGE_EVIDENCE_LIMITS = {
    "judge_scope_and_gate_status": 6000,
    "submitted_sync_summary_text": 16000,
    "submitted_task_state_semantic_summary": 18000,
    "submitted_sync_history_semantic_summary": 18000,
    "public_sync_policy_context": 18000,
    "public_noop_preservation_context": 16000,
    "public_workspace_boundary_context": 10000,
}


class EvalInputError(RuntimeError):
    pass


def _check(name: str, passed: bool, detail: Any, group: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail, "group": group}


def _build_result(checks: list[dict[str, Any]], preflight_checks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    preflight = preflight_checks or []
    passed = sum(1 for check in checks if check.get("passed"))
    total = len(checks)
    return {
        "passed_count": passed,
        "total_count": total,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "checks": checks,
        "preflight_passed_count": sum(1 for check in preflight if check.get("passed")),
        "preflight_total_count": len(preflight),
        "preflight_checks": preflight,
    }


CONTRACT_TOTAL_COUNT = 109


def _not_evaluable_check(name: str, group: str, parse_failures: list[str]) -> dict[str, Any]:
    return _check(
        name,
        False,
        {
            "status": "not_evaluable",
            "reason": "required JSON artifact parse failure prevents fair evaluation of this downstream deterministic contract check",
            "depends_on_failed_checks": parse_failures,
        },
        group,
    )


def _downstream_contract_check_specs(gold: dict[str, Any], expected_history: dict[str, Any]) -> list[tuple[str, str]]:
    specs: list[tuple[str, str]] = [
        ("task_state_schema_required_top_level", "output_contract"),
        ("sync_history_schema_required_top_level", "output_contract"),
        ("task_ids_unique", "duplicate_idempotency"),
        ("mapping_ids_unique", "duplicate_idempotency"),
        ("preexisting_task_ids_all_preserved", "stale_noop_preserve"),
        ("preexisting_mapping_ids_all_preserved", "stale_noop_preserve"),
    ]

    for item in gold["expected_decisions"]["updated_existing"]:
        task_id = item["task_id"]
        mapping_id = item["mapping_id"]
        specs.extend([
            (f"stable_update_{task_id}_task_fields", "matching_and_updates"),
            (f"stable_update_{task_id}_manual_fields_preserved", "stale_noop_preserve"),
            (f"stable_update_{mapping_id}_history_fields", "matching_and_updates"),
        ])
        if task_id == "task-local-2017":
            specs.append(("stable_update_mobile_cache_training_matched_not_duplicated", "matching_and_updates"))

    for event_id in _expected_event_specs(gold):
        specs.extend([
            (f"new_create_{event_id}_one_active_task_by_sync_key", "matching_and_updates"),
            (f"new_create_{event_id}_task_source_linkage", "matching_and_updates"),
            (f"new_create_{event_id}_uses_nonpublic_task_id", "matching_and_updates"),
            (f"new_create_{event_id}_one_active_mapping_by_sync_key", "duplicate_idempotency"),
            (f"new_create_{event_id}_uses_nonpublic_mapping_id", "duplicate_idempotency"),
            (f"new_create_{event_id}_mapping_source_linkage", "matching_and_updates"),
        ])

    for item in gold["expected_decisions"]["inactive_tasks"]:
        task_id = item["task_id"]
        mapping_id = item["mapping_id"]
        reason = item["reason"]
        specs.extend([
            (f"inactive_{task_id}_{reason}_task_status", "stale_noop_preserve"),
            (f"inactive_{task_id}_{reason}_source_fields", "matching_and_updates"),
            (f"inactive_{mapping_id}_{reason}_history_fields", "stale_noop_preserve"),
        ])

    for task_id in gold["expected_decisions"]["no_change_tasks"]:
        specs.append((f"noop_preserve_{task_id}_exact", "stale_noop_preserve"))

    expected_by_mapping = _mappings_by_id(expected_history)
    noop_mapping_ids = [
        mapping_id
        for mapping_id, mapping in expected_by_mapping.items()
        if mapping.get("task_id") in gold["expected_decisions"]["no_change_tasks"] or mapping.get("state") == "excluded"
    ]
    for mapping_id in noop_mapping_ids:
        specs.append((f"noop_preserve_{mapping_id}_exact", "stale_noop_preserve"))

    for task_id in gold["expected_decisions"]["manual_preserve_tasks"]:
        specs.append((f"manual_preserve_{task_id}_exact", "stale_noop_preserve"))

    specs.extend([
        ("suppressed_duplicates_expected_event_ids_present", "duplicate_idempotency"),
        ("suppressed_duplicates_total_count_preserved", "duplicate_idempotency"),
    ])
    for event_id in gold["expected_decisions"]["suppressed_duplicate_event_ids"]:
        specs.append((f"duplicate_event_{_compact(event_id)}_single_active_task_mapping_for_sync_key", "duplicate_idempotency"))

    specs.extend([
        ("excluded_readonly_before_archive_no_active_task_or_mapping", "stale_noop_preserve"),
        ("out_of_window_existing_task_preserved_not_duplicated", "stale_noop_preserve"),
        ("source_missing_after_window_existing_task_preserved_active", "stale_noop_preserve"),
        ("idempotency_no_duplicate_active_tasks_per_sync_key", "duplicate_idempotency"),
        ("idempotency_no_duplicate_active_mappings_per_sync_key", "duplicate_idempotency"),
        ("idempotency_active_mappings_link_to_active_tasks", "duplicate_idempotency"),
        ("expected_task_total_count", "output_contract"),
        ("expected_mapping_total_count", "output_contract"),
        ("active_current_window_mapping_count", "duplicate_idempotency"),
        ("existing_public_id_tasks_match_expected_state", "matching_and_updates"),
        ("existing_public_id_mappings_match_expected_state", "matching_and_updates"),
        ("summary_required_headings_present", "summary_consistency"),
        ("summary_new_creates_refs_match_state", "summary_consistency"),
        ("summary_updates_refs_match_state", "summary_consistency"),
        ("summary_inactive_refs_and_reasons_match_state", "summary_consistency"),
        ("summary_noop_refs_match_state", "summary_consistency"),
        ("summary_duplicate_excluded_refs_match_state", "summary_consistency"),
        ("summary_manual_preserve_refs_match_state", "summary_consistency"),
        ("summary_category_counts_match_expected", "summary_consistency"),
        ("summary_boundary_confirmation_present", "summary_consistency"),
    ])
    return specs


def _append_parse_failure_contract_checks(
    checks: list[dict[str, Any]],
    gold: dict[str, Any],
    expected_history: dict[str, Any],
    root: Path,
    parse_failures: list[str],
) -> None:
    for name, group in _downstream_contract_check_specs(gold, expected_history):
        checks.append(_not_evaluable_check(name, group, parse_failures))

    mutable_text_parts: list[str] = []
    for rel in [TASK_STATE_REL, SYNC_HISTORY_REL, SUMMARY_REL]:
        path = root / rel
        if path.exists():
            mutable_text_parts.append(_read_text(path))
    mutable_text = "\n".join(mutable_text_parts)
    leakage = _text_leakage_hits(mutable_text)
    checks.append(_check("no_external_urls", not leakage["urls"], leakage["urls"], "output_contract"))
    checks.append(_check("no_secret_like_strings", not leakage["secrets"], leakage["secrets"], "output_contract"))
    checks.append(_check("no_private_paths_or_source_locator_markers", not leakage["private_markers"], leakage["private_markers"], "output_contract"))
    checks.append(_check("no_positive_live_or_external_service_claims", not leakage["positive_live_claims"], leakage["positive_live_claims"], "output_contract"))

    derivation_ok = gold.get("uses_judge") is False and gold.get("uses_vlm_judge") is False and "approved public files" in gold.get("derivation_boundary", "") and gold.get("created_after_p6_gate") == "G-P6R2-001"
    checks.append(_check("gold_boundary_deterministic_public_derivation", derivation_ok, gold.get("derivation_boundary"), "output_contract"))


def _force_zero_model_score(checks: list[dict[str, Any]], reason: str) -> list[dict[str, Any]]:
    return [
        {
            **check,
            "passed": False,
            "detail": f"{reason}; no model credit for this check. Original detail: {check.get('detail', '')}",
        }
        for check in checks
    ]


def _release_case_file(case_dir: Path, rel: str) -> Path:
    rel_path = Path(rel)
    rel_posix = rel_path.as_posix()
    if rel_posix in {"gold_answer.json", "gold/gold_answer.json"}:
        return GOLD_ANSWER
    if rel_posix.startswith("expected/"):
        return FIXTURE_DIR / "expected" / Path(rel_posix.removeprefix("expected/"))
    if rel_posix.startswith("gold/expected/"):
        return FIXTURE_DIR / "expected" / Path(rel_posix.removeprefix("gold/expected/"))
    return case_dir / rel_path


def _load_gold(case_dir: Path) -> dict[str, Any]:
    with _release_case_file(case_dir, "gold_answer.json").open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_expected_json(case_dir: Path, rel: str) -> Any:
    with _release_case_file(case_dir, rel).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_initial_json(case_dir: Path, rel: str) -> Any:
    """Read a workspace file as it was before the agent ran (root commit of the
    workspace git repo, created by environment/Dockerfile); the agent edits the
    working copy in place, so the working copy cannot tell initial ids from new ones."""
    import subprocess

    try:
        root = subprocess.run(
            ["git", "-C", str(case_dir), "rev-list", "--max-parents=0", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.split()[0]
        shown = subprocess.run(
            ["git", "-C", str(case_dir), "show", f"{root}:{Path(rel).as_posix()}"],
            capture_output=True, text=True, check=True,
        ).stdout
        return json.loads(shown)
    except (subprocess.CalledProcessError, IndexError, OSError, json.JSONDecodeError):
        return _load_expected_json(case_dir, rel)


def _read_expected_text(case_dir: Path, rel: str) -> str:
    return _release_case_file(case_dir, rel).read_text(encoding="utf-8")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8-sig")


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return str(path)


def _log_rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return str(path)


def _truncate_chars(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    marker = f"\n\n[truncated to {max_chars} characters by deterministic verifier; exact facts remain deterministic-owned]\n"
    return text[: max(0, max_chars - len(marker))].rstrip() + marker


def _state_kind(root: Path) -> str | None:
    if (root / "input" / "workspace").exists() and (root / "environment").exists():
        return "case_root"
    return None


def _resolve_root(path_arg: str | Path | None) -> tuple[Path, str]:
    root = Path(path_arg) if path_arg is not None else CASE_DIR
    if not root.is_absolute():
        root = Path.cwd() / root
    if root.is_file():
        for parent in root.parents:
            if _state_kind(parent):
                return parent, "file_parent_case_root"
        return root.parent, "file_parent_unknown"
    return root, "directory"


def _iter_state_files(root: Path) -> list[tuple[str, Path]]:
    pairs: list[tuple[str, Path]] = []
    for prefix in ["input", "environment"]:
        base = root / prefix
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                pairs.append(((Path(prefix) / path.relative_to(base)).as_posix(), path))
    return pairs


def _snapshot_protected_matches(root: Path, gold: dict[str, Any]) -> tuple[bool, str]:
    problems: list[str] = []
    for item in gold.get("public_workspace_snapshot", {}).get("files", []):
        rel = item.get("path")
        if not rel or item.get("mutable"):
            continue
        path = root / rel
        if not path.exists() or not path.is_file():
            problems.append(f"missing {rel}")
            continue
        digest = _sha256(path)
        size = path.stat().st_size
        if digest != item.get("sha256") or size != item.get("size_bytes"):
            problems.append(f"changed {rel}")
    return not problems, "; ".join(problems[:20]) if problems else "protected public input/environment snapshot matches hidden contract"


def _state_file_boundary(root: Path, gold: dict[str, Any]) -> tuple[bool, str]:
    expected = {item["path"]: item for item in gold.get("public_workspace_snapshot", {}).get("files", [])}
    actual = {rel: path for rel, path in _iter_state_files(root)}
    extra = sorted(set(actual) - set(expected))
    missing = sorted(set(expected) - set(actual))
    mutable_digest_problems: list[str] = []
    for rel, item in expected.items():
        path = actual.get(rel)
        if not path:
            continue
        digest = _sha256(path)
        initial_digest = item.get("sha256")
        if item.get("mutable"):
            if rel in MUTABLE_RELS and digest == initial_digest:
                mutable_digest_problems.append(f"unchanged mutable deliverable {rel}")
        else:
            if digest != initial_digest:
                mutable_digest_problems.append(f"changed protected {rel}")
    problems = []
    if extra:
        problems.append(f"extra={extra[:20]}")
    if missing:
        problems.append(f"missing={missing[:20]}")
    if mutable_digest_problems:
        problems.append(f"digest_problems={mutable_digest_problems[:20]}")
    return not problems, "; ".join(problems) if problems else "state tree contains only expected files; only target deliverables changed from initial snapshot"


def _norm(value: Any) -> str:
    return "" if value is None else str(value)


def _compact(value: Any) -> str:
    text = _norm(value).casefold().replace("（", "(").replace("）", ")")
    return re.sub(r"[\s`*_·•:：/\\|\-—–,，。；;、()（）\[\]【】<>《》%＋+?？.!！#\"'“”‘’]+", "", text)


def _contains_any(text: str, terms: list[str]) -> bool:
    lowered = text.casefold()
    compact = _compact(text)
    for term in terms:
        if not term:
            continue
        if term.casefold() in lowered or _compact(term) in compact:
            return True
    return False


def _split_clauses(text: str) -> list[str]:
    return [clause.strip() for clause in re.split(r"[\n。；;.!！?？]", text) if clause.strip()]


def _has_negation(text: str) -> bool:
    return _contains_any(text, NEGATION_TERMS)


def _positive_live_claim_hits(text: str) -> list[str]:
    hits: list[str] = []
    for pattern in LIVE_POSITIVE_PATTERNS:
        for match in pattern.finditer(text):
            clause_start = max(text.rfind(mark, 0, match.start()) for mark in ["\n", "。", "；", ";", ".", "!", "！", "?", "？"])
            clause_prefix = text[clause_start + 1: match.start()]
            hit_text = match.group(0)
            if _has_negation(clause_prefix) or _has_negation(hit_text):
                continue
            hits.append(hit_text[:220])
    return hits[:12]


def _text_leakage_hits(text: str) -> dict[str, list[str]]:
    return {
        "urls": [match.group(0)[:180] for match in URL_RE.finditer(text)][:12],
        "secrets": [match.group(0)[:180] for pattern in SECRET_PATTERNS for match in pattern.finditer(text)][:12],
        "private_markers": [match.group(0)[:180] for pattern in PRIVATE_PATTERNS for match in pattern.finditer(text)][:12],
        "positive_live_claims": _positive_live_claim_hits(text),
    }


def _tasks_by_id(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {task.get("task_id"): task for task in state.get("tasks", []) if isinstance(task, dict) and task.get("task_id")}


def _mappings_by_id(history: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {mapping.get("mapping_id"): mapping for mapping in history.get("mappings", []) if isinstance(mapping, dict) and mapping.get("mapping_id")}


def _tasks_by_sync_key(state: dict[str, Any], *, status: str | None = None) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for task in state.get("tasks", []):
        if not isinstance(task, dict):
            continue
        if status is not None and task.get("status") != status:
            continue
        key = (task.get("source") or {}).get("sync_key")
        if key:
            out.setdefault(key, []).append(task)
    return out


def _mappings_by_sync_key(history: dict[str, Any], *, state: str | None = None) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for mapping in history.get("mappings", []):
        if not isinstance(mapping, dict):
            continue
        if state is not None and mapping.get("state") != state:
            continue
        key = mapping.get("sync_key")
        if key:
            out.setdefault(key, []).append(mapping)
    return out


def _public_calendar(case_dir: Path) -> dict[str, Any]:
    return _load_expected_json(case_dir, "input/workspace/calendar/calendar_export_2026-07-14.json")


def _event_by_id(calendar: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {event.get("event_id"): event for event in calendar.get("events", []) if isinstance(event, dict)}


def _expected_event_specs(gold: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["event_id"]: item for item in gold.get("expected_decisions", {}).get("created_from_events", [])}


def _task_core_matches_event(task: dict[str, Any], event: dict[str, Any], spec: dict[str, Any]) -> tuple[bool, str]:
    source = task.get("source") or {}
    sync_fields = task.get("sync_fields") or {}
    required = {
        "status": "active",
        "archived": False,
        "list_id": spec.get("list_id", event.get("task_hint", {}).get("target_list")),
        "due_time": spec.get("due_time"),
        "priority": spec.get("priority") or ("high" if event.get("priority_hint") == "high" else "low" if event.get("priority_hint") == "low" else "normal"),
        "source.kind": "mock_calendar",
        "source.sync_key": event.get("sync_key"),
        "source.event_uid": event.get("uid"),
        "source.event_id": event.get("event_id"),
        "source.calendar_id": event.get("calendar_id"),
        "source.last_source_updated_at": event.get("updated_at"),
        "source.last_synced_at": RUN_TIME,
        "sync_fields.source_title": event.get("title"),
        "sync_fields.source_start_time": event.get("start_time"),
        "sync_fields.source_end_time": event.get("end_time"),
        "sync_fields.source_location": event.get("location"),
        "sync_fields.due_offset_minutes": event.get("task_hint", {}).get("due_offset_minutes"),
        "sync_fields.inactive_reason": None,
    }
    actual = {
        "status": task.get("status"),
        "archived": task.get("archived"),
        "list_id": task.get("list_id"),
        "due_time": task.get("due_time"),
        "priority": task.get("priority"),
        "source.kind": source.get("kind"),
        "source.sync_key": source.get("sync_key"),
        "source.event_uid": source.get("event_uid"),
        "source.event_id": source.get("event_id"),
        "source.calendar_id": source.get("calendar_id"),
        "source.last_source_updated_at": source.get("last_source_updated_at"),
        "source.last_synced_at": source.get("last_synced_at"),
        "sync_fields.source_title": sync_fields.get("source_title"),
        "sync_fields.source_start_time": sync_fields.get("source_start_time"),
        "sync_fields.source_end_time": sync_fields.get("source_end_time"),
        "sync_fields.source_location": sync_fields.get("source_location"),
        "sync_fields.due_offset_minutes": sync_fields.get("due_offset_minutes"),
        "sync_fields.inactive_reason": sync_fields.get("inactive_reason"),
    }
    mismatches = [f"{key}: expected {expected!r}, got {actual.get(key)!r}" for key, expected in required.items() if actual.get(key) != expected]
    tags = set(task.get("tags") or [])
    event_tags = set(event.get("task_hint", {}).get("tags") or [])
    missing_tags = sorted((event_tags | {"calendar-sync"}) - tags)
    if missing_tags:
        mismatches.append(f"missing tags {missing_tags}")
    title = str(task.get("title") or "")
    if event.get("title") not in title or "同步" not in title:
        mismatches.append(f"title does not bind source title: {title!r}")
    return not mismatches, "; ".join(mismatches[:12]) if mismatches else f"task {task.get('task_id')} matches event {event.get('event_id')} by source linkage"


def _mapping_core_matches_event(mapping: dict[str, Any], task: dict[str, Any], event: dict[str, Any], action: str) -> tuple[bool, str]:
    expected = {
        "sync_key": event.get("sync_key"),
        "event_uid": event.get("uid"),
        "event_id_last_seen": event.get("event_id"),
        "task_id": task.get("task_id"),
        "calendar_id": event.get("calendar_id"),
        "state": "active",
        "last_action": action,
        "last_seen_in_export_at": event.get("updated_at"),
        "last_synced_at": RUN_TIME,
        "missing_in_current_export": False,
    }
    mismatches = [f"{key}: expected {value!r}, got {mapping.get(key)!r}" for key, value in expected.items() if mapping.get(key) != value]
    return not mismatches, "; ".join(mismatches[:12]) if mismatches else f"mapping {mapping.get('mapping_id')} matches event {event.get('event_id')} and task {task.get('task_id')}"


def _dict_subset_equal(actual: dict[str, Any], expected: dict[str, Any], keys: list[str]) -> tuple[bool, str]:
    problems = [f"{key}: expected {expected.get(key)!r}, got {actual.get(key)!r}" for key in keys if actual.get(key) != expected.get(key)]
    return not problems, "; ".join(problems[:12]) if problems else "selected fields match"


def _section(text: str, heading: str) -> str:
    pattern = re.compile(rf"^\s*{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return ""
    next_match = re.search(r"^\s*##\s+", text[match.end():], flags=re.MULTILINE)
    if not next_match:
        return text[match.end():]
    return text[match.end(): match.end() + next_match.start()]


def _count_refs(text: str, refs: list[str]) -> int:
    compact = _compact(text)
    count = 0
    for ref in refs:
        if ref in text or _compact(ref) in compact:
            count += 1
    return count


def _summary_has_refs(section: str, refs: list[str]) -> tuple[bool, str]:
    missing = [ref for ref in refs if ref not in section and _compact(ref) not in _compact(section)]
    return not missing, f"missing refs={missing[:20]}" if missing else f"all refs present={refs}"


def _active_current_mapping_count(history: dict[str, Any]) -> int:
    current_prefixes = (
        "cal::uid-local-budget-20260716::2026-07-16",
        "cal::uid-local-review-moved-20260719::2026-07-19",
        "cal::uid-local-briefing-shift-20260716::2026-07-16",
        "cal::uid-local-briefing-20260715::2026-07-15",
        "cal::uid-local-vendor-review-20260715::2026-07-15",
        "cal::uid-local-onsite-20260717::2026-07-17",
        "cal::uid-local-training-20260718::2026-07-18",
        "cal::uid-local-contract-renewal-20260717-v2::2026-07-17",
    )
    return sum(1 for mapping in history.get("mappings", []) if mapping.get("state") == "active" and mapping.get("sync_key") in current_prefixes)


def _deterministic_safety_failed(result: dict[str, Any]) -> bool:
    safety_checks = {
        "no_external_urls",
        "no_secret_like_strings",
        "no_private_paths_or_source_locator_markers",
        "no_positive_live_or_external_service_claims",
    }
    failed = {check.get("name") for check in result.get("checks", []) if not check.get("passed")}
    return bool(failed & safety_checks)


def _json_label(task_or_mapping: dict[str, Any], *keys: str) -> str:
    parts: list[str] = []
    for key in keys:
        value = task_or_mapping.get(key)
        if value not in (None, ""):
            parts.append(f"{key}={value}")
    return "; ".join(parts) if parts else "no selected identifiers"


def _task_semantic_summary(task_state: dict[str, Any] | None) -> str:
    if not isinstance(task_state, dict):
        return _truncate_chars(
            "# Submitted Task State Semantic Summary\n\nNo parseable submitted task_state.json object was available. Deterministic parseability and schema checks own this failure.\n",
            JUDGE_EVIDENCE_LIMITS["submitted_task_state_semantic_summary"],
        )
    tasks = [task for task in task_state.get("tasks", []) if isinstance(task, dict)]
    active = [task for task in tasks if task.get("status") == "active"]
    inactive = [task for task in tasks if task.get("status") == "inactive"]
    source_linked = [task for task in tasks if (task.get("source") or {}).get("sync_key")]
    manual = [task for task in tasks if not (task.get("source") or {}).get("sync_key")]
    manual_locked = [task for task in tasks if task.get("manual_lock")]
    by_source_kind: dict[str, int] = {}
    by_list: dict[str, int] = {}
    for task in tasks:
        source = task.get("source") or {}
        by_source_kind[str(source.get("kind") or "none")] = by_source_kind.get(str(source.get("kind") or "none"), 0) + 1
        by_list[str(task.get("list_id") or "none")] = by_list.get(str(task.get("list_id") or "none"), 0) + 1
    lines = [
        "# Submitted Task State Semantic Summary",
        "",
        "This evidence summarizes only the submitted final `input/workspace/tasks/task_state.json` artifact. It does not compare against hidden gold, hidden expected state, oracle prose, construction notes, private trace context, model logs, or final-agent replies. Exact IDs, counts, timestamps, source-binding facts, schema compliance, and correctness remain deterministic-owned.",
        "",
        "## Top-level context",
        f"- state_meta keys: {', '.join(sorted((task_state.get('state_meta') or {}).keys())) if isinstance(task_state.get('state_meta'), dict) else 'not an object'}",
        f"- lists declared: {len(task_state.get('lists', [])) if isinstance(task_state.get('lists'), list) else 'not a list'}",
        f"- submitted tasks total: {len(tasks)} (context only; deterministic-owned)",
        f"- active tasks: {len(active)}; inactive tasks: {len(inactive)}; source-linked tasks: {len(source_linked)}; manual/null-sync-key tasks: {len(manual)}; manual_lock tasks: {len(manual_locked)}",
        f"- source kind families: {by_source_kind}",
        f"- list families: {by_list}",
        "",
        "## Source-linked task families",
    ]
    for task in sorted(source_linked, key=lambda item: str(((item.get("source") or {}).get("sync_key"), item.get("task_id")))):
        source = task.get("source") or {}
        sync_fields = task.get("sync_fields") or {}
        lines.append(
            "- "
            + "; ".join(
                [
                    f"task_id={task.get('task_id')}",
                    f"status={task.get('status')}",
                    f"archived={task.get('archived')}",
                    f"list_id={task.get('list_id')}",
                    f"due_time={task.get('due_time')}",
                    f"priority={task.get('priority')}",
                    f"sync_key={source.get('sync_key')}",
                    f"event_id={source.get('event_id')}",
                    f"event_uid={source.get('event_uid')}",
                    f"last_source_updated_at={source.get('last_source_updated_at')}",
                    f"inactive_reason={sync_fields.get('inactive_reason')}",
                    f"source_title={sync_fields.get('source_title')}",
                ]
            )
        )
    lines.extend(["", "## Manual, null-sync-key, or locally owned task families"])
    for task in sorted(manual, key=lambda item: str(item.get("task_id"))):
        lines.append(
            "- "
            + "; ".join(
                [
                    f"task_id={task.get('task_id')}",
                    f"status={task.get('status')}",
                    f"archived={task.get('archived')}",
                    f"list_id={task.get('list_id')}",
                    f"due_time={task.get('due_time')}",
                    f"manual_lock={task.get('manual_lock')}",
                    f"title={task.get('title')}",
                    f"manual_note={task.get('manual_note')}",
                ]
            )
        )
    lines.extend([
        "",
        "## Semantic-use boundary",
        "Judge may use this summary only to compare the submitted human report against the model's own submitted final JSON at a semantic category level. Deterministic checks own parseability, schema, exact IDs/counts/timestamps, source linkage, inactive reasons, duplicate uniqueness, and correctness against expected state.",
    ])
    return _truncate_chars("\n".join(lines).strip() + "\n", JUDGE_EVIDENCE_LIMITS["submitted_task_state_semantic_summary"])


def _history_semantic_summary(sync_history: dict[str, Any] | None) -> str:
    if not isinstance(sync_history, dict):
        return _truncate_chars(
            "# Submitted Sync History Semantic Summary\n\nNo parseable submitted sync_history.json object was available. Deterministic parseability and schema checks own this failure.\n",
            JUDGE_EVIDENCE_LIMITS["submitted_sync_history_semantic_summary"],
        )
    mappings = [mapping for mapping in sync_history.get("mappings", []) if isinstance(mapping, dict)]
    suppressed = [item for item in sync_history.get("suppressed_duplicates", []) if isinstance(item, dict)]
    by_state: dict[str, int] = {}
    by_action: dict[str, int] = {}
    missing_flags: dict[str, int] = {"missing_true": 0, "missing_false": 0, "missing_other": 0}
    for mapping in mappings:
        by_state[str(mapping.get("state") or "none")] = by_state.get(str(mapping.get("state") or "none"), 0) + 1
        by_action[str(mapping.get("last_action") or "none")] = by_action.get(str(mapping.get("last_action") or "none"), 0) + 1
        if mapping.get("missing_in_current_export") is True:
            missing_flags["missing_true"] += 1
        elif mapping.get("missing_in_current_export") is False:
            missing_flags["missing_false"] += 1
        else:
            missing_flags["missing_other"] += 1
    lines = [
        "# Submitted Sync History Semantic Summary",
        "",
        "This evidence summarizes only the submitted final `input/workspace/sync/sync_history.json` artifact. It does not compare against hidden gold, hidden expected state, oracle prose, construction notes, private trace context, model logs, or final-agent replies. Exact mapping IDs, counts, timestamps, source-binding facts, duplicate records, schema compliance, and correctness remain deterministic-owned.",
        "",
        "## Top-level context",
        f"- history_meta keys: {', '.join(sorted((sync_history.get('history_meta') or {}).keys())) if isinstance(sync_history.get('history_meta'), dict) else 'not an object'}",
        f"- sync_window: {sync_history.get('sync_window') if isinstance(sync_history.get('sync_window'), dict) else 'not an object'}",
        f"- submitted mappings total: {len(mappings)} (context only; deterministic-owned)",
        f"- mapping state families: {by_state}",
        f"- last_action families: {by_action}",
        f"- missing_in_current_export families: {missing_flags}",
        f"- suppressed duplicate records: {len(suppressed)} (context only; deterministic-owned)",
        "",
        "## Mapping families",
    ]
    for mapping in sorted(mappings, key=lambda item: str((item.get("state"), item.get("sync_key"), item.get("mapping_id")))):
        lines.append(
            "- "
            + "; ".join(
                [
                    f"mapping_id={mapping.get('mapping_id')}",
                    f"state={mapping.get('state')}",
                    f"last_action={mapping.get('last_action')}",
                    f"sync_key={mapping.get('sync_key')}",
                    f"task_id={mapping.get('task_id')}",
                    f"event_id_last_seen={mapping.get('event_id_last_seen')}",
                    f"missing_in_current_export={mapping.get('missing_in_current_export')}",
                    f"last_seen_in_export_at={mapping.get('last_seen_in_export_at')}",
                    f"last_synced_at={mapping.get('last_synced_at')}",
                ]
            )
        )
    lines.extend(["", "## Suppressed duplicate families"])
    for item in sorted(suppressed, key=lambda entry: str((entry.get("sync_key"), entry.get("source_event_id")))):
        lines.append(
            "- "
            + "; ".join(
                [
                    _json_label(item, "source_event_id", "canonical_event_id", "sync_key", "reason"),
                    f"source_updated_at={item.get('source_updated_at')}",
                ]
            )
        )
    lines.extend([
        "",
        "## Semantic-use boundary",
        "Judge may use this summary only to compare the submitted human report against the model's own submitted final history at a semantic category level. Deterministic checks own parseability, schema, exact mapping/source-binding facts, duplicate uniqueness, exact duplicate records, timestamps, and correctness against expected state.",
    ])
    return _truncate_chars("\n".join(lines).strip() + "\n", JUDGE_EVIDENCE_LIMITS["submitted_sync_history_semantic_summary"])


def _judge_scope_status(result: dict[str, Any]) -> str:
    failed = [check.get("name") for check in result.get("checks", []) if not check.get("passed")]
    preflight_failed = [check.get("name") for check in result.get("preflight_checks", []) if not check.get("passed")]
    gated_pass = result.get("passed_count") == result.get("total_count") and result.get("preflight_passed_count") == result.get("preflight_total_count")
    safety_failed = _deterministic_safety_failed(result)
    lines = [
        "# Judge Scope and Deterministic Gate Status",
        "",
        "This Markdown evidence file is produced by the deterministic verifier for supplemental text-only WB Judge consumption.",
        "",
        "## Deterministic status",
        f"- passed_count: {result.get('passed_count')}",
        f"- total_count: {result.get('total_count')}",
        f"- pass_rate: {result.get('pass_rate')}",
        f"- preflight_passed_count: {result.get('preflight_passed_count')}",
        f"- preflight_total_count: {result.get('preflight_total_count')}",
        f"- deterministic_gated_pass: {str(gated_pass).lower()}",
        f"- deterministic_safety_or_leakage_failed: {str(safety_failed).lower()}",
        f"- llm_judge_activation_allowed: {str(not safety_failed).lower()}",
        f"- failed_checks: {', '.join(failed) if failed else 'none'}",
        f"- preflight_failed_checks: {', '.join(preflight_failed) if preflight_failed else 'none'}",
        "",
        "WB Judge may run only when all required judge_evidence files exist, deterministic safety/leakage checks pass, and deterministic component score, preflight status, failed_checks, and objective failure attribution are preserved separately. Deterministic full pass is not required by the current merge policy, but Judge must not recover, forgive, reinterpret, or override deterministic failures.",
        "",
        "## Judge modality and forbidden behavior",
        "- Text-only semantic review of the submitted sync summary, submitted final-state semantic summaries, deterministic scope status, and public policy/boundary context.",
        "- No VLM/image/OCR/pixel-level visual scoring, screenshots, rendered thumbnails, audio, or video evidence.",
        "- No browser/API/Skill/MCP/live-service behavior, external web evidence, real account access, notifications, or network side effects are required or allowed for Judge evidence.",
        "",
        "## Deterministic-owned scope not scored by Judge",
        "- file existence, filenames, path correctness, workspace state diff, protected-file preservation, and forbidden extra artifact detection",
        "- JSON/Markdown parseability, required schema/headings, exact state transitions, exact field values, exact IDs/counts/timestamps, source binding, duplicate uniqueness, and exact summary references/count terms",
        "- objective safety/leakage checks, private/source leakage detection, secret detection, and live/external-service regex scans",
        "- deterministic pass recovery, deterministic failed-check reinterpretation, hidden gold comparison, exact oracle wording, or score compensation",
        "",
        "## Exclusion boundary",
        "This file excludes hidden gold-only expected artifacts, construction notes, evidence-package internals, private trace text, private paths, private URLs, credentials, account identifiers, customer data, proprietary code, unpublished assets, model logs, and final-agent replies.",
    ]
    return _truncate_chars("\n".join(lines).strip() + "\n", JUDGE_EVIDENCE_LIMITS["judge_scope_and_gate_status"])


def _read_public_source(case_dir: Path, rel: str, max_chars: int) -> str:
    path = case_dir / rel
    if not path.exists() or not path.is_file():
        return f"Missing public source `{rel}`. Deterministic file-boundary checks own missing-file facts.\n"
    return _truncate_chars(_read_text(path).strip(), max_chars)


def _source_flags(record: dict[str, Any]) -> set[str]:
    raw_flags = record.get("source_flags")
    if isinstance(raw_flags, list):
        return {str(flag) for flag in raw_flags if flag not in (None, "")}
    if isinstance(raw_flags, str):
        return {flag.strip() for flag in re.split(r"[,;|\s]+", raw_flags) if flag.strip()}
    if isinstance(raw_flags, dict):
        return {str(flag) for flag, enabled in raw_flags.items() if enabled}
    return set()


def _calendar_sync_window(calendar: dict[str, Any]) -> tuple[str | None, str | None]:
    export_meta = calendar.get("export_meta") if isinstance(calendar.get("export_meta"), dict) else {}
    sync_window = export_meta.get("sync_window") if isinstance(export_meta.get("sync_window"), dict) else {}
    start = (
        sync_window.get("start")
        or sync_window.get("start_time")
        or sync_window.get("window_start")
        or export_meta.get("sync_window_start")
        or export_meta.get("window_start")
    )
    end = (
        sync_window.get("end")
        or sync_window.get("end_time")
        or sync_window.get("window_end")
        or export_meta.get("sync_window_end")
        or export_meta.get("window_end")
    )
    return str(start) if start else None, str(end) if end else None


def _within_sync_window(start_time: Any, window_start: str | None, window_end: str | None) -> bool | None:
    if not isinstance(start_time, str) or not start_time or not (window_start or window_end):
        return None
    if window_start and start_time < window_start:
        return False
    if window_end and start_time > window_end:
        return False
    return True


def _public_sync_policy_context(case_dir: Path) -> str:
    calendar = _public_calendar(case_dir)
    events = [event for event in calendar.get("events", []) if isinstance(event, dict)]
    calendars = [item for item in calendar.get("calendars", []) if isinstance(item, dict)]
    excluded_calendar_ids = {
        str(item.get("calendar_id"))
        for item in calendars
        if item.get("calendar_id") and item.get("sync_allowed") is False
    }
    window_start, window_end = _calendar_sync_window(calendar)

    sync_key_counts: dict[str, int] = {}
    for event in events:
        key = event.get("sync_key")
        if key:
            sync_key_counts[str(key)] = sync_key_counts.get(str(key), 0) + 1

    duplicate_or_cache_flags = {"repeated_export_row", "backup_snapshot", "device_cache_snapshot"}
    read_only_or_excluded_flags = {"reference_calendar", "reference_record", "archive_calendar", "do_not_sync", "source_excluded"}
    duplicate_keys = sorted({
        str(event.get("sync_key"))
        for event in events
        if event.get("sync_key")
        and (
            sync_key_counts.get(str(event.get("sync_key")), 0) > 1
            or bool(_source_flags(event) & duplicate_or_cache_flags)
        )
    })
    cancelled = [event.get("event_id") for event in events if event.get("status") == "cancelled"]
    read_only = sorted({
        str(event.get("event_id"))
        for event in events
        if event.get("event_id")
        and (
            str(event.get("calendar_id")) in excluded_calendar_ids
            or bool(_source_flags(event) & read_only_or_excluded_flags)
        )
    })
    out_of_window = sorted({
        str(event.get("event_id"))
        for event in events
        if event.get("event_id")
        and (
            "outside_current_window" in _source_flags(event)
            or _within_sync_window(event.get("start_time"), window_start, window_end) is False
        )
    })
    same_title_titles: dict[str, list[str]] = {}
    for event in events:
        same_title_titles.setdefault(str(event.get("title")), []).append(str(event.get("sync_key")))
    same_title_different_key = {title: sorted(set(keys)) for title, keys in same_title_titles.items() if len(set(keys)) > 1}
    lines = [
        "# Public Sync Policy Context",
        "",
        "This evidence summarizes only P6-approved public input files for supplemental WB Judge. It includes no hidden gold, hidden expected state, oracle prose, construction notes, private trace context, model logs, final-agent replies, external web evidence, or live-service evidence. Exact row coverage, IDs, timestamps, and correctness remain deterministic-owned.",
        "",
        "## Public synchronization policy excerpts",
        _read_public_source(case_dir, "input/workspace/rules/sync_policy.md", 9000),
        "",
        "## Public operator-note excerpts",
        _read_public_source(case_dir, "input/workspace/notes/operator_notes.txt", 3500),
        "",
        "## Public calendar-export semantic anchors",
        f"- event records in public calendar export: {len(events)} (context only; exact counts deterministic-owned)",
        f"- duplicate/cache sync_key families visible in public export: {duplicate_keys}",
        f"- cancelled public event IDs visible in public export: {cancelled}",
        f"- read-only/excluded public event IDs visible in public export: {read_only}",
        f"- out-of-window public event IDs visible in public export: {out_of_window}",
        f"- same-title different-sync-key public families: {same_title_different_key}",
        "",
        "## Judge-use policy anchors",
        "- Stable `sync_key`/history/target-side matching takes precedence over title, time, or natural-language similarity when deciding whether an existing task is updated or a new task is created.",
        "- Manual tasks, null-sync-key tasks, manual_lock tasks, and unrelated local tasks are not synchronization targets merely because their titles or notes look similar.",
        "- Source-missing active mappings are inactivated only when the target due_time is inside the current sync window; source-missing targets outside the current window remain active for this run.",
        "- Same-title different-sync_key or v1/v2 source instances are distinct; an old stable chain must not be overwritten by a similar new source instance.",
        "- Repeated export/cache/backup rows sharing a sync_key are duplicate-suppressed rather than producing duplicate active tasks or mappings.",
        "- No deletion of unrelated/manual task state is implied by the sync policy.",
    ]
    return _truncate_chars("\n".join(lines).strip() + "\n", JUDGE_EVIDENCE_LIMITS["public_sync_policy_context"])


def _public_noop_preservation_context(case_dir: Path) -> str:
    initial_tasks = _load_expected_json(case_dir, "input/workspace/tasks/task_state.json")
    initial_history = _load_expected_json(case_dir, "input/workspace/sync/sync_history.json")
    calendar = _public_calendar(case_dir)
    window_start, window_end = _calendar_sync_window(calendar)
    events_by_sync: dict[str, list[dict[str, Any]]] = {}
    for event in calendar.get("events", []):
        if isinstance(event, dict) and event.get("sync_key"):
            events_by_sync.setdefault(str(event.get("sync_key")), []).append(event)
    tasks_by_id = _tasks_by_id(initial_tasks)
    seen: set[tuple[str, str]] = set()
    lines = [
        "# Public No-Change and Preservation Context",
        "",
        "This evidence is derived only from public initial task_state.json, public initial sync_history.json, and the public current calendar export. It exposes visible preservation-category anchors for supplemental WB Judge. It does not use hidden gold, hidden expected state, oracle prose, construction notes, private trace context, model logs, final-agent replies, or external/live-service evidence.",
        "",
        "## Public policy boundary",
        "- When an active history row and task already match the current public calendar row by stable sync_key and source fields, the human report should treat that chain as unchanged/no-op rather than as a completed update.",
        "- Existing chains that are outside the current sync window, source-missing outside the window, excluded/read-only, or otherwise preserved should not be presented as clean updates, creates, or inactive transitions unless the submitted artifacts explicitly qualify a metadata-only refresh.",
        "- Deterministic checks still own exact field equality, exact IDs/counts/timestamps, exact summary references, enum spellings, and full state-diff correctness.",
        "",
        "## Visible preservation anchors",
    ]

    def _event_position(event: dict[str, Any]) -> str:
        window_value = _within_sync_window(event.get("start_time"), window_start, window_end)
        if window_value is True:
            return "inside_window"
        if window_value is False:
            return "outside_window"
        return "window_unknown"

    def _append_anchor(category: str, mapping: dict[str, Any], task: dict[str, Any], public_events: list[dict[str, Any]], reason: str) -> None:
        mapping_id = str(mapping.get("mapping_id") or "")
        if not mapping_id or (category, mapping_id) in seen:
            return
        seen.add((category, mapping_id))
        source = task.get("source") or {}
        sync_fields = task.get("sync_fields") or {}
        sorted_events = sorted(public_events, key=lambda event: str(event.get("event_id")))
        event_flags = sorted({flag for event in sorted_events for flag in _source_flags(event)})
        event_positions = [f"{event.get('event_id')}:{_event_position(event)}" for event in sorted_events]
        lines.append(
            "- "
            + "; ".join(
                [
                    f"preservation_category={category}",
                    f"reason={reason}",
                    f"mapping_id={mapping.get('mapping_id')}",
                    f"task_id={mapping.get('task_id')}",
                    f"sync_key={mapping.get('sync_key')}",
                    f"initial_history_state={mapping.get('state')}",
                    f"initial_history_last_action={mapping.get('last_action')}",
                    f"initial_history_event_id_last_seen={mapping.get('event_id_last_seen')}",
                    f"initial_history_missing_in_current_export={mapping.get('missing_in_current_export')}",
                    f"initial_task_status={task.get('status')}",
                    f"initial_task_due_time={task.get('due_time')}",
                    f"initial_task_event_id={source.get('event_id')}",
                    f"initial_task_last_source_updated_at={source.get('last_source_updated_at')}",
                    f"source_title={sync_fields.get('source_title')}",
                    f"public_event_ids={[event.get('event_id') for event in sorted_events]}",
                    f"public_event_flags={event_flags}",
                    f"public_event_window_positions={event_positions}",
                ]
            )
        )

    for mapping in sorted(initial_history.get("mappings", []), key=lambda item: str(item.get("mapping_id"))):
        if not isinstance(mapping, dict):
            continue
        sync_key = str(mapping.get("sync_key") or "")
        task = tasks_by_id.get(mapping.get("task_id"), {})
        public_events = events_by_sync.get(sync_key, [])
        current_rows = [event for event in public_events if "current_export_row" in _source_flags(event)]
        current_event = current_rows[0] if current_rows else (public_events[0] if public_events else {})
        if mapping.get("state") == "active" and mapping.get("last_action") == "no_change":
            source = task.get("source") or {}
            already_current = bool(current_event) and source.get("event_id") == current_event.get("event_id") and source.get("last_source_updated_at") == current_event.get("updated_at") and mapping.get("event_id_last_seen") == current_event.get("event_id") and mapping.get("missing_in_current_export") is False
            reason = "active stable chain already matches public current row" if already_current else "active stable chain initially marked no_change in public history"
            _append_anchor("already_current_no_change", mapping, task, public_events, reason)
        if mapping.get("state") == "active" and any("outside_current_window" in _source_flags(event) or _within_sync_window(event.get("start_time"), window_start, window_end) is False for event in public_events):
            _append_anchor("out_of_window_existing_preserve", mapping, task, public_events, "public source row is outside the current sync window, so the existing chain should be preserved rather than treated as an in-window update")
        if mapping.get("state") == "active" and not public_events and _within_sync_window(task.get("due_time"), window_start, window_end) is False:
            _append_anchor("source_missing_outside_window_preserve", mapping, task, public_events, "no current public source row is visible and the existing task due_time is outside the current sync window, so it should remain active for this run")
        if mapping.get("state") == "excluded" or any(_source_flags(event) & {"reference_calendar", "reference_record", "archive_calendar", "do_not_sync", "source_excluded"} for event in public_events):
            _append_anchor("excluded_or_readonly_preserve", mapping, task, public_events, "public source or initial history marks this chain as excluded/read-only, so it should not be reported as an ordinary sync mutation")

    lines.extend([
        "",
        "## Judge-use boundary",
        "Judge may use this public context only to assess whether sync_summary.md and submitted state/history evidence present visible preservation anchors honestly as unchanged/no-op/out-of-window/source-missing-outside/excluded/read-only preservation, or instead overclaim them as updates, creates, inactive transitions, or unqualified completed actions. If submitted artifact summaries show changed last_action, event_id_last_seen, source event ID, or source timestamp for a public preservation anchor compared with this public context, a report that says the chain was simply unchanged should disclose that metadata/history refresh rather than presenting it as a full no-op. Judge must not require exact hidden output wording or rescore deterministic field equality.",
    ])
    return _truncate_chars("\n".join(lines).strip() + "\n", JUDGE_EVIDENCE_LIMITS["public_noop_preservation_context"])


def _public_workspace_boundary_context(case_dir: Path) -> str:
    lines = [
        "# Public Workspace Boundary Context",
        "",
        "This evidence summarizes only public local/mock workspace boundary files for supplemental WB Judge. It includes no hidden gold, hidden expected state, oracle prose, construction notes, private trace context, model logs, final-agent replies, external web evidence, or live-service evidence.",
        "",
        "## Public README excerpt",
        _read_public_source(case_dir, "input/workspace/README_先读我.md", 3500),
        "",
        "## Public local mock environment excerpt",
        _read_public_source(case_dir, "environment/local_mock_sync/README.md", 2500),
        "",
        "## Public state-diff manifest excerpt",
        _read_public_source(case_dir, "environment/state_diff_manifest.json", 3500),
        "",
        "## Boundary anchors for Judge",
        "- The workspace is local mock JSON/Markdown state, not a real calendar/task/reminder service.",
        "- Approved mutable outputs are only `input/workspace/tasks/task_state.json`, `input/workspace/sync/sync_history.json`, and `input/workspace/reports/sync_summary.md`.",
        "- Calendar source, rules, notes, README, environment files, and other public inputs are protected context and must not be treated as submitted output changes for Judge scoring.",
        "- No real external calendar, Dida/TickTick account, browser, network, API, MCP, Skill, notification, or live side effect is part of the task or Judge evidence.",
        "- Deterministic checks own exact file-boundary, protected-hash, forbidden extra-artifact, URL, secret, private-marker, and live-service-claim facts.",
    ]
    return _truncate_chars("\n".join(lines).strip() + "\n", JUDGE_EVIDENCE_LIMITS["public_workspace_boundary_context"])


def _write_judge_evidence(
    log_dir: Path,
    result: dict[str, Any],
    case_dir: Path,
    task_state: dict[str, Any] | None,
    sync_history: dict[str, Any] | None,
    summary_text: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    judge_dir = log_dir / "judge_evidence"
    judge_dir.mkdir(parents=True, exist_ok=True)
    safety_failed = _deterministic_safety_failed(result)
    submitted_summary = summary_text.strip() + "\n" if summary_text.strip() else "No submitted sync_summary.md text was available. Deterministic existence/readability checks own this failure.\n"
    submitted_task_summary = _task_semantic_summary(task_state)
    submitted_history_summary = _history_semantic_summary(sync_history)
    if safety_failed:
        withheld = (
            "# Submitted Artifact Evidence Withheld\n\n"
            "The deterministic verifier detected objective safety/leakage or forbidden external-service failures in submitted mutable artifacts. "
            "Submitted-output text and semantic summaries are withheld from Judge evidence so unsafe fragments are not routed to WB Judge activation. "
            "Use deterministic failed_checks in judge_scope_and_gate_status.md for failure attribution; do not run WB Judge on this submitted text.\n"
        )
        submitted_summary = withheld
        submitted_task_summary = withheld
        submitted_history_summary = withheld
    evidence_payloads = {
        "judge_scope_and_gate_status": _judge_scope_status(result),
        "submitted_sync_summary_text": _truncate_chars(submitted_summary, JUDGE_EVIDENCE_LIMITS["submitted_sync_summary_text"]),
        "submitted_task_state_semantic_summary": _truncate_chars(submitted_task_summary, JUDGE_EVIDENCE_LIMITS["submitted_task_state_semantic_summary"]),
        "submitted_sync_history_semantic_summary": _truncate_chars(submitted_history_summary, JUDGE_EVIDENCE_LIMITS["submitted_sync_history_semantic_summary"]),
        "public_sync_policy_context": _public_sync_policy_context(case_dir),
        "public_noop_preservation_context": _public_noop_preservation_context(case_dir),
        "public_workspace_boundary_context": _public_workspace_boundary_context(case_dir),
    }
    records: list[dict[str, Any]] = []
    for evidence_id, rel_path in JUDGE_EVIDENCE_FILES.items():
        path = log_dir / rel_path
        text = evidence_payloads[evidence_id]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        is_submitted = evidence_id.startswith("submitted_")
        records.append({
            "id": evidence_id,
            "path_role": rel_path.as_posix(),
            "relative_path": rel_path.as_posix(),
            "kind": "judge_evidence",
            "required": True,
            "text_only_public_safe": not (is_submitted and safety_failed),
            "judge_activation_usable": not (is_submitted and safety_failed),
            "submitted_text_withheld": is_submitted and safety_failed,
            "bytes": path.stat().st_size,
            "characters": len(text),
            "max_chars": JUDGE_EVIDENCE_LIMITS[evidence_id],
        })
    safety_record = {
        "deterministic_safety_failed": safety_failed,
        "submitted_output_text_withheld": safety_failed,
        "llm_judge_activation_allowed": not safety_failed,
        "policy": "withhold submitted-output text from judge_evidence and skip WB Judge activation when deterministic safety/leakage checks fail",
    }
    return records, safety_record


def evaluate(path_arg: str | Path | None = None, *, case_dir: Path = CASE_DIR, verifier_logs: str | Path | None = None) -> dict[str, Any]:
    root, root_resolution = _resolve_root(path_arg)
    gold = _load_gold(case_dir)
    expected_task = _load_expected_json(case_dir, "gold/expected/task_state.json")
    expected_history = _load_expected_json(case_dir, "gold/expected/sync_history.json")
    expected_summary = _read_expected_text(case_dir, "gold/expected/sync_summary.md")
    calendar = _public_calendar(case_dir)
    events = _event_by_id(calendar)

    preflight_checks: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    required_paths = [TASK_STATE_REL, SYNC_HISTORY_REL, SUMMARY_REL]
    for rel in required_paths:
        path = root / rel
        checks.append(_check(f"file_exists_{rel.as_posix().replace('/', '__')}", path.exists() and path.is_file(), _safe_rel(path, root), "output_contract"))

    task_state: dict[str, Any] | None = None
    sync_history: dict[str, Any] | None = None
    summary_text = ""
    task_parse_ok = False
    history_parse_ok = False
    summary_read_ok = False
    try:
        task_state = _load_json(root / TASK_STATE_REL)
        task_parse_ok = isinstance(task_state, dict)
        detail = f"tasks={len(task_state.get('tasks', []))}" if isinstance(task_state, dict) else "top-level JSON is not object"
    except Exception as exc:
        detail = f"json parse error: {exc!r}"
    checks.append(_check("task_state_json_parseable", task_parse_ok, detail, "output_contract"))

    try:
        sync_history = _load_json(root / SYNC_HISTORY_REL)
        history_parse_ok = isinstance(sync_history, dict)
        detail = f"mappings={len(sync_history.get('mappings', []))}" if isinstance(sync_history, dict) else "top-level JSON is not object"
    except Exception as exc:
        detail = f"json parse error: {exc!r}"
    checks.append(_check("sync_history_json_parseable", history_parse_ok, detail, "output_contract"))

    try:
        summary_text = _read_text(root / SUMMARY_REL)
        summary_read_ok = bool(summary_text.strip())
        detail = f"chars={len(summary_text)}"
    except Exception as exc:
        detail = f"read error: {exc!r}"
    checks.append(_check("sync_summary_readable_nonempty", summary_read_ok, detail, "output_contract"))

    protected_ok, protected_detail = _snapshot_protected_matches(root, gold)
    checks.append(_check("state_protected_hashes_unchanged", protected_ok, protected_detail, "output_contract"))
    boundary_ok, boundary_detail = _state_file_boundary(root, gold)
    checks.append(_check("state_only_three_mutable_artifacts_changed", boundary_ok, boundary_detail, "output_contract"))

    if not (task_parse_ok and history_parse_ok and task_state is not None and sync_history is not None):
        parse_failures = []
        if not task_parse_ok or task_state is None:
            parse_failures.append("task_state_json_parseable")
        if not history_parse_ok or sync_history is None:
            parse_failures.append("sync_history_json_parseable")
        _append_parse_failure_contract_checks(checks, gold, expected_history, root, parse_failures)
        result = _build_result(checks, preflight_checks)
        if verifier_logs:
            _write_verifier_logs(Path(verifier_logs), root, result, case_dir, task_state, sync_history, summary_text)
        return result

    task_list = task_state.get("tasks", [])
    mapping_list = sync_history.get("mappings", [])
    task_ids = [task.get("task_id") for task in task_list if isinstance(task, dict)]
    mapping_ids = [mapping.get("mapping_id") for mapping in mapping_list if isinstance(mapping, dict)]
    checks.append(_check("task_state_schema_required_top_level", isinstance(task_state.get("state_meta"), dict) and isinstance(task_state.get("lists"), list) and isinstance(task_list, list), f"keys={sorted(task_state.keys())}", "output_contract"))
    checks.append(_check("sync_history_schema_required_top_level", isinstance(sync_history.get("history_meta"), dict) and isinstance(sync_history.get("sync_window"), dict) and isinstance(mapping_list, list) and isinstance(sync_history.get("suppressed_duplicates"), list), f"keys={sorted(sync_history.keys())}", "output_contract"))
    checks.append(_check("task_ids_unique", len(task_ids) == len(set(task_ids)) and all(task_ids), f"task_ids={task_ids}", "duplicate_idempotency"))
    checks.append(_check("mapping_ids_unique", len(mapping_ids) == len(set(mapping_ids)) and all(mapping_ids), f"mapping_ids={mapping_ids}", "duplicate_idempotency"))

    expected_by_task = _tasks_by_id(expected_task)
    actual_by_task = _tasks_by_id(task_state)
    expected_by_mapping = _mappings_by_id(expected_history)
    actual_by_mapping = _mappings_by_id(sync_history)
    actual_active_tasks_by_sync = _tasks_by_sync_key(task_state, status="active")
    actual_active_mappings_by_sync = _mappings_by_sync_key(sync_history, state="active")
    initial_task_ids = set(_tasks_by_id(_load_initial_json(case_dir, "input/workspace/tasks/task_state.json")))
    initial_mapping_ids = set(_mappings_by_id(_load_initial_json(case_dir, "input/workspace/sync/sync_history.json")))

    created_event_ids = set(_expected_event_specs(gold))
    expected_generated_task_ids = {
        task_id
        for task_id, task in expected_by_task.items()
        if (task.get("source") or {}).get("event_id") in created_event_ids
    }
    expected_generated_mapping_ids = {
        mapping_id
        for mapping_id, mapping in expected_by_mapping.items()
        if mapping.get("event_id_last_seen") in created_event_ids
    }
    expected_existing_ids = set(expected_by_task) - expected_generated_task_ids
    expected_public_mapping_ids = set(expected_by_mapping) - expected_generated_mapping_ids
    checks.append(_check("preexisting_task_ids_all_preserved", expected_existing_ids <= set(actual_by_task), f"missing={sorted(expected_existing_ids - set(actual_by_task))}", "stale_noop_preserve"))
    checks.append(_check("preexisting_mapping_ids_all_preserved", expected_public_mapping_ids <= set(actual_by_mapping), f"missing={sorted(expected_public_mapping_ids - set(actual_by_mapping))}", "stale_noop_preserve"))

    # Stable matched updates: exact IDs are public and must remain stable.
    for item in gold["expected_decisions"]["updated_existing"]:
        task_id = item["task_id"]
        mapping_id = item["mapping_id"]
        event = events[item["event_id"]]
        task = actual_by_task.get(task_id, {})
        mapping = actual_by_mapping.get(mapping_id, {})
        ok, detail = _task_core_matches_event(task, event, item) if task else (False, f"missing task {task_id}")
        checks.append(_check(f"stable_update_{task_id}_task_fields", ok, detail, "matching_and_updates"))
        exp_task = expected_by_task[task_id]
        manual_keys = ["task_id", "created_at", "manual_note", "manual_tags", "manual_lock"]
        manual_ok, manual_detail = _dict_subset_equal(task, exp_task, manual_keys) if task else (False, f"missing task {task_id}")
        checks.append(_check(f"stable_update_{task_id}_manual_fields_preserved", manual_ok, manual_detail, "stale_noop_preserve"))
        ok, detail = _mapping_core_matches_event(mapping, task, event, "updated_from_calendar") if task and mapping else (False, f"missing mapping {mapping_id} or task {task_id}")
        checks.append(_check(f"stable_update_{mapping_id}_history_fields", ok, detail, "matching_and_updates"))
        if task_id == "task-local-2017":
            prior_task = _tasks_by_id(_load_initial_json(case_dir, "input/workspace/tasks/task_state.json")).get(task_id, {})
            prior_mapping = _mappings_by_id(_load_initial_json(case_dir, "input/workspace/sync/sync_history.json")).get(mapping_id, {})
            mobile_ok = bool(prior_task) and (prior_task.get("source") or {}).get("sync_key") == event["sync_key"] and (prior_mapping.get("sync_key") == event["sync_key"]) and task.get("task_id") == prior_task.get("task_id")
            checks.append(_check("stable_update_mobile_cache_training_matched_not_duplicated", mobile_ok, {"prior_task_id": prior_task.get("task_id"), "prior_mapping_id": prior_mapping.get("mapping_id"), "sync_key": event["sync_key"]}, "matching_and_updates"))

    # New creates: validate by source linkage and uniqueness, not hidden exact generated IDs.
    for event_id, spec in _expected_event_specs(gold).items():
        event = events[event_id]
        active_tasks = actual_active_tasks_by_sync.get(event["sync_key"], [])
        one_task_ok = len(active_tasks) == 1
        checks.append(_check(f"new_create_{event_id}_one_active_task_by_sync_key", one_task_ok, f"active_task_ids={[task.get('task_id') for task in active_tasks]}", "matching_and_updates"))
        task = active_tasks[0] if one_task_ok else (active_tasks[0] if active_tasks else {})
        ok, detail = _task_core_matches_event(task, event, spec) if task else (False, f"no task for {event['sync_key']}")
        checks.append(_check(f"new_create_{event_id}_task_source_linkage", ok, detail, "matching_and_updates"))
        nonpublic_task_ok = bool(task) and task.get("task_id") not in initial_task_ids
        checks.append(_check(f"new_create_{event_id}_uses_nonpublic_task_id", nonpublic_task_ok, f"task_id={task.get('task_id') if task else None}; initial_task_ids={sorted(initial_task_ids)}", "matching_and_updates"))
        active_maps = actual_active_mappings_by_sync.get(event["sync_key"], [])
        one_map_ok = len(active_maps) == 1
        checks.append(_check(f"new_create_{event_id}_one_active_mapping_by_sync_key", one_map_ok, f"active_mapping_ids={[mapping.get('mapping_id') for mapping in active_maps]}", "duplicate_idempotency"))
        mapping = active_maps[0] if one_map_ok else (active_maps[0] if active_maps else {})
        nonpublic_mapping_ok = bool(mapping) and mapping.get("mapping_id") not in initial_mapping_ids
        checks.append(_check(f"new_create_{event_id}_uses_nonpublic_mapping_id", nonpublic_mapping_ok, f"mapping_id={mapping.get('mapping_id') if mapping else None}; initial_mapping_ids={sorted(initial_mapping_ids)}", "duplicate_idempotency"))
        ok, detail = _mapping_core_matches_event(mapping, task, event, "created_task") if task and mapping else (False, f"no active mapping/task pair for {event['sync_key']}")
        checks.append(_check(f"new_create_{event_id}_mapping_source_linkage", ok, detail, "matching_and_updates"))

    # Cancelled/source-missing inactive transitions.
    for item in gold["expected_decisions"]["inactive_tasks"]:
        task_id = item["task_id"]
        mapping_id = item["mapping_id"]
        task = actual_by_task.get(task_id, {})
        mapping = actual_by_mapping.get(mapping_id, {})
        reason = item["reason"]
        task_ok = bool(task) and task.get("status") == "inactive" and task.get("archived") is True and (task.get("sync_fields") or {}).get("inactive_reason") == reason
        checks.append(_check(f"inactive_{task_id}_{reason}_task_status", task_ok, {"status": task.get("status"), "archived": task.get("archived"), "inactive_reason": (task.get("sync_fields") or {}).get("inactive_reason")}, "stale_noop_preserve"))
        source_ok = bool(task) and (task.get("source") or {}).get("last_synced_at") == RUN_TIME and task.get("updated_at") == RUN_TIME
        if "event_id" in item:
            event = events[item["event_id"]]
            source_ok = source_ok and (task.get("source") or {}).get("event_id") == event["event_id"] and (task.get("source") or {}).get("last_source_updated_at") == event["updated_at"]
        checks.append(_check(f"inactive_{task_id}_{reason}_source_fields", source_ok, {"source": task.get("source"), "updated_at": task.get("updated_at")}, "matching_and_updates"))
        mapping_ok = bool(mapping) and mapping.get("state") == "inactive" and mapping.get("last_action") == reason and mapping.get("last_synced_at") == RUN_TIME
        if reason == "source_missing_current_export":
            mapping_ok = mapping_ok and mapping.get("missing_in_current_export") is True
        else:
            mapping_ok = mapping_ok and mapping.get("missing_in_current_export") is False
        checks.append(_check(f"inactive_{mapping_id}_{reason}_history_fields", mapping_ok, mapping, "stale_noop_preserve"))

    # No-op and out-of-scope synced records are exact-preserve.
    for task_id in gold["expected_decisions"]["no_change_tasks"]:
        actual = actual_by_task.get(task_id)
        expected = expected_by_task[task_id]
        checks.append(_check(f"noop_preserve_{task_id}_exact", actual == expected, {"expected": expected, "actual": actual}, "stale_noop_preserve"))
    noop_mapping_ids = [
        mapping_id
        for mapping_id, mapping in expected_by_mapping.items()
        if mapping.get("task_id") in gold["expected_decisions"]["no_change_tasks"] or mapping.get("state") == "excluded"
    ]
    for mapping_id in noop_mapping_ids:
        actual = actual_by_mapping.get(mapping_id)
        expected = expected_by_mapping[mapping_id]
        checks.append(_check(f"noop_preserve_{mapping_id}_exact", actual == expected, {"expected": expected, "actual": actual}, "stale_noop_preserve"))

    # Manual/unrelated tasks exact-preserve.
    for task_id in gold["expected_decisions"]["manual_preserve_tasks"]:
        actual = actual_by_task.get(task_id)
        expected = expected_by_task[task_id]
        checks.append(_check(f"manual_preserve_{task_id}_exact", actual == expected, {"expected": expected, "actual": actual}, "stale_noop_preserve"))

    # Duplicate suppression and source filtering.
    suppressed_ids = [item.get("source_event_id") for item in sync_history.get("suppressed_duplicates", [])]
    expected_dups = gold["expected_decisions"]["suppressed_duplicate_event_ids"]
    checks.append(_check("suppressed_duplicates_expected_event_ids_present", set(expected_dups) <= set(suppressed_ids), f"suppressed_ids={suppressed_ids}", "duplicate_idempotency"))
    checks.append(_check("suppressed_duplicates_total_count_preserved", len(sync_history.get("suppressed_duplicates", [])) == gold["expected_counts"]["suppressed_duplicates_total"], f"count={len(sync_history.get('suppressed_duplicates', []))}", "duplicate_idempotency"))
    for event_id in expected_dups:
        sync_key = events[event_id]["sync_key"]
        active_task_count = len(actual_active_tasks_by_sync.get(sync_key, []))
        active_mapping_count = len(actual_active_mappings_by_sync.get(sync_key, []))
        checks.append(_check(f"duplicate_event_{_compact(event_id)}_single_active_task_mapping_for_sync_key", active_task_count == 1 and active_mapping_count == 1, {"sync_key": sync_key, "active_task_count": active_task_count, "active_mapping_count": active_mapping_count}, "duplicate_idempotency"))

    excluded_sync_keys = [events[event_id]["sync_key"] for event_id in gold["expected_decisions"]["excluded_event_ids"]]
    wrong_excluded_active = [key for key in excluded_sync_keys if key not in {"cal::uid-after-window-20260724::2026-07-24"} and (actual_active_tasks_by_sync.get(key) or actual_active_mappings_by_sync.get(key))]
    # The out-of-window key has a preexisting active task/mapping that must be preserved, not newly created.
    checks.append(_check("excluded_readonly_before_archive_no_active_task_or_mapping", not wrong_excluded_active, f"wrong_excluded_active={wrong_excluded_active}", "stale_noop_preserve"))
    checks.append(_check("out_of_window_existing_task_preserved_not_duplicated", len(actual_active_tasks_by_sync.get("cal::uid-after-window-20260724::2026-07-24", [])) == 1 and len(actual_active_mappings_by_sync.get("cal::uid-after-window-20260724::2026-07-24", [])) == 1, {"tasks": actual_active_tasks_by_sync.get("cal::uid-after-window-20260724::2026-07-24", []), "mappings": actual_active_mappings_by_sync.get("cal::uid-after-window-20260724::2026-07-24", [])}, "stale_noop_preserve"))
    after_window_missing_key = "cal::uid-local-after-window-missing-20260722::2026-07-22"
    checks.append(_check("source_missing_after_window_existing_task_preserved_active", len(actual_active_tasks_by_sync.get(after_window_missing_key, [])) == 1 and len(actual_active_mappings_by_sync.get(after_window_missing_key, [])) == 1, {"tasks": actual_active_tasks_by_sync.get(after_window_missing_key, []), "mappings": actual_active_mappings_by_sync.get(after_window_missing_key, [])}, "stale_noop_preserve"))

    # Aggregate uniqueness/idempotency.
    active_task_sync_keys = [((task.get("source") or {}).get("sync_key")) for task in task_list if isinstance(task, dict) and task.get("status") == "active" and (task.get("source") or {}).get("kind") == "mock_calendar"]
    active_mapping_sync_keys = [mapping.get("sync_key") for mapping in mapping_list if isinstance(mapping, dict) and mapping.get("state") == "active" and mapping.get("task_id")]
    duplicate_active_task_keys = sorted({key for key in active_task_sync_keys if key and active_task_sync_keys.count(key) > 1})
    duplicate_active_mapping_keys = sorted({key for key in active_mapping_sync_keys if key and active_mapping_sync_keys.count(key) > 1})
    checks.append(_check("idempotency_no_duplicate_active_tasks_per_sync_key", not duplicate_active_task_keys, f"duplicate_active_task_keys={duplicate_active_task_keys}", "duplicate_idempotency"))
    checks.append(_check("idempotency_no_duplicate_active_mappings_per_sync_key", not duplicate_active_mapping_keys, f"duplicate_active_mapping_keys={duplicate_active_mapping_keys}", "duplicate_idempotency"))
    active_mapping_links_ok = True
    link_problems: list[str] = []
    for mapping in mapping_list:
        if not isinstance(mapping, dict) or mapping.get("state") != "active" or not mapping.get("task_id"):
            continue
        task = actual_by_task.get(mapping.get("task_id"))
        if not task or task.get("status") != "active" or (task.get("source") or {}).get("sync_key") != mapping.get("sync_key"):
            active_mapping_links_ok = False
            link_problems.append(f"{mapping.get('mapping_id')}->{mapping.get('task_id')} sync_key={mapping.get('sync_key')}")
    checks.append(_check("idempotency_active_mappings_link_to_active_tasks", active_mapping_links_ok, f"link_problems={link_problems[:20]}", "duplicate_idempotency"))
    checks.append(_check("expected_task_total_count", len(task_list) == gold["expected_counts"]["tasks_total"], f"count={len(task_list)} expected={gold['expected_counts']['tasks_total']}", "output_contract"))
    checks.append(_check("expected_mapping_total_count", len(mapping_list) == gold["expected_counts"]["mappings_total"], f"count={len(mapping_list)} expected={gold['expected_counts']['mappings_total']}", "output_contract"))
    checks.append(_check("active_current_window_mapping_count", _active_current_mapping_count(sync_history) == gold["expected_counts"]["active_mappings_for_current_window_after_run"], f"count={_active_current_mapping_count(sync_history)}", "duplicate_idempotency"))

    # Hidden oracle exact state catches content drift while separate creation checks avoid exact new-ID dependence as primary diagnosis.
    # New task/mapping IDs may differ, so exact file equality is limited to non-generated public IDs and aggregate fields.
    expected_existing_core_ok = True
    exact_problems: list[str] = []
    for task_id in sorted(expected_existing_ids):
        if actual_by_task.get(task_id) != expected_by_task.get(task_id):
            # Updated/inactive existing tasks are expected to match exactly because their IDs and mutable fields are public.
            exact_problems.append(task_id)
            expected_existing_core_ok = False
    checks.append(_check("existing_public_id_tasks_match_expected_state", expected_existing_core_ok, f"mismatched_existing_task_ids={exact_problems[:20]}", "matching_and_updates"))
    mapping_exact_problems = [mapping_id for mapping_id in sorted(expected_public_mapping_ids) if actual_by_mapping.get(mapping_id) != expected_by_mapping.get(mapping_id)]
    checks.append(_check("existing_public_id_mappings_match_expected_state", not mapping_exact_problems, f"mismatched_existing_mapping_ids={mapping_exact_problems[:20]}", "matching_and_updates"))

    # Summary checks.
    headings_present = all(heading in summary_text for heading in REQUIRED_SUMMARY_HEADINGS)
    checks.append(_check("summary_required_headings_present", headings_present, {heading: heading in summary_text for heading in REQUIRED_SUMMARY_HEADINGS}, "summary_consistency"))
    summary_sections = {heading: _section(summary_text, heading) for heading in REQUIRED_SUMMARY_HEADINGS}
    created_refs = [item["event_id"] for item in gold["expected_decisions"]["created_from_events"]] + [item["sync_key"] for item in gold["expected_decisions"]["created_from_events"]]
    ok, detail = _summary_has_refs(summary_sections["## 新建待办"], created_refs)
    checks.append(_check("summary_new_creates_refs_match_state", ok, detail, "summary_consistency"))
    update_refs = [item["task_id"] for item in gold["expected_decisions"]["updated_existing"]] + [item["mapping_id"] for item in gold["expected_decisions"]["updated_existing"]] + [item["event_id"] for item in gold["expected_decisions"]["updated_existing"]]
    ok, detail = _summary_has_refs(summary_sections["## 更新已有同步项"], update_refs)
    checks.append(_check("summary_updates_refs_match_state", ok, detail, "summary_consistency"))
    inactive_refs = []
    for item in gold["expected_decisions"]["inactive_tasks"]:
        inactive_refs.extend([item["task_id"], item["mapping_id"], item["reason"]])
        if item.get("event_id"):
            inactive_refs.append(item["event_id"])
        if item.get("sync_key"):
            inactive_refs.append(item["sync_key"])
    ok, detail = _summary_has_refs(summary_sections["## 置为 inactive"], inactive_refs)
    checks.append(_check("summary_inactive_refs_and_reasons_match_state", ok, detail, "summary_consistency"))
    noop_refs = ["task-local-2006", "map-local-1006", "evt-20260716-briefing-shift-A", "task-local-2009", "map-local-1007", "evt-20260724-after-window-A", "task-local-2018", "map-local-1012", "cal::uid-local-after-window-missing-20260722::2026-07-22"]
    ok, detail = _summary_has_refs(summary_sections["## 保持不变"], noop_refs)
    checks.append(_check("summary_noop_refs_match_state", ok, detail, "summary_consistency"))
    duplicate_excluded_refs = gold["expected_decisions"]["suppressed_duplicate_event_ids"] + gold["expected_decisions"]["excluded_event_ids"] + ["map-local-1010"]
    ok, detail = _summary_has_refs(summary_sections["## 重复或排除"], duplicate_excluded_refs)
    checks.append(_check("summary_duplicate_excluded_refs_match_state", ok, detail, "summary_consistency"))
    manual_refs = gold["expected_decisions"]["manual_preserve_tasks"]
    ok, detail = _summary_has_refs(summary_sections["## 手工/无关任务保留"], manual_refs)
    checks.append(_check("summary_manual_preserve_refs_match_state", ok, detail, "summary_consistency"))
    count_terms = ["新建 4", "更新 3", "inactive 4", "保持 5", "重复抑制 4", "排除 4", "保留 7"]
    count_ok = all(term in summary_text or _compact(term) in _compact(summary_text) for term in count_terms)
    checks.append(_check("summary_category_counts_match_expected", count_ok, f"required_terms={count_terms}", "summary_consistency"))
    boundary_terms_ok = _contains_any(summary_sections["## 边界确认"], ["未调用", "没有调用", "no-live-service", "no live service"]) and _contains_any(summary_sections["## 边界确认"], ["只", "本地", "三个", "只在"])
    checks.append(_check("summary_boundary_confirmation_present", boundary_terms_ok, summary_sections["## 边界确认"][:500], "summary_consistency"))

    # Leakage/live-service checks across all three mutable artifacts.
    mutable_text_parts: list[str] = []
    for rel in [TASK_STATE_REL, SYNC_HISTORY_REL, SUMMARY_REL]:
        path = root / rel
        if path.exists():
            mutable_text_parts.append(_read_text(path))
    mutable_text = "\n".join(mutable_text_parts)
    leakage = _text_leakage_hits(mutable_text)
    checks.append(_check("no_external_urls", not leakage["urls"], leakage["urls"], "output_contract"))
    checks.append(_check("no_secret_like_strings", not leakage["secrets"], leakage["secrets"], "output_contract"))
    checks.append(_check("no_private_paths_or_source_locator_markers", not leakage["private_markers"], leakage["private_markers"], "output_contract"))
    checks.append(_check("no_positive_live_or_external_service_claims", not leakage["positive_live_claims"], leakage["positive_live_claims"], "output_contract"))

    # Public derivation consistency: hidden gold remains derivable from approved public files.
    derivation_ok = gold.get("uses_judge") is False and gold.get("uses_vlm_judge") is False and "approved public files" in gold.get("derivation_boundary", "") and gold.get("created_after_p6_gate") == "G-P6R2-001"
    checks.append(_check("gold_boundary_deterministic_public_derivation", derivation_ok, gold.get("derivation_boundary"), "output_contract"))

    result = _build_result(checks, preflight_checks)
    if verifier_logs:
        _write_verifier_logs(Path(verifier_logs), root, result, case_dir, task_state, sync_history, summary_text)
    return result


def _summarize_checks_for_artifact(checks: list[dict[str, Any]]) -> dict[str, Any]:
    by_group: dict[str, dict[str, int]] = {}
    records: list[dict[str, Any]] = []
    for check in checks:
        group = str(check.get("group") or "ungrouped")
        bucket = by_group.setdefault(group, {"passed": 0, "failed": 0, "total": 0})
        bucket["total"] += 1
        if check.get("passed") is True:
            bucket["passed"] += 1
        else:
            bucket["failed"] += 1
        records.append({
            "name": check.get("name"),
            "group": group,
            "passed": bool(check.get("passed")),
        })
    return {"by_group": by_group, "checks": records}


def _write_verifier_logs(
    log_dir: Path,
    root: Path,
    result: dict[str, Any],
    case_dir: Path,
    task_state: dict[str, Any] | None,
    sync_history: dict[str, Any] | None,
    summary_text: str,
) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    artifact_text = log_dir / "artifact_text"
    raw_artifacts = log_dir / "raw_artifacts"
    artifact_text.mkdir(parents=True, exist_ok=True)
    raw_artifacts.mkdir(parents=True, exist_ok=True)

    summary_sections = {heading: _section(summary_text, heading) for heading in REQUIRED_SUMMARY_HEADINGS}
    (artifact_text / "sync_summary_sections.json").write_text(json.dumps(summary_sections, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    raw_records: list[dict[str, Any]] = []
    for rel in [TASK_STATE_REL, SYNC_HISTORY_REL, SUMMARY_REL]:
        src = root / rel
        if src.exists() and src.is_file():
            dest = raw_artifacts / rel.as_posix().replace("/", "__")
            shutil.copy2(src, dest)
            raw_records.append({
                "rel_path": rel.as_posix(),
                "raw_artifact": _log_rel(dest, log_dir),
                "sha256": _sha256(src),
                "size_bytes": src.stat().st_size,
                "visibility": "verifier_only",
            })

    judge_evidence, judge_evidence_safety = _write_judge_evidence(log_dir, result, case_dir, task_state, sync_history, summary_text)
    failed_checks = [check.get("name") for check in result.get("checks", []) if not check.get("passed")]
    preflight_failed_checks = [check.get("name") for check in result.get("preflight_checks", []) if not check.get("passed")]
    deterministic_gated_pass = result.get("passed_count") == result.get("total_count") and result.get("preflight_passed_count") == result.get("preflight_total_count")
    check_summary = _summarize_checks_for_artifact(result.get("checks", []))
    preflight_summary = _summarize_checks_for_artifact(result.get("preflight_checks", []))
    deterministic_summary = {
        "passed_count": result.get("passed_count"),
        "total_count": result.get("total_count"),
        "pass_rate": result.get("pass_rate"),
        "preflight_passed_count": result.get("preflight_passed_count"),
        "preflight_total_count": result.get("preflight_total_count"),
        "deterministic_gated_pass": deterministic_gated_pass,
        "failed_checks": failed_checks,
        "preflight_failed_checks": preflight_failed_checks,
        "check_group_summary": check_summary["by_group"],
        "preflight_group_summary": preflight_summary["by_group"],
        "checks": check_summary["checks"],
        "preflight_checks": preflight_summary["checks"],
        "redaction_policy": "check detail payloads are omitted from Judge-adjacent artifact_text to avoid exposing hidden expected state or verifier-only oracle data",
    }
    (artifact_text / "deterministic_eval_summary.json").write_text(json.dumps(deterministic_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "case_slug": "calendar_dida_sync_state",
        "parse_failure_contract_total_count": CONTRACT_TOTAL_COUNT,
        "parse_failure_downstream_not_evaluable_checks_counted": True,
        "deterministic_only_release": False,
        "deterministic_component_preserved": True,
        "deterministic_passed": deterministic_gated_pass,
        "judge_planned": True,
        "uses_judge": True,
        "judge_config_path": "tests/judge.yaml or verifier/judge.yaml after smoke packaging materializes case-local tests/judge.yaml",
        "judge_evidence_extraction_created_by_this_worker": True,
        "judge_evidence_extraction_fixed_by_this_worker": True,
        "judge_activation_allowed": judge_evidence_safety["llm_judge_activation_allowed"],
        "judge_activation_block_reason": None if judge_evidence_safety["llm_judge_activation_allowed"] else "deterministic_safety_or_leakage_check_failed",
        "vlm_judge_planned": False,
        "uses_vlm_judge": False,
        "wb_judge_invoked": False,
        "private_trace_dependency": False,
        "source_root_resolution": "verifier_input_root",
        "artifact_text": [
            "artifact_text/deterministic_eval_summary.json",
            "artifact_text/sync_summary_sections.json",
        ],
        "raw_artifacts": raw_records,
        "judge_evidence": judge_evidence,
        "judge_evidence_safety": judge_evidence_safety,
        "score": {
            "passed_count": result.get("passed_count"),
            "total_count": result.get("total_count"),
            "pass_rate": result.get("pass_rate"),
        },
        "deterministic_scope_note": "WB Judge evidence is non-scored verifier-owned extraction. It must not alter deterministic checks, exact expected-state semantics, failed-check attribution, or objective safety/leakage gates.",
    }
    (log_dir / "artifact_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic verifier for calendar_dida_sync_state")
    parser.add_argument("root", nargs="?", default=str(CASE_DIR), help="Case root or submitted workspace root")
    parser.add_argument("--case-dir", default=str(CASE_DIR), help="Case directory containing gold/ and evaluator/")
    parser.add_argument("--verifier-logs", default=None, help="Optional verifier evidence output directory")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON result")
    args = parser.parse_args(argv)
    result = evaluate(args.root, case_dir=Path(args.case_dir), verifier_logs=args.verifier_logs)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0 if result["passed_count"] == result["total_count"] and result.get("preflight_passed_count") == result.get("preflight_total_count") else 1


if __name__ == "__main__":
    raise SystemExit(main())
