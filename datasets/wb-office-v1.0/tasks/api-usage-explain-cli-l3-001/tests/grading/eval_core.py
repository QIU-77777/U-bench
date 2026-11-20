#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


CASE_DIR = Path(os.environ.get("WB_BENCH_CASE_DIR", "/workspace"))
GOLD_PATH = Path(os.environ.get("WB_BENCH_GOLD_PATH", "/tests/gold/gold_answer.json"))
WORKSPACE_REL = Path("input/sample_workspace/citrinectl")

CJK_RE = re.compile(r"[一-鿿]")
HEADING_RE = re.compile(r"^\s{0,3}#{1,4}\s+\S+", re.MULTILINE)
PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"(?:input/sample_workspace/citrinectl/)?"
    r"(?:(?:docs|src|config|schemas|examples|tests|notes)/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+|README\.md|pyproject\.toml)"
)

COMMON_OUTPUT_FILENAMES = {
    "answer.md",
    "result.md",
    "usage.md",
    "usage_explanation.md",
    "cli_api_usage_explanation.md",
    "citrinectl_usage.md",
    "citrinectl_usage_explanation.md",
}

UNSUPPORTED_MARKERS = [
    "不支持",
    "不能",
    "不可",
    "未注册",
    "未接入",
    "没有接入",
    "未 wire",
    "未 wired",
    "not supported",
    "unsupported",
    "not registered",
    "not wired",
    "experimental",
    "实验",
    "roadmap",
    "规划",
    "future",
    "planning",
    "draft",
    "历史",
    "旧",
    "stale",
    "legacy",
    "pre-0.4",
    "v1",
]

SUPPORT_MARKERS = ["支持", "supported", "current", "当前", "可用", "可以使用", "已接入", "registered", "wired"]

PRIVATE_PATTERNS = [
    # Generic release-safety classes only; do not embed concrete source locator values.
    # Keep absolute local paths anchored so public relative paths such as
    # examples/data/sample-items.txt are not treated as /data/... leaks.
    re.compile(r"(?<![A-Za-z0-9_.-])/(?:data|home|Users)/[^\s)\]}>]+", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_.-])[A-Za-z]:[\\/][^\s)\]}>]+"),
    re.compile(r"\b[\w.-]+\.parquet\b", re.IGNORECASE),
    re.compile(r"\b(?:request_id|conversation_id|source_locator|private_source_access)\b", re.IGNORECASE),
    re.compile(r"\b[a-f0-9]{32}\b", re.IGNORECASE),
    re.compile(r"\b[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\b", re.IGNORECASE),
    re.compile(r"\b(?:credential|credentials|secret|token|api[_-]?key)\b", re.IGNORECASE),
]


class EvalInputError(RuntimeError):
    pass


def _load_gold(gold_path: Path = GOLD_PATH) -> dict[str, Any]:
    with gold_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _build_result(checks: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for check in checks if check["passed"])
    total = len(checks)
    return {
        "passed_count": passed,
        "total_count": total,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "checks": checks,
    }


def _check(checks: list[dict[str, Any]], group: str, name: str, passed: bool, detail: Any) -> None:
    checks.append({"name": name, "group": group, "passed": bool(passed), "detail": detail})


def _norm(text: Any) -> str:
    return "" if text is None else str(text)


def _lower(text: Any) -> str:
    return _norm(text).casefold()


def _contains_all(text: str, tokens: list[str]) -> bool:
    lowered = _lower(text)
    return all(token.casefold() in lowered for token in tokens)


def _contains_any(text: str, tokens: list[str]) -> bool:
    lowered = _lower(text)
    return any(token.casefold() in lowered for token in tokens)


def _has_number_or_assignment(text: str, key: str, value: str) -> bool:
    pattern = re.compile(rf"{re.escape(key)}\s*[:=：]?\s*`?{re.escape(value)}`?", re.IGNORECASE)
    return bool(pattern.search(text)) or (key.casefold() in _lower(text) and value.casefold() in _lower(text))


def _window_around(text: str, needle: str, before: int = 120, after: int = 180) -> list[str]:
    windows: list[str] = []
    for match in re.finditer(re.escape(needle), text, flags=re.IGNORECASE):
        windows.append(text[max(0, match.start() - before) : min(len(text), match.end() + after)])
    return windows


