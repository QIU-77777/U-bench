#!/usr/bin/env python3
"""从静态投研资料包生成 analyst_forecast_extract.xlsx 与 .json。"""
from __future__ import annotations

import json
import re
from pathlib import Path

import openpyxl

ROOT = Path("/workspace")
INPUT = ROOT / "input"
OUTPUT = ROOT / "output"
CASE_ID = "case_analyst_forecast_extract_L3_018"

SHEETS = {
    "forecast_fields": ["institution", "report_date", "canonical_company", "fiscal_year",
                        "net_profit_cny_mn", "eps_cny", "source_file", "source_row_or_section"],
    "rating_changes": ["institution", "report_date", "canonical_company", "source_rating_text",
                       "standard_rating", "action_type", "source_file"],
    "target_price_table": ["institution", "report_date", "canonical_company",
                           "target_price_cny_per_share", "target_price_status", "source_file"],
    "missing_fields": ["institution", "report_date", "company_alias", "missing_type",
                       "evidence", "source_file"],
}


def load_inputs():
    wb = openpyxl.load_workbook(INPUT / "company_dictionary.xlsx", data_only=True)
    aliases, canon_of = {}, {}
    for row in list(wb["company_aliases"].iter_rows(values_only=True))[1:]:
        canonical, _code, alias, _type, active = row[:5]
        if str(active).upper() == "Y":
            aliases[alias] = canonical
    scope = {r[0]: r[1] for r in list(wb["task_scope"].iter_rows(values_only=True))[1:]}
    codebook = json.loads((INPUT / "rating_codebook.json").read_text(encoding="utf-8"))
    ratings = {r["source_text"]: r for r in codebook["rating_aliases"]}
    fwb = openpyxl.load_workbook(INPUT / "forecast_tables.xlsx", data_only=True)
    index = {}
    for row in list(fwb["report_index"].iter_rows(values_only=True))[1:]:
        index[Path(row[1]).name] = {"institution": row[2], "report_date": row[3], "source_file": row[1]}
    detail = []
    for excel_row, row in enumerate(fwb["forecast_detail_export"].iter_rows(values_only=True), start=1):
        if excel_row > 1 and row[0] is not None:
            detail.append((excel_row, row))
    return aliases, scope["target_company"], ratings, index, detail


def norm_date(text):
    m = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", str(text))
    return f"{int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}"


def norm_year(text):
    m = re.search(r"(20\d{2})", str(text))
    if m:
        return m[1]
    m = re.fullmatch(r"\s*(\d{2})E?\s*", str(text))
    return f"20{m[1]}" if m else None


def to_number(value):
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def clause(text, keyword):
    for part in re.split(r"[。\n]", text):
        if keyword in part:
            return part.strip("# ").strip()
    return keyword


