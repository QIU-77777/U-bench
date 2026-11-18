#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

FORBIDDEN_PATTERNS = [
    ("private_path", re.compile(r"/(?:data/private|mnt/private|var/secrets|tmp/private|Users)/[^\s\"'`]+", re.I)),
    ("credential", re.compile(r"(?:api[_-]?key|secret|token|credential|password)\s*[:=]", re.I)),
]
TEXT_LIKE = {"md", "txt", "text", "json", "jsonl", "csv", "yaml", "yml", "toml", "log"}


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "artifact"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _judge_refs(judge_yaml: Path) -> tuple[dict[str, dict[str, Any]], set[str]]:
    data = yaml.safe_load(judge_yaml.read_text(encoding="utf-8")) or {}
    artifacts = {str(item["id"]): item for item in data.get("artifacts", []) or [] if isinstance(item, dict) and item.get("id") is not None}
    refs: set[str] = set()
    for rubric in (data.get("llm_judge") or {}).get("rubrics") or []:
        refs.update(str(ref) for ref in rubric.get("artifact_refs") or [])
    return artifacts, refs


def _existing_manifest_records(logs: Path) -> dict[str, dict[str, Any]]:
    data = _load_json(logs / "artifact_manifest.json")
    records = data.get("artifacts") if isinstance(data.get("artifacts"), list) else []
    return {str(record.get("id")): record for record in records if isinstance(record, dict) and record.get("id")}


def _text_hits(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    return [label for label, pattern in FORBIDDEN_PATTERNS if pattern.search(text)]


def _record_from_logs(artifact_id: str, artifact: dict[str, Any], logs: Path) -> dict[str, Any] | None:
    rel = str(artifact.get("path") or "")
    evidence_path = logs / rel
    producer = "case_local_evidence_builder"
    source_path = rel
    if not evidence_path.is_file() or evidence_path.stat().st_size == 0:
        tests_root = Path(os.environ.get("WB_BENCH_TESTS_ROOT", "/tests"))
        verifier_public = tests_root / "grading" / "judge" / f"{artifact_id}.md"
        if not verifier_public.is_file() or verifier_public.stat().st_size == 0:
            return None
        rel = f"judge_evidence/{artifact_id}.md"
        evidence_path = logs / rel
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(verifier_public, evidence_path)
        producer = "verifier_public_evidence"
        source_path = str(verifier_public)
    hits = _text_hits(evidence_path)
    return {
        "id": artifact_id,
        "source_path": source_path,
        "text_path": rel,
        "type": str(artifact.get("type") or "md"),
        "required": bool(artifact.get("required", True)),
        "extract_status": "ok" if not hits else "error",
        "sha256": _sha256(evidence_path),
        "producer": producer,
        **({"error": "unsafe_curated_evidence", "sanitization_findings": hits} if hits else {}),
    }


def _record_from_workspace(artifact_id: str, artifact: dict[str, Any], workspace: Path, logs: Path) -> dict[str, Any] | None:
    rel = str(artifact.get("path") or "")
    source = (workspace / rel).resolve()
    try:
        source.relative_to(workspace.resolve())
    except Exception:
        return None
    if not source.is_file() or source.stat().st_size == 0:
        return None
    artifact_type = str(artifact.get("type") or source.suffix.lstrip(".") or "txt").lower()
    suffix = source.suffix or ".txt"
    raw_rel = f"raw_artifacts/{_safe_name(artifact_id)}{suffix if not _safe_name(artifact_id).endswith(suffix) else ''}"
    text_rel = f"artifact_text/{_safe_name(artifact_id)}.md"
    raw_path = logs / raw_rel
    text_path = logs / text_rel
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, raw_path)
    if artifact_type in TEXT_LIKE or source.suffix.lower().lstrip(".") in TEXT_LIKE:
        content = source.read_text(encoding="utf-8", errors="replace")
    else:
        content = f"Binary artifact copied to {raw_rel}; no text conversion available in verifier-local minimal extractor."
    text_path.write_text(content, encoding="utf-8")
    hits = _text_hits(text_path)
    return {
        "id": artifact_id,
        "source_path": rel,
        "verifier_raw_path": raw_rel,
        "text_path": text_rel,
        "type": str(artifact.get("type") or source.suffix.lstrip(".") or "txt"),
        "required": bool(artifact.get("required", True)),
        "extract_status": "ok" if not hits else "error",
        "sha256": _sha256(source),
        "producer": "declared_workspace_artifact_minimal_extractor",
        **({"error": "unsafe_workspace_evidence", "sanitization_findings": hits} if hits else {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--judge-yaml", default="/tests/judge.yaml")
    parser.add_argument("--logs", default="/logs/verifier")
    parser.add_argument("--workspace", default="/workspace")
    args = parser.parse_args()
    logs = Path(args.logs)
    workspace = Path(args.workspace)
    logs.mkdir(parents=True, exist_ok=True)
    artifacts, refs = _judge_refs(Path(args.judge_yaml))
    existing = _existing_manifest_records(logs)
    records = []
    findings = []
    for artifact_id in sorted(refs):
        artifact = artifacts.get(artifact_id)
        if not artifact:
            records.append({"id": artifact_id, "extract_status": "error", "error": "artifact_ref_not_declared"})
            continue
        existing_record = existing.get(artifact_id)
        if existing_record and existing_record.get("extract_status") == "ok" and existing_record.get("text_path") and (logs / str(existing_record["text_path"])).is_file():
            records.append(existing_record)
            continue
        record = _record_from_logs(artifact_id, artifact, logs) or _record_from_workspace(artifact_id, artifact, workspace, logs)
        if record is None:
            record = {"id": artifact_id, "source_path": str(artifact.get("path") or ""), "type": str(artifact.get("type") or "md"), "required": bool(artifact.get("required", True)), "extract_status": "error", "error": "missing_declared_artifact_evidence"}
        if record.get("extract_status") != "ok":
            findings.append({"id": artifact_id, "path": record.get("source_path"), "error": record.get("error")})
        records.append(record)
    status = "pass" if records and all(record.get("extract_status") == "ok" for record in records) else "needs_review"
    artifact_manifest = {"artifacts": records, "extract_status": "ok" if status == "pass" else "error", "extract_source": "case_local_curated_or_declared_workspace_evidence", "curated_evidence_only": all(str(record.get("producer")) == "case_local_evidence_builder" for record in records)}
    evaluator_manifest = {"schema_version": "wb_judge_evidence_manifest_v1", "status": status, "artifact_manifest_present": True, "raw_artifacts_dir_present": (logs / "raw_artifacts").exists(), "artifact_text_dir_present": (logs / "artifact_text").exists(), "findings": findings}
    (logs / "artifact_manifest.json").write_text(json.dumps(artifact_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (logs / "evaluator_artifact_manifest.json").write_text(json.dumps(evaluator_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    score_path = logs / "score.json"
    score = _load_json(score_path)
    if score:
        score["judge_evidence_ready"] = status == "pass"
        score["judge_evidence_manifest"] = "artifact_manifest.json"
        score["judge_evidence_status"] = status
        score["judge_evidence_source"] = artifact_manifest["extract_source"]
        score["judge_extraction_required"] = False
        score_path.write_text(json.dumps(score, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evaluator_manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