def _near_any(text: str, needle: str, markers: list[str], before: int = 120, after: int = 180) -> bool:
    return any(_contains_any(window, markers) for window in _window_around(text, needle, before, after))


def _canonical_path(path: str) -> str:
    prefix = "input/sample_workspace/citrinectl/"
    return path[len(prefix) :] if path.startswith(prefix) else path


def _extract_path_mentions(answer_text: str, allowed_paths: set[str]) -> tuple[set[str], list[str]]:
    cited: set[str] = set()
    invalid: list[str] = []
    for raw in PATH_RE.findall(answer_text):
        canonical = _canonical_path(raw.rstrip(".,;:，。；、)］]`'\""))
        if canonical in allowed_paths:
            cited.add(canonical)
        elif canonical not in invalid:
            invalid.append(canonical)
    return cited, invalid


def _compute_snapshot(root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    if not root.exists():
        return {"workspace_root": str(root), "file_count": 0, "tree_sha256": None, "files": []}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        data = path.read_bytes()
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
            }
        )
    roll = hashlib.sha256()
    for item in files:
        roll.update(item["path"].encode("utf-8"))
        roll.update(b"\0")
        roll.update(item["sha256"].encode("utf-8"))
        roll.update(b"\0")
        roll.update(str(item["size_bytes"]).encode("utf-8"))
        roll.update(b"\n")
    return {"workspace_root": str(root), "file_count": len(files), "tree_sha256": roll.hexdigest(), "files": files}