def main():
    aliases, target, ratings, index, detail = load_inputs()
    ordered = sorted(aliases, key=len, reverse=True)

    def first_alias(text):
        hits = [(text.find(a), a) for a in ordered if a in text]
        return min(hits)[1] if hits else None

    out = {name: [] for name in SHEETS}
    forecast_keys = set()
    summary_files = sorted((INPUT / "broker_summaries").glob("*.md"))
    rollup_date = None

    # 预测明细
    detail_by_report = {}
    for excel_row, row in detail:
        _no, date, institution, _analyst, alias, year, profit, eps, _note = row
        date = norm_date(date)
        detail_by_report.setdefault((institution, date), []).append((excel_row, alias, year, profit, eps))

    for md in summary_files:
        text = md.read_text(encoding="utf-8")
        meta = index.get(md.name)
        rel = f"broker_summaries/{md.name}"
        if meta is None:
            # 滚动统计摘要：机构与日期取自预测明细中无法归一的行
            date = norm_date(md.name)
            institution = next((inst for (inst, d), rows in detail_by_report.items()
                                if d == date and all(r[1] not in aliases for r in rows)), "页面统计区")
            out["missing_fields"].append({
                "institution": institution, "report_date": date, "company_alias": "多公司",
                "missing_type": "aggregate_summary_not_report_row",
                "evidence": clause(text, "滚动统计") if "滚动统计" in text else "滚动统计摘要",
                "source_file": rel,
            })
            continue
        institution, date = meta["institution"], meta["report_date"]
        body = text.split("\n", 1)[1]
        alias = first_alias(body)
        canonical = aliases[alias]
        is_target = canonical == target

        # 目标价
        price = None
        pm = re.search(r"目标价[^。\n\d]{0,12}?(\d+(?:\.\d+)?)\s*元", body)
        if pm:
            price = float(pm[1])
        if not is_target:
            status = "not_target_company"
        elif price is None:
            status = "missing"
        else:
            status = "present"
        row = {"institution": institution, "report_date": date, "canonical_company": canonical,
               "target_price_cny_per_share": price if price is not None else "",
               "target_price_status": status, "source_file": rel}
        if is_target or price is not None:
            out["target_price_table"].append(row)
        if status == "missing":
            out["missing_fields"].append({
                "institution": institution, "report_date": date, "company_alias": alias,
                "missing_type": "missing_target_price", "evidence": clause(body, "目标价"),
                "source_file": rel})
        if not is_target:
            tgt_alias = next(a for a in ordered if aliases[a] == target and a in body)
            out["missing_fields"].append({
                "institution": institution, "report_date": date, "company_alias": alias,
                "missing_type": "non_target_company",
                "evidence": f"报告主体为{alias}，{tgt_alias}仅为同业比较对象",
                "source_file": rel})
            continue

        # 评级：仅映射 codebook 中列出的文本
        changed = re.search(r"由[“\"](.+?)[”\"]调整为[“\"](.+?)[”\"]", body)
        candidates = [f"由{changed[1]}调整为{changed[2]}"] if changed else []
        candidates += re.findall(r"[“\"]([^”\"]+)[”\"]", body)
        for cand in candidates:
            if cand in ratings:
                r = ratings[cand]
                out["rating_changes"].append({
                    "institution": institution, "report_date": date, "canonical_company": canonical,
                    "source_rating_text": cand, "standard_rating": r["standard_rating"],
                    "action_type": r["action_type"], "source_file": rel})
                break
        else:
            out["missing_fields"].append({
                "institution": institution, "report_date": date, "company_alias": alias,
                "missing_type": "rating_not_in_codebook", "evidence": clause(body, "评级"),
                "source_file": rel})

        # 摘要中声明的缺失预测年度
        m = re.search(r"FY(\d{4})\s*未在摘要段披露", body)
        if m:
            out["missing_fields"].append({
                "institution": institution, "report_date": date, "company_alias": alias,
                "missing_type": "missing_forecast_year", "evidence": f"FY{m[1]} 未在摘要段披露",
                "source_file": rel})
        m = re.search(r"((?:20\d{2}E[^，。]{0,3}){2,}数值沿用上一版资料[^。]*)", body)
        if m:
            out["missing_fields"].append({
                "institution": institution, "report_date": date, "company_alias": alias,
                "missing_type": "missing_forecast_year", "evidence": m[1],
                "source_file": rel})

        # 预测明细
        for excel_row, row_alias, year, profit, eps in detail_by_report.get((institution, date), []):
            if aliases.get(row_alias) != target:
                continue
            fy = norm_year(year)
            np_, eps_ = to_number(profit), to_number(eps)
            if np_ is None or eps_ is None:
                out["missing_fields"].append({
                    "institution": institution, "report_date": date, "company_alias": row_alias,
                    "missing_type": "missing_numeric_forecast",
                    "evidence": f"forecast_tables.xlsx forecast_detail_export 第{excel_row - 1}行 {year} "
                                f"归母净利润和 EPS 均为空",
                    "source_file": "forecast_tables.xlsx"})
                continue
            out["forecast_fields"].append({
                "institution": institution, "report_date": date, "canonical_company": canonical,
                "fiscal_year": fy, "net_profit_cny_mn": np_, "eps_cny": eps_,
                "source_file": "forecast_tables.xlsx",
                "source_row_or_section": f"forecast_detail_export!R{excel_row}"})

    for name in out:
        out[name].sort(key=lambda r: (r["report_date"], r["institution"],
                                      str(r.get("fiscal_year", "")), r.get("missing_type", "")))

    OUTPUT.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, cols in SHEETS.items():
        ws = wb.create_sheet(name)
        ws.append(cols)
        for r in out[name]:
            ws.append([r[c] for c in cols])
    wb.save(OUTPUT / "analyst_forecast_extract.xlsx")

    payload = {
        "case_id": CASE_ID,
        "workbook": "analyst_forecast_extract.xlsx",
        "target_company": target,
        "sheet_row_counts": {name: len(rows) for name, rows in out.items()},
        "normalization_contract": {
            "basis": "仅使用工作区内的静态文件，不补猜缺失值",
            "company_matching": "company_dictionary.xlsx 中 active=Y 的 alias 归一到 canonical_company",
            "rating_mapping": "rating_codebook.json 中列出的 source_text，不解释 codebook 外的文字",
            "date_format": "YYYY-MM-DD",
            "fiscal_year_format": "YYYY，26E、FY2026、2026E 均归一为 2026",
            "net_profit_unit": "CNY_mn",
            "eps_unit": "CNY",
            "target_price_unit": "CNY/share",
            "target_price_status_values": ["present", "missing", "not_target_company"],
            "excluded_from_fact_sheets": ["非目标公司", "滚动统计摘要", "页脚与免责声明", "缺失数值的预测行"],
            "inputs": [
                "broker_summaries/*.md", "forecast_tables.xlsx", "rating_codebook.json",
                "company_dictionary.xlsx", "output_schema.json"],
        },
        "row_source_trace": {
            name: [
                {"institution": r["institution"], "report_date": r["report_date"],
                 "source_file": r["source_file"],
                 "location": r.get("source_row_or_section") or r.get("missing_type") or r.get("target_price_status") or r.get("standard_rating")}
                for r in rows
            ] for name, rows in out.items()
        },
    }
    (OUTPUT / "analyst_forecast_extract.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
