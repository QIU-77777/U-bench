#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

try:
    from openpyxl import load_workbook
except ImportError:  # pragma: no cover - exercised only in missing dependency environments
    load_workbook = None  # type: ignore[assignment]


CASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DECK_REL = Path("input/quarterly_governance_board_deck.pptx")
INPUT_WORKBOOK_REL = Path("input/program_milestone_update_register.xlsx")
ENV_NOTE_REL = Path("environment/local_fixture_notes.txt")
EXPECTED_OUTPUT_REL = Path("output/quarterly_governance_board_deck_revised.pptx")

JUDGE_EVIDENCE_FILES = {
    "judge_scope_and_gate_status": Path("judge_evidence/judge_scope_and_gate_status.md"),
    "submitted_deck_slide_text": Path("judge_evidence/submitted_deck_slide_text.md"),
    "base_vs_submitted_slide_delta": Path("judge_evidence/base_vs_submitted_slide_delta.md"),
    "public_workbook_update_summary": Path("judge_evidence/public_workbook_update_summary.md"),
    "public_base_deck_role_summary": Path("judge_evidence/public_base_deck_role_summary.md"),
}
JUDGE_EVIDENCE_LIMITS = {
    "judge_scope_and_gate_status": 5000,
    "submitted_deck_slide_text": 30000,
    "base_vs_submitted_slide_delta": 18000,
    "public_workbook_update_summary": 18000,
    "public_base_deck_role_summary": 12000,
}

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
NS = {"p": P_NS, "a": A_NS, "r": R_NS, "rel": PKG_REL_NS, "ct": CT_NS}

FORBIDDEN_OUTPUT_SUFFIXES = {".pdf", ".md", ".markdown", ".docx", ".xlsx", ".html", ".htm", ".png", ".jpg", ".jpeg"}
OUTPUT_GATE_CHECKS = [
    "output_pptx_discovered",
    "output_single_pptx_unambiguous",
    "output_extension_pptx",
    "output_zip_openable",
]
STATIC_EXPECTED_CHECKS: list[tuple[str, str]] = [
    ("verifier_isolation", "input_base_deck_sha256_unchanged"),
    ("verifier_isolation", "input_workbook_sha256_unchanged"),
    ("verifier_isolation", "input_environment_sha256_unchanged"),
    ("workbook_to_slide_mapping", "source_workbook_openable"),
    ("workbook_to_slide_mapping", "workbook_material_date_matches_gold"),
    ("workbook_to_slide_mapping", "workbook_current_records_match_gold"),
    ("workbook_to_slide_mapping", "workbook_excluded_records_match_gold"),
    ("workbook_to_slide_mapping", "workbook_version_normalization_rows_match_gold"),
    ("output_contract", "output_pptx_discovered"),
    ("output_contract", "output_single_pptx_unambiguous"),
    ("output_contract", "output_extension_pptx"),
    ("output_contract", "output_file_nonempty"),
    ("output_contract", "output_not_public_input_file"),
    ("output_contract", "output_not_base_deck_clone"),
    ("output_contract", "no_forbidden_extra_delivery_artifacts"),
    ("file_integrity", "output_zip_openable"),
    ("file_integrity", "output_required_ooxml_parts_present"),
    ("file_integrity", "output_content_types_include_presentation"),
    ("file_integrity", "output_presentation_xml_parseable"),
    ("file_integrity", "output_presentation_relationships_parseable"),
    ("file_integrity", "output_slides_xml_parseable"),
    ("template_preservation", "output_slide_count_11"),
    ("template_preservation", "slide_order_matches_base"),
    ("template_preservation", "slide_titles_sections_preserved"),
    ("template_preservation", "shape_object_names_preserved"),
    ("template_preservation", "table_structure_all_expected"),
    ("template_preservation", "timeline_object_order_preserved"),
    ("timeline_version_consistency", "footer_all_slides_v1_8_current"),
    ("timeline_version_consistency", "footer_all_slides_material_date_2026_07_01"),
    ("timeline_version_consistency", "old_footer_version_absent"),
    ("timeline_version_consistency", "old_material_date_absent"),
    ("timeline_version_consistency", "version_aliases_normalized_current"),
    ("timeline_version_consistency", "slide_03_current_overview_mapping"),
    ("timeline_version_consistency", "slide_04_date_normalization"),
    ("timeline_version_consistency", "slide_07_decision_deadline_and_risk_window"),
    ("distractor_non_updates", "distractor_history_slide_preserved"),
    ("distractor_non_updates", "distractor_template_slide_preserved"),
    ("distractor_non_updates", "distractor_future_draft_not_promoted"),
    ("distractor_non_updates", "distractor_monitoring_not_promoted"),
    ("distractor_non_updates", "distractor_archive_alias_not_rewritten_to_current"),
    ("distractor_non_updates", "workbook_raw_sheet_headers_not_dumped"),
    ("file_integrity", "chinese_text_dominant"),
    ("file_integrity", "no_external_relationships"),
    ("file_integrity", "no_external_url_or_file_uri"),
    ("file_integrity", "no_private_paths_or_source_locators"),
    ("file_integrity", "no_secret_like_strings"),
    ("file_integrity", "no_forbidden_dependency_claims"),
]

SECTION_TOKENS = {
    1: ["春晖公益协同计划", "季度治理会材料"],
    2: ["会议材料目录"],
    3: ["总览", "治理包"],
    4: ["实施时间线", "关键节点"],
    5: ["工作流 A", "社区站点", "志愿者"],
    6: ["工作流 B", "数据回收", "服务包"],
    7: ["治理会决策", "风险"],
    8: ["资源", "沟通节奏"],
    9: ["附录", "字段口径", "页脚"],
    10: ["历史归档", "保留"],
    11: ["模板页", "样例", "不作为正文"],
}

