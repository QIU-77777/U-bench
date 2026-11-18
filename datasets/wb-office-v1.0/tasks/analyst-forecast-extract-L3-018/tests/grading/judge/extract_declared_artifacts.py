#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

TEXT_LIKE_TYPES = {
    "txt",
    "text",
    "md",
    "markdown",
    "csv",
    "json",
    "yaml",
    "yml",
    "html",
    "htm",
    "xml",
    "py",
    "js",
    "ts",
    "tsx",
    "jsx",
    "java",
    "go",
    "rs",
    "cpp",
    "c",
    "h",
    "hpp",
    "css",
    "scss",
    "sql",
    "toml",
    "ini",
    "log",
    "source",
}

FORBIDDEN_PATTERNS = [
    ("private_path", re.compile(r"/(?:data/private|mnt/private|var/secrets|tmp/private|Users)/[^\s\"'`]+", re.IGNORECASE)),
    ("credential", re.compile(r"(?:api[_-]?key|secret|token|credential|password)\s*[:=]", re.IGNORECASE)),
]


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_workspace_path(workspace: Path, relative_path: str) -> Path:
    candidate = (workspace / relative_path).resolve()
    root = workspace.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"artifact path escapes workspace: {relative_path}") from exc
    return candidate


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "artifact"


def _artifact_output_name(artifact_id: str, source_rel: str) -> str:
    suffix = Path(source_rel).suffix
    safe_id = _safe_name(artifact_id)
    return f"{safe_id}{suffix}" if suffix and not safe_id.endswith(suffix) else safe_id


def _format_cell_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("\n", "\\n")