def _compare_snapshot(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    expected_by_path = {item["path"]: item for item in expected.get("files", [])}
    actual_by_path = {item["path"]: item for item in actual.get("files", [])}
    missing = sorted(set(expected_by_path) - set(actual_by_path))
    extra = sorted(set(actual_by_path) - set(expected_by_path))
    modified = sorted(
        path
        for path in set(expected_by_path) & set(actual_by_path)
        if expected_by_path[path].get("sha256") != actual_by_path[path].get("sha256")
        or expected_by_path[path].get("size_bytes") != actual_by_path[path].get("size_bytes")
    )
    return {"missing": missing, "extra": extra, "modified": modified}


def _common_output_files(case_dir: Path) -> list[str]:
    found: list[str] = []
    check_roots = [case_dir, case_dir / WORKSPACE_REL]
    for root in check_roots:
        if not root.exists():
            continue
        for name in COMMON_OUTPUT_FILENAMES:
            path = root / name
            if path.exists():
                found.append(path.relative_to(case_dir).as_posix())
    return sorted(set(found))


def _feature_contexts(answer_text: str, feature: str) -> list[str]:
    contexts = [line.strip() for line in answer_text.splitlines() if feature.casefold() in line.casefold()]
    if contexts:
        return contexts
    return _window_around(answer_text, feature, before=80, after=120)


def _strip_citation_parentheticals(context: str) -> str:
    return re.sub(
        r"[（(][^）)]*(?:docs/|src/|config/|schemas/|examples/|tests/|notes/|README\.md|pyproject\.toml)[^）)]*[）)]",
        "",
        context,
    )


def _feature_context_has_any(answer_text: str, feature: str, markers: list[str]) -> bool:
    return any(_contains_any(_strip_citation_parentheticals(context), markers) for context in _feature_contexts(answer_text, feature))


def _timeout_ambiguity_caveat_present(answer_text: str) -> bool:
    markers = ["歧义", "不一致", "ambiguous", "ambiguity", "caveat", "命名不一致", "不是两个字段", "不要编造"]
    for block in re.split(r"\n\s*\n", answer_text):
        clean = _strip_citation_parentheticals(block)
        if "timeout" in clean and "timeout_seconds" in clean and _contains_any(clean, markers):
            return True
    return False


def _api_no_format_kwarg_caveat_present(answer_text: str) -> bool:
    negative_markers = ["没有", "不接受", "不暴露", "不支持", "不能", "no", "does not accept", "does not expose"]
    rendering_markers = ["format", "format=\"table\"", "format 参数", "format keyword", "渲染", "rendering", "to_records", "to_summary"]
    for context in _feature_contexts(answer_text, "scan_job"):
        clean = _strip_citation_parentheticals(context)
        if _contains_any(clean, negative_markers) and _contains_any(clean, rendering_markers):
            return True
    return False


def _config_resolution_order_present(answer_text: str) -> bool:
    order_markers = ["顺序", "优先级", "override", "覆盖", "层级", "resolution", "先", "最后"]
    defaults_markers = ["config/defaults.yaml", "packaged defaults", "defaults"]
    profile_markers = ["config/profiles.example.yaml", "named profile", "命名 profile", "profile"]
    cli_markers = ["CLI flag", "CLI flags", "CLI 参数", "命令行", "--format", "--include-warnings", "--profile"]
    arrow_pattern = re.compile(
        r"(?:packaged\s+defaults|defaults|config/defaults\.yaml|默认)[\s\S]{0,900}"
        r"(?:named\s+profile|命名\s*profile|profile|config/profiles\.example\.yaml)[\s\S]{0,900}"
        r"(?:CLI\s+flags?|CLI\s*参数|命令行|--format|--include-warnings|--profile)",
        re.IGNORECASE,
    )
    if arrow_pattern.search(answer_text) and _contains_any(answer_text, order_markers):
        return True
    for block in re.split(r"\n\s*\n", answer_text):
        clean = _strip_citation_parentheticals(block)
        if (
            _contains_any(clean, defaults_markers)
            and _contains_any(clean, profile_markers)
            and _contains_any(clean, cli_markers)
            and _contains_any(clean, order_markers)
        ):
            return True
    return False


def _config_no_env_format_override_present(answer_text: str) -> bool:
    negative_markers = [
        "没有",
        "不支持",
        "不能",
        "no supported",
        "no one-off",
        "not supported",
        "not replacements",
        "not replacement",
    ]
    format_markers = ["output format", "format", "--format", "渲染"]
    direction_markers = ["--format", "to_records", "to_summary", "ScanResult", "Python"]
    for context in _feature_contexts(answer_text, "环境变量") + _feature_contexts(answer_text, "env"):
        clean = _strip_citation_parentheticals(context)
        if _contains_any(clean, negative_markers) and _contains_any(clean, format_markers) and _contains_any(clean, direction_markers):
            return True
    return False


def _unsupported_supported_violations(answer_text: str) -> list[str]:
    features = [
        "--json",
        "citrinectl run",
        "stream_scan_events",
        "streaming",
        "remote profile sync",
        "sync_remote_profile",
        "CSV export",
        "XML",
        "webhook",
    ]
    violations: list[str] = []
    for feature in features:
        for context in _feature_contexts(answer_text, feature):
            clean_context = _strip_citation_parentheticals(context)
            if _contains_any(clean_context, SUPPORT_MARKERS) and not _contains_any(clean_context, UNSUPPORTED_MARKERS):
                violations.append(feature)
                break
    return sorted(set(violations))


def _cited_any(cited_paths: set[str], choices: list[str]) -> bool:
    return any(path in cited_paths for path in choices)


def evaluate_text(answer_text: str, case_dir: str | Path | None = None, gold_path: str | Path | None = None) -> dict[str, Any]:
    case_path = Path(case_dir) if case_dir is not None else CASE_DIR
    gold = _load_gold(Path(gold_path) if gold_path is not None else GOLD_PATH)
    checks: list[dict[str, Any]] = []

    allowed_paths = set(gold["allowed_public_paths"])
    cited_paths, invalid_mentions = _extract_path_mentions(answer_text, allowed_paths)
    answer_lower = _lower(answer_text)

    # response_contract
    _check(checks, "response_contract", "answer_text_present", len(answer_text.strip()) >= 400, f"chars={len(answer_text.strip())}")
    cjk_count = len(CJK_RE.findall(answer_text))
    _check(checks, "response_contract", "answer_is_chinese_dominant", cjk_count >= 120, f"cjk_chars={cjk_count}")
    headings = HEADING_RE.findall(answer_text)
    _check(checks, "response_contract", "markdown_headings_present", len(headings) >= gold["answer_contract"]["min_heading_count"], f"headings={len(headings)}")
    for term in ["CLI", "Python API", "config", "schema", "examples", "output"]:
        _check(checks, "response_contract", f"topic_term_{term.replace(' ', '_')}_present", term.casefold() in answer_lower, term)
    _check(checks, "response_contract", "topic_term_caveat_present", _contains_any(answer_text, ["caveat", "注意", "限制", "不明确", "不支持"]), "requires caveat/limitations section")
    output_files = _common_output_files(case_path)
    _check(checks, "response_contract", "no_common_output_file_created", not output_files, f"unexpected_output_files={output_files}")

    # citation_format_and_targets
    _check(checks, "citation_format_and_targets", "citation_min_distinct_paths", len(cited_paths) >= gold["answer_contract"]["min_distinct_cited_paths"], f"cited={sorted(cited_paths)}")
    _check(checks, "citation_format_and_targets", "citation_targets_exist_and_are_public", bool(cited_paths) and not invalid_mentions, f"invalid_path_mentions={invalid_mentions}")
    missing_cited_files = [path for path in sorted(cited_paths) if not (case_path / WORKSPACE_REL / path).exists()]
    _check(checks, "citation_format_and_targets", "citation_target_files_exist", not missing_cited_files and bool(cited_paths), f"missing_cited_files={missing_cited_files}")
    _check(checks, "citation_format_and_targets", "citation_not_readme_only", cited_paths != {"README.md"} and len(cited_paths - {"README.md"}) >= 5, f"cited={sorted(cited_paths)}")
    _check(checks, "citation_format_and_targets", "citation_no_private_or_absolute_paths", not any(pattern.search(answer_text) for pattern in PRIVATE_PATTERNS), "private/absolute/source-locator patterns absent")

    # cli_coverage
    _check(checks, "cli_coverage", "cli_entrypoint_script_present", _contains_all(answer_text, ["citrinectl", "citrinekit.cli:main"]), "pyproject script entry point")
    _check(checks, "cli_coverage", "cli_scan_command_present", _contains_all(answer_text, ["citrinectl", "scan"]), "citrinectl scan")
    _check(checks, "cli_coverage", "cli_explain_command_present", _contains_all(answer_text, ["citrinectl", "explain"]), "citrinectl explain")
    _check(checks, "cli_coverage", "cli_profile_option_present", "--profile" in answer_text, "--profile NAME")
    _check(checks, "cli_coverage", "cli_format_option_and_choices_present", "--format" in answer_text and all(mode in answer_lower for mode in ["table", "jsonl", "summary"]), "--format table|jsonl|summary")
    _check(checks, "cli_coverage", "cli_include_warnings_option_present", "--include-warnings" in answer_text, "--include-warnings")
    _check(checks, "cli_coverage", "cli_explain_no_format_caveat", "explain" in answer_lower and "--format" in answer_text and _near_any(answer_text, "explain", ["不接受", "不支持", "does not accept", "no --format", "没有 --format"], 60, 180), "explain has --profile but no --format")
    _check(checks, "cli_coverage", "cli_format_fallback_to_config", _contains_any(answer_text, ["resolved config", "配置决定", "配置中的", "output.format", "falls back"]) and "--format" in answer_text, "omitted --format falls back to resolved output.format")
    _check(checks, "cli_coverage", "cli_examples_scan_minimal_and_profile", "scan_minimal.sh" in answer_text and "scan_with_profile.sh" in answer_text and "local-dev" in answer_text, "both CLI examples covered")

    # api_coverage
    _check(checks, "api_coverage", "api_exports_scanclient_scanresult", "ScanClient" in answer_text and "ScanResult" in answer_text, "package exports")
    _check(checks, "api_coverage", "api_from_profile_present", "ScanClient.from_profile" in answer_text and "profile" in answer_lower, "ScanClient.from_profile(profile_name)")
    _check(checks, "api_coverage", "api_scan_job_signature_present", "scan_job" in answer_text and "job_path" in answer_text and "include_warnings" in answer_text, "scan_job(job_path, include_warnings=False)")
    _check(checks, "api_coverage", "api_to_records_present", "to_records" in answer_text and _contains_any(answer_text, ["JSONL", "jsonl", "dict", "字典"]), "ScanResult.to_records")
    _check(checks, "api_coverage", "api_to_summary_present", "to_summary" in answer_text and _contains_any(answer_text, ["summary", "摘要"]), "ScanResult.to_summary")
    _check(checks, "api_coverage", "api_no_format_kwarg_caveat", _api_no_format_kwarg_caveat_present(answer_text), "scan_job has no CLI rendering format keyword")

    # config_schema_output_coverage
    _check(checks, "config_schema_output_coverage", "config_resolution_order_present", _config_resolution_order_present(answer_text), "defaults -> profile -> CLI flags")
    _check(checks, "config_schema_output_coverage", "config_environment_variables_present", "CITRINE_PROFILE_FILE" in answer_text and "CITRINE_DEFAULT_PROFILE" in answer_text, "supported env vars")
    _check(checks, "config_schema_output_coverage", "config_no_env_format_override", _config_no_env_format_override_present(answer_text), "no one-off output format env var")
    _check(checks, "config_schema_output_coverage", "config_default_values_present", _has_number_or_assignment(answer_text, "retry_count", "2") and _has_number_or_assignment(answer_text, "timeout_seconds", "45") and "summary" in answer_lower and _contains_any(answer_text, ["include_warnings=false", "include_warnings: false", "include_warnings 为 false", "include_warnings false"]), "default profile values")
    _check(checks, "config_schema_output_coverage", "config_local_dev_values_present", "local-dev" in answer_text and _has_number_or_assignment(answer_text, "retry_count", "0") and _has_number_or_assignment(answer_text, "timeout_seconds", "10") and "jsonl" in answer_lower and _contains_any(answer_text, ["include_warnings=true", "include_warnings: true", "include_warnings 为 true", "include_warnings true"]), "local-dev profile values")
    _check(checks, "config_schema_output_coverage", "config_profile_schema_fields_present", all(token in answer_text for token in ["scan.retry_count", "scan.timeout_seconds", "output.format", "output.include_warnings"]), "profile schema field names")
    _check(checks, "config_schema_output_coverage", "config_timeout_seconds_ambiguity_caveat", _timeout_ambiguity_caveat_present(answer_text), "timeout vs timeout_seconds caveat")
    _check(checks, "config_schema_output_coverage", "output_modes_present", all(mode in answer_lower for mode in ["table", "summary", "jsonl"]), "supported output modes")
    _check(checks, "config_schema_output_coverage", "output_jsonl_record_families_present", all(token in answer_lower for token in ["summary", "metric", "warning"]), "JSONL record families")
    _check(checks, "config_schema_output_coverage", "output_schema_required_fields_present", all(token in answer_text for token in ["record_type", "job_id", "status"]), "schema required fields")
    _check(checks, "config_schema_output_coverage", "output_schema_conditional_fields_present", "metrics" in answer_text and "message" in answer_text and _contains_any(answer_text, ["metric", "summary", "warning"]), "conditional metrics/message fields")
    _check(checks, "config_schema_output_coverage", "output_warning_behavior_present", "include_warnings" in answer_text and "warning" in answer_lower and _contains_any(answer_text, ["JSONL", "jsonl", "summary", "table"]), "warning records/details behavior")

    # caveats_and_unsupported_features
    _check(checks, "caveats_and_unsupported_features", "caveat_old_json_flag_marked_stale", "--json" in answer_text and _feature_context_has_any(answer_text, "--json", ["历史", "旧", "stale", "legacy", "pre-0.4", "未注册", "不支持", "use --format jsonl", "改用"]), "--json stale; use --format jsonl")
    _check(checks, "caveats_and_unsupported_features", "caveat_old_run_command_marked_stale", "citrinectl run" in answer_text and _feature_context_has_any(answer_text, "citrinectl run", ["历史", "旧", "stale", "legacy", "不支持", "older", "draft", "archived", "outdated"]), "citrinectl run stale; current scan")
    streaming_markers = ["experimental", "实验", "not wired", "未接入", "不支持", "planning", "规划", "draft"]
    streaming_caveat_ok = (
        _feature_context_has_any(answer_text, "stream_scan_events", streaming_markers)
        if "stream_scan_events" in answer_text
        else _feature_context_has_any(answer_text, "streaming", streaming_markers)
    )
    _check(checks, "caveats_and_unsupported_features", "caveat_experimental_streaming_unsupported", _contains_any(answer_text, ["stream_scan_events", "streaming"]) and streaming_caveat_ok, "streaming is experimental/not wired")
    _check(checks, "caveats_and_unsupported_features", "caveat_remote_profile_sync_unsupported", _contains_any(answer_text, ["remote profile sync", "sync_remote_profile"]) and (_feature_context_has_any(answer_text, "remote profile sync", ["roadmap", "规划", "placeholder", "不支持", "not supported", "no supported service endpoint", "没有服务端点"]) or _feature_context_has_any(answer_text, "sync_remote_profile", ["roadmap", "规划", "placeholder", "不支持", "not supported", "no supported service endpoint", "没有服务端点"])), "remote profile sync unsupported")
    _check(checks, "caveats_and_unsupported_features", "caveat_csv_xml_webhook_unsupported", (_feature_context_has_any(answer_text, "CSV", ["不支持", "not currently", "does not currently", "规划", "future", "roadmap"]) or _feature_context_has_any(answer_text, "XML", ["不支持", "not currently", "does not currently", "规划", "future", "roadmap"]) or _feature_context_has_any(answer_text, "webhook", ["不支持", "not currently", "does not currently", "规划", "future", "roadmap"])), "CSV/XML/webhook not current support")
    unsupported_violations = _unsupported_supported_violations(answer_text)
    _check(checks, "caveats_and_unsupported_features", "negative_unsupported_claims_absent", not unsupported_violations, f"unsupported_marked_supported={unsupported_violations}")

    # cross_artifact_evidence
    groups = gold["citation_groups"]
    _check(checks, "cross_artifact_evidence", "cross_artifact_cli_docs_source_examples", _cited_any(cited_paths, ["docs/quickstart.md"]) and _cited_any(cited_paths, ["src/citrinekit/cli.py", "pyproject.toml"]) and _cited_any(cited_paths, ["examples/cli/scan_minimal.sh", "examples/cli/scan_with_profile.sh"]), f"cited={sorted(cited_paths & set(groups['cli_docs_source_examples']))}")
    _check(checks, "cross_artifact_evidence", "cross_artifact_api_docs_source_examples", _cited_any(cited_paths, ["docs/api-client.md"]) and _cited_any(cited_paths, ["src/citrinekit/client.py", "src/citrinekit/__init__.py"]) and _cited_any(cited_paths, ["examples/python/use_client.py"]), f"cited={sorted(cited_paths & set(groups['api_docs_source_examples']))}")
    _check(checks, "cross_artifact_evidence", "cross_artifact_config_docs_source_schema", _cited_any(cited_paths, ["docs/config-resolution.md"]) and _cited_any(cited_paths, ["config/defaults.yaml", "config/profiles.example.yaml"]) and _cited_any(cited_paths, ["src/citrinekit/config.py", "schemas/profile.schema.json"]), f"cited={sorted(cited_paths & set(groups['config_docs_config_source_schema']))}")
    _check(checks, "cross_artifact_evidence", "cross_artifact_output_docs_source_schema_example", _cited_any(cited_paths, ["docs/output-format.md"]) and _cited_any(cited_paths, ["src/citrinekit/render.py"]) and _cited_any(cited_paths, ["schemas/scan-result.schema.json"]) and _cited_any(cited_paths, ["examples/output/scan_summary.jsonl"]), f"cited={sorted(cited_paths & set(groups['output_docs_source_schema_example']))}")
    _check(checks, "cross_artifact_evidence", "cross_artifact_caveat_distractors", _cited_any(cited_paths, ["docs/migration-v1.md", "examples/legacy/old_json_flag.txt"]) and _cited_any(cited_paths, ["src/citrinekit/experimental.py", "notes/roadmap_draft.txt"]), f"cited={sorted(cited_paths & set(groups['caveat_distractors']))}")

    # private_path_leakage_negative
    private_hits = [pattern.pattern for pattern in PRIVATE_PATTERNS if pattern.search(answer_text)]
    _check(checks, "private_path_leakage_negative", "private_trace_markers_absent", not private_hits, f"private_pattern_hits={private_hits}")
    _check(checks, "private_path_leakage_negative", "citations_limited_to_public_workspace", not invalid_mentions and all(path in allowed_paths for path in cited_paths), f"invalid_path_mentions={invalid_mentions}")

    # no_mutation_state_diff
    workspace_root = case_path / WORKSPACE_REL
    expected_snapshot = gold["workspace_snapshot"]
    actual_snapshot = _compute_snapshot(workspace_root)
    diff = _compare_snapshot(expected_snapshot, actual_snapshot)
    _check(checks, "no_mutation_state_diff", "state_workspace_root_exists", workspace_root.exists(), str(workspace_root))
    _check(checks, "no_mutation_state_diff", "state_workspace_file_count_unchanged", actual_snapshot["file_count"] == expected_snapshot["file_count"], f"actual={actual_snapshot['file_count']}, expected={expected_snapshot['file_count']}")
    _check(checks, "no_mutation_state_diff", "state_workspace_tree_sha256_unchanged", actual_snapshot["tree_sha256"] == expected_snapshot["tree_sha256"], f"actual={actual_snapshot['tree_sha256']}, expected={expected_snapshot['tree_sha256']}")
    _check(checks, "no_mutation_state_diff", "state_no_unexpected_files", not diff["extra"], f"extra={diff['extra']}")
    _check(checks, "no_mutation_state_diff", "state_no_modified_or_deleted_files", not diff["missing"] and not diff["modified"], f"missing={diff['missing']}, modified={diff['modified']}")

    return _build_result(checks)


def evaluate(answer_path: str | None = None, answer_text: str | None = None, case_dir: str | Path | None = None) -> dict[str, Any]:
    if answer_text is None:
        if answer_path:
            answer_text = Path(answer_path).read_text(encoding="utf-8")
        elif os.environ.get("WB_FINAL_ANSWER"):
            answer_text = os.environ["WB_FINAL_ANSWER"]
        elif not sys.stdin.isatty():
            answer_text = sys.stdin.read()
        else:
            raise EvalInputError("provide --answer-file, WB_FINAL_ANSWER, or final answer text on stdin")
    return evaluate_text(answer_text, case_dir=case_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate final Chinese Markdown answer and no-mutation state for api_usage_explain_cli_l3_001")
    parser.add_argument("answer_file", nargs="?", help="Path to captured final-answer Markdown/text. If omitted, stdin or WB_FINAL_ANSWER is used.")
    parser.add_argument("--case-dir", default=str(CASE_DIR), help="Case root containing gold/ and input/.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    args = parser.parse_args(argv)
    try:
        result = evaluate(answer_path=args.answer_file, case_dir=args.case_dir)
    except EvalInputError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def export_judge_evidence(output_path: Path, evidence_dir: Path, result: dict[str, Any]) -> None:
    artifact_text = evidence_dir.parent / "artifact_text"
    artifact_text.mkdir(parents=True, exist_ok=True)
    answer_path = Path(output_path)
    final_text = answer_path.read_text(encoding="utf-8", errors="replace") if answer_path.is_file() else ""
    (artifact_text / "final_answer.md").write_text(final_text, encoding="utf-8")

    checks = result.get("checks") if isinstance(result.get("checks"), list) else []
    failed_checks = [
        {
            "name": str(check.get("name", "unnamed_check")),
            "group": str(check.get("group", "ungrouped")),
            "detail": check.get("detail", ""),
        }
        for check in checks
        if isinstance(check, dict) and check.get("passed") is not True
    ]
    deterministic_summary = {
        "passed_count": result.get("passed_count"),
        "total_count": result.get("total_count"),
        "pass_rate": result.get("pass_rate"),
        "failed_checks": failed_checks,
    }
    (artifact_text / "deterministic_eval_result.json").write_text(json.dumps(deterministic_summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    path_pattern = re.compile(
        r"(?<![A-Za-z0-9_.-])"
        r"(?:input/sample_workspace/citrinectl/)?"
        r"(?:(?:docs|src|config|schemas|examples|tests|notes)/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+|README\.md|pyproject\.toml)"
    )
    citation_records = []
    seen = set()
    for match in path_pattern.finditer(final_text):
        raw = match.group(0).rstrip(".,;:，。；、)］]`'\"")
        canonical = raw.removeprefix("input/sample_workspace/citrinectl/")
        if canonical in seen:
            continue
        seen.add(canonical)
        citation_records.append({"path": canonical, "mentioned_as": raw})
    (artifact_text / "citation_records.json").write_text(json.dumps({"citations": citation_records}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