PRIVATE_PATTERN_SPECS = [
    ("private_posix_path", re.compile(r"(?<![A-Za-z0-9_.-])/(?:data/private|home|Users|var/secrets|mnt/private|tmp/private|private)[^\s<>\]})]+", re.IGNORECASE)),
    ("windows_path", re.compile(r"(?<![A-Za-z0-9_.-])[A-Za-z]:[\\/][^\s<>\]})]+")),
    ("source_locator", re.compile(r"\b(?:source_locator|private_source_access|conversation_id|request_id|row_group|row_in_group|wbi-opus461m|parquet)\b(?:\s*[:=]\s*[^\s<>\]})]+)?", re.IGNORECASE)),
    ("email_address", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("account_identifier", re.compile(r"\b(?:account[_-]?id|tenant[_-]?id|customer[_-]?id|user[_-]?id)\s*[:=]\s*[A-Za-z0-9_.:-]{4,}\b", re.IGNORECASE)),
]
SECRET_PATTERN_SPECS = [
    ("credential_assignment", re.compile(r"\b(?:password|passwd|secret|token|api[_-]?key|credential|access[_-]?key)\s*[:=]\s*[^\s<>\]})]+", re.IGNORECASE)),
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
]
PRIVATE_PATTERNS = [pattern for _, pattern in PRIVATE_PATTERN_SPECS]
SECRET_PATTERNS = [pattern for _, pattern in SECRET_PATTERN_SPECS]
EXTERNAL_URL_RE = re.compile(r"(?:https?://|file://|ftp://|s3://|gs://)[^\"'< >\s]*", re.IGNORECASE)
STANDARD_XML_URI_PREFIXES = tuple(
    prefix.casefold()
    for prefix in [
        "http://schemas.openxmlformats.org/",
        "http://schemas.microsoft.com/office/",
        "http://schemas.microsoft.com/Office/",
        "http://purl.org/",
        "http://www.w3.org/",
        "http://ns.adobe.com/",
        "http://www.ecma-international.org/",
    ]
)


class PptxParseError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_gold(case_dir: Path) -> dict[str, Any]:
    gold_path = Path(os.environ.get("WB_BENCH_GOLD_PATH", "/tests/gold/gold_answer.json"))
    with gold_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _compact(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.casefold().replace("（", "(").replace("）", ")")
    return re.sub(r"[\s`*_·•:：/\\|\-—–,，。；;、()（）\[\]【】<>《》\n\r\t]+", "", text)


def _contains(text: str, term: str) -> bool:
    return _compact(term) in _compact(text)


def _contains_all(text: str, terms: list[str]) -> bool:
    return all(_contains(text, term) for term in terms)


def _contains_none(text: str, terms: list[str]) -> bool:
    return all(not _contains(text, term) for term in terms)


def _redact_sensitive_text(text: str) -> str:
    def replace_external_url(match: re.Match[str]) -> str:
        url = match.group(0)
        return url if url.casefold().startswith(STANDARD_XML_URI_PREFIXES) else "<redacted-external-url>"

    redacted = EXTERNAL_URL_RE.sub(replace_external_url, text)
    for category, pattern in PRIVATE_PATTERN_SPECS:
        redacted = pattern.sub(f"<redacted-{category}>", redacted)
    for category, pattern in SECRET_PATTERN_SPECS:
        redacted = pattern.sub(f"<redacted-{category}>", redacted)
    return redacted


def _redact_sensitive_detail(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_sensitive_text(value)
    if isinstance(value, list):
        return [_redact_sensitive_detail(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_sensitive_detail(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _redact_sensitive_detail(item) for key, item in value.items()}
    return value


def _check(checks: list[dict[str, Any]], group: str, name: str, passed: bool, detail: Any = "") -> None:
    checks.append({"name": name, "group": group, "passed": bool(passed), "detail": _redact_sensitive_detail(detail)})


def _external_target_category(target: str) -> str:
    lowered = target.casefold()
    if lowered.startswith("file://"):
        return "file_uri"
    if lowered.startswith("s3://"):
        return "s3_uri"
    if lowered.startswith("gs://"):
        return "gs_uri"
    if lowered.startswith("ftp://"):
        return "ftp_url"
    if lowered.startswith("https://"):
        return "https_url"
    if lowered.startswith("http://"):
        return "http_url"
    return "external_relationship"


def _summarize_redacted_findings(findings: list[dict[str, str]], *, placeholder: str) -> dict[str, Any]:
    parts = sorted({item.get("part", "<unknown-part>") for item in findings})
    categories = sorted({item.get("category", "unknown") for item in findings})
    return {"count": len(findings), "categories": categories, "parts": parts, "placeholder": placeholder}


def _redacted_pattern_summary(text_by_part: dict[str, str], specs: list[tuple[str, re.Pattern[str]]], *, placeholder: str) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    for part, text in text_by_part.items():
        for category, pattern in specs:
            for _ in pattern.finditer(text):
                findings.append({"part": part, "category": category})
    return _summarize_redacted_findings(findings, placeholder=placeholder)


def _forbidden_claim_summary(text: str, forbidden_claims: list[str]) -> dict[str, Any]:
    matched_count = sum(1 for claim in forbidden_claims if _contains(text, claim))
    return {
        "count": matched_count,
        "categories": ["forbidden_dependency_claim"] if matched_count else [],
        "parts": ["ppt/slides/*.xml"] if matched_count else [],
        "placeholder": "<redacted-forbidden-dependency-claim>",
    }


def _expected_checks(gold: dict[str, Any]) -> list[tuple[str, str]]:
    expected: list[tuple[str, str]] = list(STATIC_EXPECTED_CHECKS)
    for slide in gold["deck_structure"]["slides"]:
        num = int(slide["slide_number"])
        expected.extend(
            [
                ("template_preservation", f"slide_{num:02d}_object_count_preserved"),
                ("template_preservation", f"slide_{num:02d}_shape_count_preserved"),
                ("template_preservation", f"slide_{num:02d}_graphic_frame_count_preserved"),
                ("template_preservation", f"slide_{num:02d}_section_title_present"),
                ("timeline_version_consistency", f"slide_{num:02d}_footer_object_present"),
                ("timeline_version_consistency", f"slide_{num:02d}_footer_version_date"),
            ]
        )
        for idx, _ in enumerate(slide.get("object_names", [])):
            expected.append(("template_preservation", f"slide_{num:02d}_object_{idx:02d}_present"))
        for idx, _ in enumerate(slide.get("table_shapes", [])):
            expected.append(("template_preservation", f"slide_{num:02d}_table_{idx:02d}_structure"))
    for slide_key, spec in gold.get("required_slide_expectations", {}).items():
        num = int(slide_key)
        for idx, _ in enumerate(spec.get("all", [])):
            expected.append(("workbook_to_slide_mapping", f"slide_{num:02d}_required_text_{idx:02d}"))
        for idx, _ in enumerate(spec.get("none", [])):
            expected.append(("distractor_non_updates", f"slide_{num:02d}_forbidden_text_{idx:02d}_absent"))
    for item in gold.get("one_to_many_sync", []):
        safe_item = re.sub(r"[^A-Za-z0-9]+", "_", str(item["item_id"])).strip("_")
        for slide_num in item.get("slides", []):
            expected.append(("workbook_to_slide_mapping", f"sync_{safe_item}_slide_{int(slide_num):02d}"))
    for item in gold.get("co_location_expectations", []):
        expected.append((str(item.get("group", "workbook_to_slide_mapping")), f"co_location_{item['id']}"))
    return expected


def _build_result(checks: list[dict[str, Any]], gold: dict[str, Any]) -> dict[str, Any]:
    expected = _expected_checks(gold)
    expected_names = [name for _, name in expected]
    raw_by_name: dict[str, dict[str, Any]] = {}
    duplicate_raw = []
    for check in checks:
        if check["name"] in raw_by_name:
            duplicate_raw.append(check["name"])
        raw_by_name[check["name"]] = check
    duplicate_expected = sorted({name for name in expected_names if expected_names.count(name) > 1})
    missing_expected = [name for name in expected_names if name not in raw_by_name]
    output_gate_failures = [name for name in OUTPUT_GATE_CHECKS if not raw_by_name.get(name, {}).get("passed", False)]

    model_checks: list[dict[str, Any]] = []
    for group, name in expected:
        raw = raw_by_name.get(name)
        if output_gate_failures:
            model_checks.append(
                {
                    "name": name,
                    "group": group,
                    "passed": False,
                    "detail": {
                        "gated_by_output_contract": output_gate_failures,
                        "raw_emitted": raw is not None,
                        "raw_passed": raw.get("passed") if raw else None,
                        "raw_detail": raw.get("detail") if raw else "not evaluated because required PPTX output gate failed",
                    },
                }
            )
        elif raw is None:
            model_checks.append({"name": name, "group": group, "passed": False, "detail": "expected check was not emitted"})
        else:
            model_checks.append(raw)

    contract_complete = not missing_expected and not duplicate_expected and not duplicate_raw
    if output_gate_failures or not contract_complete:
        model_score = 0
    else:
        model_score = sum(1 for check in model_checks if check.get("passed"))
    model_total = len(expected)
    model_pass_rate = round(model_score / model_total, 4) if model_total else 0.0
    raw_passed = sum(1 for check in checks if check.get("passed"))
    raw_total = len(checks)
    return {
        "passed_count": model_score,
        "total_count": model_total,
        "pass_rate": model_pass_rate,
        "score_denominator_mode": f"full_contract_{model_total}_output_gated",
        "model_score": model_score,
        "model_total": model_total,
        "model_pass_rate": model_pass_rate,
        "gated_pass": bool(contract_complete and not output_gate_failures and model_score == model_total),
        "scoring": {
            "output_gate_checks": OUTPUT_GATE_CHECKS,
            "output_gate_failures": output_gate_failures,
            "contract_complete": contract_complete,
            "missing_expected_checks": missing_expected,
            "duplicate_expected_checks": duplicate_expected,
            "duplicate_raw_checks": sorted(set(duplicate_raw)),
            "raw_emitted_passed_count": raw_passed,
            "raw_emitted_total_count": raw_total,
            "raw_emitted_pass_rate": round(raw_passed / raw_total, 4) if raw_total else 0.0,
            "interpretation": "passed_count/total_count is the deterministic verifier score. Required PPTX output gate failures set the comparable model score to 0 while diagnostic raw checks remain visible.",
        },
        "checks": model_checks,
        "diagnostic_checks": checks,
    }


def _discover_output(target: Path | None, case_dir: Path) -> dict[str, Any]:
    search_dir = case_dir / "output"
    context_files: list[Path] = []
    if target is None:
        expected = case_dir / EXPECTED_OUTPUT_REL
        if search_dir.exists():
            context_files = [path for path in search_dir.rglob("*") if path.is_file()]
        candidate = expected if expected.exists() else None
        pptx_files = [path for path in context_files if path.suffix.lower() == ".pptx"]
        if candidate is None and len(pptx_files) == 1:
            candidate = pptx_files[0]
        return {"candidate": candidate, "pptx_files": pptx_files, "context_files": context_files, "mode": "default_output_dir"}
    if target.is_dir():
        context_files = [path for path in target.rglob("*") if path.is_file()]
        pptx_files = [path for path in context_files if path.suffix.lower() == ".pptx"]
        candidate = pptx_files[0] if len(pptx_files) == 1 else None
        return {"candidate": candidate, "pptx_files": pptx_files, "context_files": context_files, "mode": "explicit_dir"}
    return {"candidate": target, "pptx_files": [target] if target.suffix.lower() == ".pptx" else [], "context_files": [target], "mode": "explicit_file"}


def _parse_xml(data: bytes, label: str) -> ET.Element:
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise PptxParseError(f"XML parse failed for {label}: {exc}") from exc


def _read_zip_text(zf: zipfile.ZipFile, name: str) -> str:
    return zf.read(name).decode("utf-8", errors="replace")


def _slide_paths_in_order(zf: zipfile.ZipFile) -> list[str]:
    rel_root = _parse_xml(zf.read("ppt/_rels/presentation.xml.rels"), "ppt/_rels/presentation.xml.rels")
    rels: dict[str, str] = {}
    for rel in rel_root.findall("rel:Relationship", NS):
        rid = rel.attrib.get("Id")
        target = rel.attrib.get("Target", "")
        if rid and target:
            rels[rid] = "ppt/" + target.lstrip("/") if not target.startswith("ppt/") else target
    pres_root = _parse_xml(zf.read("ppt/presentation.xml"), "ppt/presentation.xml")
    paths: list[str] = []
    for sld_id in pres_root.findall(".//p:sldId", NS):
        rid = sld_id.attrib.get(f"{{{R_NS}}}id")
        if rid in rels:
            paths.append(rels[rid])
    return paths


def _shape_name(elem: ET.Element) -> str:
    c_nv = elem.find(".//p:cNvPr", NS)
    return c_nv.attrib.get("name", "") if c_nv is not None else ""


def _extract_texts(elem: ET.Element) -> list[str]:
    return [node.text for node in elem.iter() if node.tag == f"{{{A_NS}}}t" and node.text]


def _extract_x(elem: ET.Element) -> int:
    xfrm = elem.find(".//a:xfrm", NS)
    if xfrm is None:
        xfrm = elem.find(".//p:xfrm", NS)
    off = xfrm.find("a:off", NS) if xfrm is not None else None
    if off is None:
        return 0
    try:
        return int(off.attrib.get("x", 0))
    except ValueError:
        return 0


def _table_dimensions(elem: ET.Element) -> tuple[int, int]:
    rows = elem.findall(".//a:tbl/a:tr", NS)
    col_count = 0
    if rows:
        col_count = max(len(row.findall("a:tc", NS)) for row in rows)
    return len(rows), col_count


def _slide_record(xml_bytes: bytes) -> dict[str, Any]:
    root = _parse_xml(xml_bytes, "slide")
    sp_tree = root.find(".//p:spTree", NS)
    objects: list[dict[str, Any]] = []
    if sp_tree is not None:
        for child in list(sp_tree):
            if child.tag not in {f"{{{P_NS}}}sp", f"{{{P_NS}}}graphicFrame", f"{{{P_NS}}}cxnSp"}:
                continue
            kind = "shape" if child.tag in {f"{{{P_NS}}}sp", f"{{{P_NS}}}cxnSp"} else "graphicFrame"
            row_count, col_count = _table_dimensions(child) if kind == "graphicFrame" else (0, 0)
            objects.append(
                {
                    "kind": kind,
                    "name": _shape_name(child),
                    "text": "\n".join(_extract_texts(child)),
                    "x": _extract_x(child),
                    "table_rows": row_count,
                    "table_cols": col_count,
                }
            )
    return {
        "objects": objects,
        "texts": [item["text"] for item in objects if item["text"]],
        "text": "\n".join(item["text"] for item in objects if item["text"]),
        "object_names": [item["name"] for item in objects],
        "object_count": len(objects),
        "shape_count": sum(1 for item in objects if item["kind"] == "shape"),
        "graphic_frame_count": sum(1 for item in objects if item["kind"] == "graphicFrame"),
        "table_shapes": [item for item in objects if item["kind"] == "graphicFrame" and item["table_rows"] > 0],
    }


def _pptx_extract(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as zf:
        entries = sorted(zf.namelist())
        required = {
            "[Content_Types].xml",
            "ppt/presentation.xml",
            "ppt/_rels/presentation.xml.rels",
            "ppt/slideMasters/slideMaster1.xml",
            "ppt/slideLayouts/slideLayout1.xml",
            "ppt/theme/theme1.xml",
        }
        missing_required = sorted(required - set(entries))
        content_types_text = _read_zip_text(zf, "[Content_Types].xml") if "[Content_Types].xml" in entries else ""
        presentation_xml_parseable = False
        presentation_relationships_parseable = False
        slide_paths: list[str] = []
        slide_records: list[dict[str, Any]] = []
        slide_parse_errors: list[str] = []
        if "ppt/presentation.xml" in entries:
            _parse_xml(zf.read("ppt/presentation.xml"), "ppt/presentation.xml")
            presentation_xml_parseable = True
        if "ppt/_rels/presentation.xml.rels" in entries:
            _parse_xml(zf.read("ppt/_rels/presentation.xml.rels"), "ppt/_rels/presentation.xml.rels")
            presentation_relationships_parseable = True
        if presentation_xml_parseable and presentation_relationships_parseable:
            slide_paths = _slide_paths_in_order(zf)
            for path_name in slide_paths:
                if path_name not in entries:
                    slide_parse_errors.append(f"missing {path_name}")
                    continue
                try:
                    slide_records.append(_slide_record(zf.read(path_name)))
                except Exception as exc:  # noqa: BLE001 - verifier returns diagnostic details
                    slide_parse_errors.append(f"{path_name}: {exc}")
        rel_external: list[dict[str, Any]] = []
        xml_bad_urls: list[dict[str, Any]] = []
        all_xml_text_parts: list[str] = []
        xml_text_by_part: dict[str, str] = {}
        for entry in entries:
            if entry.endswith(".xml") or entry.endswith(".rels"):
                text = zf.read(entry).decode("utf-8", errors="replace")
                all_xml_text_parts.append(text)
                xml_text_by_part[entry] = text
                for url in EXTERNAL_URL_RE.findall(text):
                    if not url.casefold().startswith(STANDARD_XML_URI_PREFIXES):
                        xml_bad_urls.append({"part": entry, "category": _external_target_category(url)})
            if entry.endswith(".rels"):
                try:
                    root = _parse_xml(zf.read(entry), entry)
                    for rel in root.findall("rel:Relationship", NS):
                        target = rel.attrib.get("Target", "")
                        mode = rel.attrib.get("TargetMode", "")
                        if mode.casefold() == "external" or target.lower().startswith(("http://", "https://", "file://", "ftp://", "s3://", "gs://")):
                            rel_external.append({"part": entry, "category": _external_target_category(target)})
                except Exception:  # noqa: BLE001 - keep diagnostics redacted
                    rel_external.append({"part": entry, "category": "relationship_parse_error"})
        all_text = "\n".join(record["text"] for record in slide_records)
        raw_xml = "\n".join(all_xml_text_parts)
        return {
            "entries": entries,
            "missing_required": missing_required,
            "content_types_text": content_types_text,
            "content_types_include_presentation": "presentationml.presentation.main+xml" in content_types_text,
            "presentation_xml_parseable": presentation_xml_parseable,
            "presentation_relationships_parseable": presentation_relationships_parseable,
            "slide_paths": slide_paths,
            "slide_records": slide_records,
            "slide_parse_errors": slide_parse_errors,
            "all_text": all_text,
            "raw_xml": raw_xml,
            "xml_text_by_part": xml_text_by_part,
            "external_relationships": _summarize_redacted_findings(rel_external, placeholder="<redacted-external-relationship>"),
            "xml_bad_urls": _summarize_redacted_findings(xml_bad_urls, placeholder="<redacted-external-url>"),
        }


def _read_workbook_contract(case_dir: Path) -> dict[str, Any]:
    if load_workbook is None:
        return {"openable": False, "error": "openpyxl is not installed"}
    path = case_dir / INPUT_WORKBOOK_REL
    try:
        wb = load_workbook(path, data_only=True)
    except Exception as exc:  # noqa: BLE001
        return {"openable": False, "error": str(exc)}

    def rows(sheet_name: str) -> list[dict[str, Any]]:
        ws = wb[sheet_name]
        raw_rows = list(ws.iter_rows(values_only=True))
        if not raw_rows:
            return []
        headers = [str(cell or "") for cell in raw_rows[0]]
        out = []
        for raw in raw_rows[1:]:
            item = {headers[idx]: raw[idx] if idx < len(raw) else None for idx in range(len(headers)) if headers[idx]}
            if any(value not in (None, "") for value in item.values()):
                out.append(item)
        return out

    readme = {str(row.get("字段", "")): str(row.get("说明", "")) for row in rows("00_阅读说明")}
    milestone_rows = rows("里程碑更新")
    current = [row for row in milestone_rows if str(row.get("材料范围")) == "本次治理会材料"]
    excluded = [row for row in milestone_rows if str(row.get("材料范围")) != "本次治理会材料"]
    version_rows = rows("版本与日期口径")
    return {"openable": True, "readme": readme, "current": current, "excluded": excluded, "version_rows": version_rows}


def _normalize_workbook_current(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    fields = {
        "record_no": "记录号",
        "item_id": "事项编号",
        "item_name": "事项名称",
        "workstream": "工作流",
        "current_status": "当前口径/状态",
        "raw_date": "原始日期写法",
        "date_display": "日期展示建议",
        "version_raw": "版本口径",
        "scope": "材料范围",
    }
    return [{key: str(row.get(src, "")) for key, src in fields.items()} for row in rows]


def _normalize_workbook_excluded(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    fields = {"record_no": "记录号", "item_id": "事项编号", "item_name": "事项名称", "current_status": "当前口径/状态", "date_display": "日期展示建议", "scope": "材料范围"}
    return [{key: str(row.get(src, "")) for key, src in fields.items()} for row in rows]


def _private_matches(text: str) -> list[str]:
    hits: list[str] = []
    for pattern in PRIVATE_PATTERNS:
        hits.extend(match.group(0) for match in pattern.finditer(text))
    return sorted(set(hits))


def _secret_matches(text: str) -> list[str]:
    hits: list[str] = []
    for pattern in SECRET_PATTERNS:
        hits.extend(match.group(0) for match in pattern.finditer(text))
    return sorted(set(hits))


def _summary_has_hits(summary: dict[str, Any]) -> bool:
    return int(summary.get("count", 0)) > 0


def _slide_text(slides: list[dict[str, Any]], num: int) -> str:
    if 1 <= num <= len(slides):
        return slides[num - 1]["text"]
    return ""


def _object_text(slides: list[dict[str, Any]], num: int, object_name: str) -> str:
    if not (1 <= num <= len(slides)):
        return ""
    for obj in slides[num - 1].get("objects", []):
        if obj.get("name") == object_name:
            return str(obj.get("text", ""))
    return ""


def _table_by_name(slide: dict[str, Any], name: str) -> dict[str, Any] | None:
    for item in slide.get("table_shapes", []):
        if item.get("name") == name:
            return item
    return None


def _truncate_chars(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    marker = "\n\n[TRUNCATED by deterministic verifier: public text exceeded judge evidence character limit.]\n"
    keep = max(0, max_chars - len(marker))
    return text[:keep].rstrip() + marker


def _log_rel(path: Path, verifier_logs: Path) -> str:
    try:
        return path.resolve().relative_to(verifier_logs.resolve()).as_posix()
    except Exception:
        return "external_path_outside_verifier_log"


def _deterministic_safety_failed(result: dict[str, Any]) -> bool:
    safety_checks = {
        "no_external_relationships",
        "no_external_url_or_file_uri",
        "no_private_paths_or_source_locators",
        "no_secret_like_strings",
        "no_forbidden_dependency_claims",
    }
    return any(check.get("name") in safety_checks and not check.get("passed") for check in result.get("checks", []))


def _candidate_is_usable_for_judge(candidate: Path | None, result: dict[str, Any]) -> bool:
    required = {"output_pptx_discovered", "output_extension_pptx", "output_zip_openable"}
    check_map = {check.get("name"): check.get("passed") for check in result.get("diagnostic_checks") or result.get("checks", [])}
    return bool(candidate and candidate.exists() and all(check_map.get(name) is True for name in required))


def _slide_text_markdown(title: str, pptx: dict[str, Any] | None, *, missing_note: str) -> str:
    parts = [f"# {title}", ""]
    if pptx is None:
        parts.append(missing_note)
        return "\n".join(parts).strip() + "\n"
    for idx, slide in enumerate(pptx.get("slide_records", []), 1):
        parts.extend([f"## Slide {idx}", ""])
        for obj in slide.get("objects", []):
            text = str(obj.get("text", "")).strip()
            if text:
                parts.append(f"### {obj.get('name', '<unnamed object>')}")
                parts.append(text)
                parts.append("")
    return "\n".join(parts).strip() + "\n"


def _base_vs_submitted_delta_markdown(case_dir: Path, submitted: dict[str, Any] | None) -> str:
    parts = ["# Base vs Submitted Slide Text Delta", "", "This evidence compares extractable PPTX text only. It does not use rendered images, OCR, VLM, pixel scoring, hidden oracle prose, private trace material, or external services.", ""]
    try:
        base = _pptx_extract(case_dir / INPUT_DECK_REL)
    except Exception as exc:  # noqa: BLE001
        parts.append(f"Base deck extraction failed: {exc}")
        return "\n".join(parts).strip() + "\n"
    if submitted is None:
        parts.append("Submitted PPTX extraction unavailable; see deterministic gate status.")
        return "\n".join(parts).strip() + "\n"
    base_slides = base.get("slide_records", [])
    submitted_slides = submitted.get("slide_records", [])
    for idx in range(1, max(len(base_slides), len(submitted_slides)) + 1):
        base_text = _slide_text(base_slides, idx)
        submitted_text = _slide_text(submitted_slides, idx)
        if base_text == submitted_text:
            parts.extend([f"## Slide {idx}", "No extractable text change.", ""])
            continue
        base_lines = [line.strip() for line in base_text.splitlines() if line.strip()]
        submitted_lines = [line.strip() for line in submitted_text.splitlines() if line.strip()]
        added = [line for line in submitted_lines if line not in base_lines]
        removed = [line for line in base_lines if line not in submitted_lines]
        parts.extend([f"## Slide {idx}", "### Added or revised submitted text"])
        parts.extend([f"- {line}" for line in added[:80]] or ["- none"])
        parts.append("### Removed or replaced base text")
        parts.extend([f"- {line}" for line in removed[:80]] or ["- none"])
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def _public_workbook_summary_markdown(gold: dict[str, Any]) -> str:
    wb = gold.get("workbook_expected", {})
    parts = [
        "# Public Workbook Update Summary",
        "",
        "This Judge evidence is derived only from the approved public source workbook and hidden deterministic contract fields that mirror the public workbook after P6/P8 surface approval. It summarizes visible source rows without exposing hidden oracle prose or private trace material.",
        "",
        "Exact workbook facts, date normalization, hashes, and source binding remain deterministic-only checks.",
        "",
        f"- Current workbook scope value: {wb.get('current_scope_value')}",
        f"- Material date for footers: {wb.get('material_date')}",
        f"- Current version display: {wb.get('current_version_display')}",
        "",
        "## Current-scope rows",
    ]
    for row in wb.get("current_records", []):
        parts.append(
            "- "
            + "; ".join(
                [
                    f"record={row.get('record_no')}",
                    f"item={row.get('item_id')} {row.get('item_name')}",
                    f"scope={row.get('scope')}",
                    f"status={row.get('current_status')}",
                    f"date={row.get('date_display')}",
                    f"targets={', '.join(row.get('target_pages', []))}",
                    f"note={row.get('note')}",
                ]
            )
        )
    parts.extend(["", "## Excluded or distractor rows"])
    for row in wb.get("excluded_records", []):
        parts.append(
            "- "
            + "; ".join(
                [
                    f"record={row.get('record_no')}",
                    f"item={row.get('item_id')} {row.get('item_name')}",
                    f"scope={row.get('scope')}",
                    f"status={row.get('current_status')}",
                    f"date={row.get('date_display')}",
                    f"targets={', '.join(row.get('target_pages', []))}",
                    f"note={row.get('note')}",
                ]
            )
        )
    parts.extend(["", "## Alias and scope reminders"])
    for row in wb.get("alias_rows", []):
        parts.append("- " + "; ".join(f"{key}={value}" for key, value in row.items()))
    for row in wb.get("out_of_scope_rows", []):
        parts.append("- out_of_scope: " + "; ".join(f"{key}={value}" for key, value in row.items()))
    return _truncate_chars("\n".join(parts).strip() + "\n", JUDGE_EVIDENCE_LIMITS["public_workbook_update_summary"])


def _public_base_deck_summary_markdown(case_dir: Path) -> str:
    parts = [
        "# Public Base Deck Role Summary",
        "",
        "This Judge evidence summarizes extractable text and role cues from the approved public base PPTX. It is text-only and does not inspect rendered pixels, screenshots, OCR, or VLM outputs.",
        "",
        "The base deck is a stale governance-board work draft. The revised deliverable should preserve slide order, section roles, footer objects, cards, tables, timeline labels, historical archive, and template page purpose while updating only source-supported current-scope text.",
        "",
    ]
    try:
        base = _pptx_extract(case_dir / INPUT_DECK_REL)
    except Exception as exc:  # noqa: BLE001
        parts.append(f"Base deck extraction failed: {exc}")
        return "\n".join(parts).strip() + "\n"
    for idx, slide in enumerate(base.get("slide_records", []), 1):
        title = next((obj.get("text", "").splitlines()[0] for obj in slide.get("objects", []) if obj.get("text")), "")
        object_names = ", ".join(str(name) for name in slide.get("object_names", []))
        parts.extend([f"## Slide {idx}: {title}", f"Objects: {object_names}", ""])
        for obj in slide.get("objects", []):
            text = str(obj.get("text", "")).strip()
            if text:
                parts.append(f"- {obj.get('name')}: {text.replace(chr(10), ' / ')}")
        parts.append("")
    return _truncate_chars("\n".join(parts).strip() + "\n", JUDGE_EVIDENCE_LIMITS["public_base_deck_role_summary"])


def _judge_scope_status_markdown(result: dict[str, Any]) -> str:
    failed = [check.get("name") for check in result.get("checks", []) if not check.get("passed")]
    safety_failed = _deterministic_safety_failed(result)
    lines = [
        "# Judge Scope and Deterministic Gate Status",
        "",
        "This evidence is produced by the deterministic verifier for supplemental text-only WB Judge consumption.",
        "",
        "## Deterministic status",
        f"- passed_count: {result.get('passed_count')}",
        f"- total_count: {result.get('total_count')}",
        f"- pass_rate: {result.get('pass_rate')}",
        f"- deterministic_gated_pass: {str(result.get('gated_pass')).lower()}",
        f"- deterministic_safety_or_leakage_failed: {str(safety_failed).lower()}",
        f"- llm_judge_activation_allowed: {str(not safety_failed).lower()}",
        f"- failed_checks: {', '.join(map(str, failed)) if failed else 'none'}",
        "",
        "LLM Judge may run when required judge_evidence files exist and deterministic safety/leakage checks pass. Deterministic component score, failed_checks, objective file/structure/source/safety failures, and gate status must remain separate and visible.",
        "",
        "## Judge modality and allowed scope",
        "- Text-only artifact-level semantic review over submitted slide text, base-vs-submitted text delta, and public workbook/deck summaries.",
        "- Judge may assess narrative integration, prioritization, governance-style concision, non-mechanical patch quality, and synthesized risk/decision framing consistency.",
        "",
        "## Deterministic-owned scope not scored by Judge",
        "- exact workbook facts, exact date/status/version correctness, co-location checks, output file existence, PPTX parseability, slide count/order, object/table structure, input hashes, safety/leakage, external dependencies, and forbidden artifacts",
        "- visual rendering, OCR, VLM, pixel-level similarity, hidden oracle phrase matching, model process/tool trace quality, or private trace fidelity",
        "",
        "## Exclusion boundary",
        "This file excludes raw private trace text, private paths, private URLs, private emails, account IDs, credentials, customer data, proprietary code, unpublished assets, and hidden oracle prose.",
    ]
    return _truncate_chars("\n".join(lines).strip() + "\n", JUDGE_EVIDENCE_LIMITS["judge_scope_and_gate_status"])


def _write_verifier_artifacts(candidate: Path | None, pptx: dict[str, Any] | None, workbook: dict[str, Any], result: dict[str, Any], verifier_logs: Path, case_dir: Path, gold: dict[str, Any]) -> dict[str, Any]:
    artifact_text = verifier_logs / "artifact_text"
    raw_artifacts = verifier_logs / "raw_artifacts"
    judge_dir = verifier_logs / "judge_evidence"
    artifact_text.mkdir(parents=True, exist_ok=True)
    raw_artifacts.mkdir(parents=True, exist_ok=True)
    judge_dir.mkdir(parents=True, exist_ok=True)

    safety_failed = _deterministic_safety_failed(result)
    usable_pptx = _candidate_is_usable_for_judge(candidate, result) and pptx is not None
    judge_activation_allowed = bool(not safety_failed and usable_pptx)

    failed_checks = [check.get("name") for check in result.get("checks", []) if not check.get("passed")]
    summary = {
        "passed_count": result.get("passed_count"),
        "total_count": result.get("total_count"),
        "pass_rate": result.get("pass_rate"),
        "gated_pass": result.get("gated_pass"),
        "failed_checks": failed_checks,
        "groups": sorted({check.get("group") for check in result.get("checks", []) if check.get("group")}),
        "judge_planned": True,
        "judge_kind": "wb",
        "judge_modality": "text_only",
        "judge_activation_allowed": judge_activation_allowed,
        "judge_activation_block_reason": None if judge_activation_allowed else ("deterministic_safety_or_leakage_check_failed" if safety_failed else "submitted_pptx_text_unavailable"),
    }
    summary_path = artifact_text / "deterministic_eval_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    raw_paths: list[str] = []
    if candidate and candidate.exists() and candidate.is_file() and not safety_failed:
        raw_copy = raw_artifacts / candidate.name
        if raw_copy.resolve() != candidate.resolve():
            shutil.copy2(candidate, raw_copy)
        raw_paths.append(_log_rel(raw_copy, verifier_logs))

    evidence_payloads = {
        "judge_scope_and_gate_status": _judge_scope_status_markdown(result),
        "submitted_deck_slide_text": _slide_text_markdown(
            "Submitted Revised Deck Slide Text",
            pptx if usable_pptx and not safety_failed else None,
            missing_note="Submitted PPTX text is unavailable or withheld because deterministic safety/leakage or output-gate checks failed.",
        ),
        "base_vs_submitted_slide_delta": _base_vs_submitted_delta_markdown(case_dir, pptx if usable_pptx and not safety_failed else None),
        "public_workbook_update_summary": _public_workbook_summary_markdown(gold),
        "public_base_deck_role_summary": _public_base_deck_summary_markdown(case_dir),
    }
    judge_records: list[dict[str, Any]] = []
    for evidence_id, rel_path in JUDGE_EVIDENCE_FILES.items():
        path = verifier_logs / rel_path
        text = _truncate_chars(evidence_payloads[evidence_id], JUDGE_EVIDENCE_LIMITS[evidence_id])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        judge_records.append(
            {
                "id": evidence_id,
                "path_role": rel_path.as_posix(),
                "relative_path": rel_path.as_posix(),
                "kind": "judge_evidence",
                "required": True,
                "text_only_public_safe": True,
                "judge_activation_usable": judge_activation_allowed,
                "bytes": path.stat().st_size,
                "characters": len(text),
                "max_chars": JUDGE_EVIDENCE_LIMITS[evidence_id],
            }
        )

    manifest = {
        "case_slug": "board_material_update_timeline_excel",
        "stage": "verifier",
        "deterministic_first": True,
        "judge_config_created_by_this_worker": False,
        "judge_evidence_extraction_created_by_this_worker": True,
        "judge_boundary": "Supplemental text-only Judge may consume verifier-owned public artifact evidence but must not own deterministic hard facts, file integrity, safety, exact source facts, or hidden oracle phrase matching.",
        "inputs_consumed": [
            "submitted revised PPTX artifact",
            "approved public PPTX/XLSX/environment inputs",
            "hidden deterministic gold contract derived from approved public inputs",
        ],
        "private_trace_dependency": False,
        "created_artifacts": [
            {"path_role": _log_rel(summary_path, verifier_logs), "relative_path": _log_rel(summary_path, verifier_logs), "kind": "artifact_text", "description": "Deterministic pass/fail summary and Judge activation status"},
            *judge_records,
        ],
        "judge_evidence": judge_records,
        "judge_evidence_safety": {
            "deterministic_safety_failed": safety_failed,
            "submitted_output_text_withheld": bool(safety_failed or not usable_pptx),
            "llm_judge_activation_allowed": judge_activation_allowed,
            "policy": "withhold submitted-output text from judge_evidence and skip LLM Judge activation when deterministic safety/leakage or output-gate checks fail",
        },
        "judge_activation_allowed": judge_activation_allowed,
        "judge_activation_block_reason": summary["judge_activation_block_reason"],
        "raw_artifacts": raw_paths,
        "check_summary": summary,
    }
    (verifier_logs / "artifact_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def evaluate(output_path: str | Path | None = None, *, case_dir: str | Path = CASE_DIR, verifier_logs: str | Path | None = None) -> dict[str, Any]:
    case_dir = Path(case_dir).resolve()
    gold = _load_gold(case_dir)
    checks: list[dict[str, Any]] = []

    # Public-input immutability and source workbook binding checks.
    for rel, check_name, role in [
        (INPUT_DECK_REL, "input_base_deck_sha256_unchanged", "base PPTX"),
        (INPUT_WORKBOOK_REL, "input_workbook_sha256_unchanged", "source workbook"),
        (ENV_NOTE_REL, "input_environment_sha256_unchanged", "environment note"),
    ]:
        expected = next((item for item in gold.get("public_inputs", []) if item.get("path") == rel.as_posix()), {})
        path = case_dir / rel
        actual = _sha256(path) if path.exists() else None
        _check(checks, "verifier_isolation", check_name, bool(actual and actual == expected.get("sha256")), {"role": role, "actual": actual, "expected": expected.get("sha256")})

    workbook = _read_workbook_contract(case_dir)
    _check(checks, "workbook_to_slide_mapping", "source_workbook_openable", workbook.get("openable") is True, workbook.get("error", "ok"))
    if workbook.get("openable"):
        material_readme = str(workbook["readme"].get("资料口径日期", ""))
        _check(checks, "workbook_to_slide_mapping", "workbook_material_date_matches_gold", gold["workbook_expected"]["material_date"] in material_readme, material_readme)
        current_actual = _normalize_workbook_current(workbook["current"])
        current_expected = [
            {key: str(row.get(key, "")) for key in ["record_no", "item_id", "item_name", "workstream", "current_status", "raw_date", "date_display", "version_raw", "scope"]}
            for row in gold["workbook_expected"]["current_records"]
        ]
        _check(checks, "workbook_to_slide_mapping", "workbook_current_records_match_gold", current_actual == current_expected, {"actual": current_actual, "expected": current_expected})
        excluded_actual = _normalize_workbook_excluded(workbook["excluded"])
        excluded_expected = [
            {key: str(row.get(key, "")) for key in ["record_no", "item_id", "item_name", "current_status", "date_display", "scope"]}
            for row in gold["workbook_expected"]["excluded_records"]
        ]
        _check(checks, "workbook_to_slide_mapping", "workbook_excluded_records_match_gold", excluded_actual == excluded_expected, {"actual": excluded_actual, "expected": excluded_expected})
        version_display = {str(row.get("原始字段", "")): str(row.get("PPT展示口径", "")) for row in workbook["version_rows"]}
        expected_version = gold["workbook_expected"].get("version_normalization", {})
        _check(
            checks,
            "workbook_to_slide_mapping",
            "workbook_version_normalization_rows_match_gold",
            all(str(version_display.get(key, "")) == str(value) for key, value in expected_version.items() if key in version_display),
            {"actual": version_display, "expected_subset": expected_version},
        )
    else:
        for name in ["workbook_material_date_matches_gold", "workbook_current_records_match_gold", "workbook_excluded_records_match_gold", "workbook_version_normalization_rows_match_gold"]:
            _check(checks, "workbook_to_slide_mapping", name, False, "source workbook unavailable")

    target = Path(output_path).resolve() if output_path is not None else None
    discovery = _discover_output(target, case_dir)
    candidate: Path | None = discovery["candidate"]
    pptx_files: list[Path] = discovery["pptx_files"]
    context_files: list[Path] = discovery["context_files"]
    forbidden_extra = [str(path) for path in context_files if path.suffix.lower() in FORBIDDEN_OUTPUT_SUFFIXES and path != candidate]

    _check(checks, "output_contract", "output_pptx_discovered", candidate is not None and candidate.exists(), {"candidate": str(candidate) if candidate else None, "pptx_files": [str(path) for path in pptx_files], "mode": discovery["mode"]})
    _check(checks, "output_contract", "output_single_pptx_unambiguous", len(pptx_files) == 1 if discovery["mode"] != "explicit_file" else bool(candidate and candidate.suffix.lower() == ".pptx"), [str(path) for path in pptx_files])
    _check(checks, "output_contract", "output_extension_pptx", bool(candidate and candidate.suffix.lower() == ".pptx"), str(candidate) if candidate else None)
    _check(checks, "output_contract", "output_file_nonempty", bool(candidate and candidate.exists() and candidate.stat().st_size > 0), candidate.stat().st_size if candidate and candidate.exists() else None)
    public_input = (case_dir / INPUT_DECK_REL).resolve()
    _check(checks, "output_contract", "output_not_public_input_file", bool(candidate and candidate.resolve() != public_input), {"candidate": str(candidate) if candidate else None, "public_input": str(public_input)})
    base_sha = _sha256(public_input) if public_input.exists() else None
    cand_sha = _sha256(candidate) if candidate and candidate.exists() else None
    _check(checks, "output_contract", "output_not_base_deck_clone", bool(cand_sha and base_sha and cand_sha != base_sha), {"candidate_sha256": cand_sha, "base_sha256": base_sha})
    _check(checks, "output_contract", "no_forbidden_extra_delivery_artifacts", not forbidden_extra, forbidden_extra)

    pptx: dict[str, Any] | None = None
    zip_open = False
    if candidate and candidate.exists():
        try:
            with zipfile.ZipFile(candidate) as zf:
                zf.testzip()
            zip_open = True
        except Exception as exc:  # noqa: BLE001
            _check(checks, "file_integrity", "output_zip_openable", False, str(exc))
    if zip_open:
        _check(checks, "file_integrity", "output_zip_openable", True, "PPTX zip opens and testzip passes")
        try:
            pptx = _pptx_extract(candidate)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            pptx = None
            _check(checks, "file_integrity", "output_required_ooxml_parts_present", False, f"extract failed: {exc}")
    elif not any(check["name"] == "output_zip_openable" for check in checks):
        _check(checks, "file_integrity", "output_zip_openable", False, "candidate missing or not a zip")

    if pptx is None:
        for name in ["output_required_ooxml_parts_present", "output_content_types_include_presentation", "output_presentation_xml_parseable", "output_presentation_relationships_parseable", "output_slides_xml_parseable"]:
            if not any(check["name"] == name for check in checks):
                _check(checks, "file_integrity", name, False, "PPTX extraction unavailable")
        result = _build_result(checks, gold)
        if verifier_logs is not None:
            manifest = _write_verifier_artifacts(candidate, pptx, workbook, result, Path(verifier_logs), case_dir, gold)
            result = {**result, "artifact_manifest": manifest}
        return result

    slides: list[dict[str, Any]] = pptx["slide_records"]
    all_text = pptx["all_text"]
    xml_text_by_part = pptx.get("xml_text_by_part", {})
    slide_count_expected = int(gold["output_contract"]["expected_slide_count"])

    _check(checks, "file_integrity", "output_required_ooxml_parts_present", not pptx["missing_required"], pptx["missing_required"])
    _check(checks, "file_integrity", "output_content_types_include_presentation", pptx["content_types_include_presentation"], "presentation content type present")
    _check(checks, "file_integrity", "output_presentation_xml_parseable", pptx["presentation_xml_parseable"], "ppt/presentation.xml")
    _check(checks, "file_integrity", "output_presentation_relationships_parseable", pptx["presentation_relationships_parseable"], "ppt/_rels/presentation.xml.rels")
    _check(checks, "file_integrity", "output_slides_xml_parseable", not pptx["slide_parse_errors"] and len(slides) == len(pptx["slide_paths"]), pptx["slide_parse_errors"])
    _check(checks, "template_preservation", "output_slide_count_11", len(slides) == slide_count_expected, {"actual": len(slides), "expected": slide_count_expected})
    expected_slide_paths = [f"ppt/slides/slide{i}.xml" for i in range(1, slide_count_expected + 1)]
    _check(checks, "template_preservation", "slide_order_matches_base", pptx["slide_paths"] == expected_slide_paths, {"actual": pptx["slide_paths"], "expected": expected_slide_paths})

    section_results = []
    object_name_results = []
    table_results = []
    for slide in gold["deck_structure"]["slides"]:
        num = int(slide["slide_number"])
        actual = slides[num - 1] if 1 <= num <= len(slides) else {"text": "", "object_names": [], "object_count": 0, "shape_count": 0, "graphic_frame_count": 0, "table_shapes": []}
        text = actual["text"]
        _check(checks, "template_preservation", f"slide_{num:02d}_object_count_preserved", actual["object_count"] == int(slide["object_count"]), {"actual": actual["object_count"], "expected": slide["object_count"]})
        _check(checks, "template_preservation", f"slide_{num:02d}_shape_count_preserved", actual["shape_count"] == int(slide["shape_count"]), {"actual": actual["shape_count"], "expected": slide["shape_count"]})
        _check(checks, "template_preservation", f"slide_{num:02d}_graphic_frame_count_preserved", actual["graphic_frame_count"] == int(slide["graphic_frame_count"]), {"actual": actual["graphic_frame_count"], "expected": slide["graphic_frame_count"]})
        section_ok = _contains_all(text, SECTION_TOKENS[num])
        section_results.append(section_ok)
        _check(checks, "template_preservation", f"slide_{num:02d}_section_title_present", section_ok, SECTION_TOKENS[num])
        for idx, name in enumerate(slide.get("object_names", [])):
            ok = name in actual["object_names"]
            object_name_results.append(ok)
            _check(checks, "template_preservation", f"slide_{num:02d}_object_{idx:02d}_present", ok, name)
        for idx, table in enumerate(slide.get("table_shapes", [])):
            actual_table = _table_by_name(actual, table["name"])
            ok = bool(actual_table and actual_table["table_rows"] == int(table["row_count"]) and actual_table["table_cols"] == int(table["col_count"]))
            table_results.append(ok)
            _check(checks, "template_preservation", f"slide_{num:02d}_table_{idx:02d}_structure", ok, {"name": table["name"], "actual": actual_table, "expected": table})
        footer_name = f"页脚_版本口径_{num}"
        footer_objs = [obj for obj in actual.get("objects", []) if obj.get("name") == footer_name]
        footer_text = "\n".join(obj.get("text", "") for obj in footer_objs)
        _check(checks, "timeline_version_consistency", f"slide_{num:02d}_footer_object_present", bool(footer_objs), footer_name)
        _check(
            checks,
            "timeline_version_consistency",
            f"slide_{num:02d}_footer_version_date",
            "v1.8 当前" in footer_text and "资料口径：2026-07-01" in footer_text,
            footer_text,
        )
    _check(checks, "template_preservation", "slide_titles_sections_preserved", all(section_results), section_results)
    _check(checks, "template_preservation", "shape_object_names_preserved", all(object_name_results), f"{sum(object_name_results)}/{len(object_name_results)} object names present")
    _check(checks, "template_preservation", "table_structure_all_expected", all(table_results), f"{sum(table_results)}/{len(table_results)} table structures matched")

    timeline_names = ["TL-合作点确认_节点", "TL-数据口径_节点", "TL-培训_节点", "TL-回访_节点", "TL-复盘_节点"]
    slide4 = slides[3] if len(slides) >= 4 else {"objects": []}
    timeline_positions = []
    for name in timeline_names:
        matches = [obj for obj in slide4.get("objects", []) if obj.get("name") == name]
        timeline_positions.append(matches[0]["x"] if matches else None)
    _check(checks, "template_preservation", "timeline_object_order_preserved", all(pos is not None for pos in timeline_positions) and timeline_positions == sorted(timeline_positions), {"names": timeline_names, "x_positions": timeline_positions})

    footer_texts = []
    for idx, slide in enumerate(slides, 1):
        footer_texts.extend(obj.get("text", "") for obj in slide.get("objects", []) if obj.get("name") == f"页脚_版本口径_{idx}")
    _check(checks, "timeline_version_consistency", "footer_all_slides_v1_8_current", len(footer_texts) == slide_count_expected and all("v1.8 当前" in text for text in footer_texts), footer_texts)
    _check(checks, "timeline_version_consistency", "footer_all_slides_material_date_2026_07_01", len(footer_texts) == slide_count_expected and all("资料口径：2026-07-01" in text for text in footer_texts), footer_texts)
    _check(checks, "timeline_version_consistency", "old_footer_version_absent", "v1.7 草稿" not in all_text, "v1.7 草稿 absent")
    _check(checks, "timeline_version_consistency", "old_material_date_absent", "2026-06-12" not in all_text, "2026-06-12 absent")
    raw_version_aliases_present = [alias for alias in ["v1.8-current"] if alias in all_text]
    if re.search(r"(?<![vV])1\.8\s*当前", all_text):
        raw_version_aliases_present.append("1.8 当前")
    _check(checks, "timeline_version_consistency", "version_aliases_normalized_current", not raw_version_aliases_present, {"raw_aliases_present": raw_version_aliases_present})

    for slide_key, spec in gold.get("required_slide_expectations", {}).items():
        num = int(slide_key)
        text = _slide_text(slides, num)
        for idx, term in enumerate(spec.get("all", [])):
            _check(checks, "workbook_to_slide_mapping", f"slide_{num:02d}_required_text_{idx:02d}", _contains(text, term), term)
        for idx, term in enumerate(spec.get("none", [])):
            _check(checks, "distractor_non_updates", f"slide_{num:02d}_forbidden_text_{idx:02d}_absent", not _contains(text, term), term)

    _check(checks, "timeline_version_consistency", "slide_03_current_overview_mapping", _contains_all(_slide_text(slides, 3), ["v1.8 当前治理包", "服务站签约：6月30日已完成", "7月3日进入抽样复核", "采购口径7月5日前确认", "黄色关注，保留专项跟踪"]), _slide_text(slides, 3))
    _check(checks, "timeline_version_consistency", "slide_04_date_normalization", _contains_all(_slide_text(slides, 4), ["6月30日已完成", "7月3日抽样复核", "7月15日已锁定", "8月第一周黄色关注"]) and _contains_none(_slide_text(slides, 4), ["6/20 待确认", "6/26 草案", "7月上旬待排期", "8月待定"]), _slide_text(slides, 4))
    _check(checks, "timeline_version_consistency", "slide_07_decision_deadline_and_risk_window", _contains_all(_slide_text(slides, 7), ["待治理会确认", "7月5日前审定采购口径", "培训启动日为7月15日", "8月第一周复盘风险窗口"]), _slide_text(slides, 7))

    for item in gold.get("one_to_many_sync", []):
        safe_item = re.sub(r"[^A-Za-z0-9]+", "_", str(item["item_id"])).strip("_")
        terms = item.get("required_terms", [])
        required_hits = min(2, len(terms)) if terms else 0
        for slide_num in item.get("slides", []):
            text = _slide_text(slides, int(slide_num))
            hits = [term for term in terms if _contains(text, term)]
            _check(checks, "workbook_to_slide_mapping", f"sync_{safe_item}_slide_{int(slide_num):02d}", len(hits) >= required_hits, {"hits": hits, "required_terms": terms, "required_hits": required_hits, "slide": int(slide_num)})

    for item in gold.get("co_location_expectations", []):
        slide_num = int(item.get("slide", 0))
        object_name = str(item.get("object_name", ""))
        object_text = _object_text(slides, slide_num, object_name)
        required_terms = [str(term) for term in item.get("required_terms", [])]
        forbidden_terms = [str(term) for term in item.get("forbidden_terms", [])]
        required_hits = [term for term in required_terms if _contains(object_text, term)]
        forbidden_hits = [term for term in forbidden_terms if _contains(object_text, term)]
        _check(
            checks,
            str(item.get("group", "workbook_to_slide_mapping")),
            f"co_location_{item['id']}",
            bool(object_text) and len(required_hits) == len(required_terms) and not forbidden_hits,
            {"slide": slide_num, "object_name": object_name, "required_hits": required_hits, "required_terms": required_terms, "forbidden_hits": forbidden_hits},
        )

    slide10_text = _slide_text(slides, 10)
    slide11_text = _slide_text(slides, 11)
    _check(checks, "distractor_non_updates", "distractor_history_slide_preserved", _contains_all(slide10_text, ["北岸书屋合作点确认", "已归档", "2025-06-20", "服务包数据回收", "已复盘", "2025-07-11", "志愿者培训", "完成", "2025-08-02"]) and _contains_none(slide10_text, ["6月30日已完成", "7月3日抽样复核", "7月15日已锁定", "黄色关注，保留专项跟踪"]), slide10_text)
    _check(checks, "distractor_non_updates", "distractor_template_slide_preserved", _contains_all(slide11_text, ["样例卡片标题", "样例状态芯片", "样例行动项", "占位文本", "不参与本次更新"]) and _contains_none(slide11_text, ["M-101", "M-205", "M-310", "DEC-044", "6月30日已完成", "7月3日抽样复核", "7月15日已锁定"]), slide11_text)
    _check(checks, "distractor_non_updates", "distractor_future_draft_not_promoted", _contains(_slide_text(slides, 7), "试点二期扩展") and _contains(_slide_text(slides, 7), "不进入本次正文") and _contains_none(all_text, ["试点二期扩展 8月中旬", "v1.9 draft"]), _slide_text(slides, 7))
    _check(checks, "distractor_non_updates", "distractor_monitoring_not_promoted", _contains(_slide_text(slides, 6), "只用于会后跟踪") and _contains(_slide_text(slides, 6), "不替换正文状态或时间线") and _contains_none(all_text, ["短期回访观察 7月下旬", "仅监控，暂不写入正文"]), _slide_text(slides, 6))
    _check(checks, "distractor_non_updates", "distractor_archive_alias_not_rewritten_to_current", not _contains(slide10_text, "北岸书屋合作点确认 6月30日") and _contains(slide10_text, "不同于当前晨光中心"), slide10_text)
    header_dump_terms = ["记录号", "事项编号", "当前口径/状态", "原始日期写法", "日期展示建议", "版本口径", "材料范围", "同步到的材料页"]
    _check(checks, "distractor_non_updates", "workbook_raw_sheet_headers_not_dumped", sum(1 for term in header_dump_terms if _contains(all_text, term)) <= 2, {"present_headers": [term for term in header_dump_terms if _contains(all_text, term)]})

    cjk_count = len(re.findall(r"[一-鿿]", all_text))
    latin_count = len(re.findall(r"[A-Za-z]", all_text))
    _check(checks, "file_integrity", "chinese_text_dominant", cjk_count > latin_count * 3, {"cjk_count": cjk_count, "latin_count": latin_count})
    _check(checks, "file_integrity", "no_external_relationships", not _summary_has_hits(pptx["external_relationships"]), pptx["external_relationships"])
    _check(checks, "file_integrity", "no_external_url_or_file_uri", not _summary_has_hits(pptx["xml_bad_urls"]), pptx["xml_bad_urls"])
    private_summary = _redacted_pattern_summary(xml_text_by_part, PRIVATE_PATTERN_SPECS, placeholder="<redacted-private-marker>")
    secret_summary = _redacted_pattern_summary(xml_text_by_part, SECRET_PATTERN_SPECS, placeholder="<redacted-secret-like-string>")
    _check(checks, "file_integrity", "no_private_paths_or_source_locators", not _summary_has_hits(private_summary), private_summary)
    _check(checks, "file_integrity", "no_secret_like_strings", not _summary_has_hits(secret_summary), secret_summary)
    forbidden_claims = gold.get("safety_contract", {}).get("forbidden_dependency_claims", [])
    forbidden_summary = _forbidden_claim_summary(all_text, forbidden_claims)
    _check(checks, "file_integrity", "no_forbidden_dependency_claims", not _summary_has_hits(forbidden_summary), forbidden_summary)

    result = _build_result(checks, gold)
    if verifier_logs is not None:
        manifest = _write_verifier_artifacts(candidate, pptx, workbook, result, Path(verifier_logs), case_dir, gold)
        result = {**result, "artifact_manifest": manifest}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic verifier for board_material_update_timeline_excel PPTX output.")
    parser.add_argument("output_path", nargs="?", help="Output PPTX file or directory. Defaults to case output/ discovery.")
    parser.add_argument("--case-dir", type=Path, default=CASE_DIR, help="Case root directory.")
    parser.add_argument("--verifier-logs", type=Path, default=None, help="Optional /logs/verifier directory for text-only Judge evidence extraction.")
    args = parser.parse_args()
    result = evaluate(args.output_path, case_dir=args.case_dir, verifier_logs=args.verifier_logs)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