def _extract_xlsx(source_path: Path, text_path: Path) -> None:
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("openpyxl is required to extract xlsx artifacts") from exc

    workbook_values = openpyxl.load_workbook(source_path, data_only=False, read_only=False)
    workbook_cached = openpyxl.load_workbook(source_path, data_only=True, read_only=True)
    lines: list[str] = [f"# Workbook: {source_path.name}"]

    for sheet_index, sheet in enumerate(workbook_values.worksheets, start=1):
        cached_sheet = workbook_cached[sheet.title]
        lines.append("")
        lines.append(f"## Sheet {sheet_index}: {sheet.title}")
        merged_ranges = [str(item) for item in sheet.merged_cells.ranges]
        if merged_ranges:
            lines.append("Merged cells: " + ", ".join(merged_ranges))

        max_row = sheet.max_row or 0
        max_column = sheet.max_column or 0
        lines.append(f"Dimensions: {max_row} rows x {max_column} columns")
        for row in range(1, max_row + 1):
            values: list[str] = []
            row_has_value = False
            for column in range(1, max_column + 1):
                cell = sheet.cell(row=row, column=column)
                cached_cell = cached_sheet.cell(row=row, column=column)
                value = _format_cell_value(cell.value)
                if value:
                    row_has_value = True
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    cached = _format_cell_value(cached_cell.value)
                    value = f"formula:{cell.value}"
                    if cached:
                        value = f"{value} cached:{cached}"
                values.append(value)
            if row_has_value or any(values):
                lines.append(f"R{row}: " + " | ".join(values))

    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _extract_text_file(source_path: Path, text_path: Path) -> None:
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(source_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")


def _extract_by_type(source_path: Path, text_path: Path, artifact_type: str) -> None:
    normalized_type = artifact_type.lower().lstrip(".")
    if normalized_type in TEXT_LIKE_TYPES:
        _extract_text_file(source_path, text_path)
        return
    if normalized_type == "xlsx":
        _extract_xlsx(source_path, text_path)
        return
    raise RuntimeError(f"unsupported artifact type for task-local extractor: {artifact_type}")


def _text_hits(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    return [label for label, pattern in FORBIDDEN_PATTERNS if pattern.search(text)]


def _rubric_consumed_artifacts(judge_yaml: Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(judge_yaml.read_text(encoding="utf-8")) or {}
    artifacts = {str(item["id"]): item for item in data.get("artifacts", []) if isinstance(item, dict) and item.get("id") is not None}
    refs: set[str] = set()
    for rubric in (data.get("llm_judge") or {}).get("rubrics") or []:
        refs.update(str(ref) for ref in rubric.get("artifact_refs") or [])
    selected: list[dict[str, Any]] = []
    for artifact_id in sorted(refs):
        artifact = artifacts.get(artifact_id)
        if artifact is None:
            selected.append({"id": artifact_id, "path": "", "type": "", "required": True, "_missing_declaration": True})
            continue
        selected.append({**artifact, "id": artifact_id, "required": bool(artifact.get("required", True))})
    return selected


def _extract_artifact(artifact: dict[str, Any], *, workspace: Path, logs: Path) -> dict[str, Any]:
    artifact_id = str(artifact["id"])
    source_rel = str(artifact.get("path") or "")
    artifact_type = str(artifact.get("type") or Path(source_rel).suffix.lstrip(".") or "text").lower().lstrip(".")
    raw_name = _artifact_output_name(artifact_id, source_rel)
    raw_path = logs / "raw_artifacts" / raw_name
    text_path = logs / "artifact_text" / f"{raw_name}.md"
    record: dict[str, Any] = {
        "id": artifact_id,
        "source_path": source_rel,
        "verifier_raw_path": raw_path.relative_to(logs).as_posix(),
        "text_path": text_path.relative_to(logs).as_posix(),
        "type": artifact_type,
        "required": bool(artifact.get("required", True)),
        "extract_status": "ok",
        "producer": "task_local_declared_artifact_extractor",
    }

    try:
        if artifact.get("_missing_declaration"):
            raise RuntimeError("artifact_ref_not_declared")
        source_path = _safe_workspace_path(workspace, source_rel)
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(f"artifact not found: {source_rel}")
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, raw_path)
        record["sha256"] = _sha256(raw_path)
        _extract_by_type(raw_path, text_path, artifact_type)
        hits = _text_hits(text_path)
        if hits:
            raise RuntimeError("unsafe_extracted_evidence: " + ",".join(hits))
    except Exception as exc:
        record["extract_status"] = "error"
        record["error"] = str(exc)
        record.pop("sha256", None)
    return record


def build_manifests(judge_yaml: Path, workspace: Path, logs: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    logs.mkdir(parents=True, exist_ok=True)
    records = [_extract_artifact(artifact, workspace=workspace, logs=logs) for artifact in _rubric_consumed_artifacts(judge_yaml)]
    findings = [
        {"id": record.get("id"), "path": record.get("source_path"), "error": record.get("error")}
        for record in records
        if record.get("extract_status") != "ok"
    ]
    status = "pass" if records and not findings else "needs_review"
    artifact_manifest = {
        "artifacts": records,
        "extract_status": "ok" if status == "pass" else "error",
        "extract_source": "task_local_declared_artifact_extractor",
        "curated_evidence_only": False,
    }
    evaluator_manifest = {
        "schema_version": "wb_judge_evidence_manifest_v1",
        "status": status,
        "artifact_manifest_present": True,
        "raw_artifacts_dir_present": (logs / "raw_artifacts").exists(),
        "artifact_text_dir_present": (logs / "artifact_text").exists(),
        "findings": findings,
        "supported_input_types": sorted(TEXT_LIKE_TYPES | {"xlsx"}),
        "notes": [
            "Task-local extractor handles rubric-consumed declared workspace artifacts only.",
            "It does not import workbuddy_bench, read hidden gold, or perform semantic scoring.",
        ],
    }
    return artifact_manifest, evaluator_manifest


def update_score(logs: Path, evaluator_manifest: dict[str, Any]) -> None:
    score_path = logs / "score.json"
    score = _load_json(score_path)
    if not score:
        return
    status = evaluator_manifest.get("status")
    score["judge_evidence_ready"] = status == "pass"
    score["judge_evidence_manifest"] = "artifact_manifest.json"
    score["judge_evidence_status"] = status
    score["judge_evidence_source"] = "task_local_declared_artifact_extractor"
    score["judge_extraction_required"] = True
    if evaluator_manifest.get("findings"):
        notes = score.setdefault("validity_notes", [])
        if isinstance(notes, list):
            notes.append("judge_evidence_extraction_findings_need_review")
    score_path.write_text(json.dumps(score, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--judge-yaml", default="/tests/judge.yaml")
    parser.add_argument("--workspace", default="/workspace")
    parser.add_argument("--logs", default="/logs/verifier")
    args = parser.parse_args()

    logs = Path(args.logs)
    artifact_manifest, evaluator_manifest = build_manifests(Path(args.judge_yaml), Path(args.workspace), logs)
    (logs / "artifact_manifest.json").write_text(json.dumps(artifact_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (logs / "evaluator_artifact_manifest.json").write_text(json.dumps(evaluator_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    update_score(logs, evaluator_manifest)
    print(json.dumps(evaluator_manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evaluator_manifest.get("status") == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
