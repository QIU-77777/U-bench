#!/usr/bin/env python3
"""
eval.py — case_channel_period_compare_L4_017 评分脚本 (v2: binary pass/fail)

用法: python eval.py <agent_output_xlsx_path>

设计: 等权 binary pass/fail, 18 个原子检查.
"""

import json
import sys
from pathlib import Path

import openpyxl


def load_gold():
    gold_path = Path("/tests/gold/gold_answer.json")
    with open(gold_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Column aliases (EN → CN mapping) ──

_SETTLE_COL_ALIASES = {
    "channel": ["渠道", "渠道商", "渠道名称", "CHANNEL_NAME", "channel", "channel_name",
                 "Channel", "Channel Name"],
    "gmv_25q4": ["GMV_25Q4", "gmv_25q4", "GMV_Q4", "25Q4_GMV", "25Q4 GMV",
                  "GMV(25Q4)", "25年Q4_GMV", "25年Q4 GMV", "25Q4GMV"],
    "gmv_26q1": ["GMV_26Q1", "gmv_26q1", "GMV_Q1", "26Q1_GMV", "26Q1 GMV",
                  "GMV(26Q1)", "26年Q1_GMV", "26年Q1 GMV", "26Q1GMV"],
    "gmv_change": ["GMV变化", "GMV_变化", "GMV差异", "GMV_change", "GMV变化量",
                    "GMV_diff", "GMV差值", "gmv_change", "GMV增减"],
    "revenue_25q4": ["营收_25Q4", "revenue_25q4", "Revenue_25Q4", "25Q4_营收",
                      "25Q4 营收", "25年Q4_营收", "25年Q4 营收", "25Q4营收"],
    "revenue_26q1": ["营收_26Q1", "revenue_26q1", "Revenue_26Q1", "26Q1_营收",
                      "26Q1 营收", "26年Q1_营收", "26年Q1 营收", "26Q1营收"],
    "revenue_change": ["营收变化", "营收_变化", "Revenue_change", "营收差异",
                        "revenue_change", "营收变化量", "营收增减"],
    "comm_rate_25q4": ["佣金率_25Q4", "comm_rate_25q4", "CommRate_25Q4",
                        "25Q4_佣金率", "25Q4 佣金率", "25年Q4_佣金率",
                        "佣金率(25Q4)", "25Q4佣金率", "Commission_Rate_25Q4"],
    "comm_rate_26q1": ["佣金率_26Q1", "comm_rate_26q1", "CommRate_26Q1",
                        "26Q1_佣金率", "26Q1 佣金率", "26年Q1_佣金率",
                        "佣金率(26Q1)", "26Q1佣金率", "Commission_Rate_26Q1"],
    "comm_rate_change": ["佣金率变化", "佣金率_变化", "CommRate_change",
                          "comm_rate_change", "佣金率差异", "佣金率增减"],
    "order_25q4": ["订单量_25Q4", "order_count_25q4", "OrderCount_25Q4",
                    "25Q4_订单量", "25Q4 订单量", "25年Q4_订单量",
                    "订单量(25Q4)", "25Q4订单量", "ORDER_COUNT_25Q4", "订单数_25Q4"],
    "order_26q1": ["订单量_26Q1", "order_count_26q1", "OrderCount_26Q1",
                    "26Q1_订单量", "26Q1 订单量", "26年Q1_订单量",
                    "订单量(26Q1)", "26Q1订单量", "ORDER_COUNT_26Q1", "订单数_26Q1"],
    "order_change": ["订单量变化", "订单量_变化", "OrderCount_change",
                      "order_count_change", "订单量差异", "订单量增减", "订单数变化"],
}

_PAY_COL_ALIASES = {
    "channel": ["渠道", "渠道商", "渠道名称", "CHANNEL_NAME", "channel", "channel_name",
                 "Channel", "Channel Name"],
    "gmv_25q1": ["GMV_25Q1", "gmv_25q1", "25Q1_GMV", "25Q1 GMV",
                  "GMV(25Q1)", "25年Q1_GMV", "25年Q1 GMV", "25Q1GMV"],
    "gmv_26q1": ["GMV_26Q1", "gmv_26q1", "26Q1_GMV", "26Q1 GMV",
                  "GMV(26Q1)", "26年Q1_GMV", "26年Q1 GMV", "26Q1GMV"],
    "gmv_change": ["GMV变化", "GMV_变化", "GMV差异", "GMV_change", "GMV变化量",
                    "GMV_diff", "GMV差值", "gmv_change", "GMV增减"],
    "revenue_25q1": ["营收_25Q1", "revenue_25q1", "Revenue_25Q1", "25Q1_营收",
                      "25Q1 营收", "25年Q1_营收", "25年Q1 营收", "25Q1营收"],
    "revenue_26q1": ["营收_26Q1", "revenue_26q1", "Revenue_26Q1", "26Q1_营收",
                      "26Q1 营收", "26年Q1_营收", "26年Q1 营收", "26Q1营收"],
    "revenue_change": ["营收变化", "营收_变化", "Revenue_change", "营收差异",
                        "revenue_change", "营收变化量", "营收增减"],
    "b_rev_25q1": ["B端收益_25Q1", "b_revenue_25q1", "B_Revenue_25Q1",
                    "25Q1_B端收益", "25Q1 B端收益", "25年Q1_B端收益",
                    "B端收益(25Q1)", "25Q1B端收益", "B端收益汇总_25Q1",
                    "PLATFORM_FEE+SERVICE_FEE_25Q1", "平台费+服务费_25Q1"],
    "b_rev_26q1": ["B端收益_26Q1", "b_revenue_26q1", "B_Revenue_26Q1",
                    "26Q1_B端收益", "26Q1 B端收益", "26年Q1_B端收益",
                    "B端收益(26Q1)", "26Q1B端收益", "B端收益汇总_26Q1",
                    "PLATFORM_FEE+SERVICE_FEE_26Q1", "平台费+服务费_26Q1"],
    "b_rev_change": ["B端收益变化", "B端收益_变化", "B_Revenue_change",
                      "b_revenue_change", "B端收益差异", "B端收益增减"],
    "hc_25q1": ["人数_25Q1", "headcount_25q1", "Headcount_25Q1",
                 "25Q1_人数", "25Q1 人数", "25年Q1_人数",
                 "人数(25Q1)", "25Q1人数", "HEADCOUNT_25Q1"],
    "hc_26q1": ["人数_26Q1", "headcount_26q1", "Headcount_26Q1",
                 "26Q1_人数", "26Q1 人数", "26年Q1_人数",
                 "人数(26Q1)", "26Q1人数", "HEADCOUNT_26Q1"],
    "hc_change": ["人数变化", "人数_变化", "Headcount_change",
                   "headcount_change", "人数差异", "人数增减"],
}


def _to_float(val):
    """Safely convert to float."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        s = str(val).strip().replace(",", "").replace(" ", "")
        if s.endswith("%"):
            return float(s[:-1]) / 100.0
        return float(s)
    except (ValueError, TypeError):
        return None


def _to_int(val):
    """Safely convert to int."""
    f = _to_float(val)
    if f is None:
        return None
    return int(round(f))


def _find_column(headers, key, alias_map):
    """Find column in headers using alias list for key."""
    candidates = alias_map.get(key, [key])
    headers_lower = [h.lower().strip() for h in headers]
    # Exact match first
    for cand in candidates:
        cand_lower = cand.lower().strip()
        for idx, h in enumerate(headers_lower):
            if cand_lower == h:
                return headers[idx]
    # Substring match fallback
    for cand in candidates:
        cand_lower = cand.lower().strip()
        for idx, h in enumerate(headers_lower):
            if len(cand_lower) >= 3 and (cand_lower in h or h in cand_lower):
                return headers[idx]
    return None


def _read_sheet(ws):
    """Read a worksheet into (headers, rows_as_dicts)."""
    rows_iter = ws.iter_rows(values_only=True)
    headers_raw = next(rows_iter, None)
    if not headers_raw:
        return [], []
    headers = [str(h).strip() if h else "" for h in headers_raw]
    data_rows = []
    for row in rows_iter:
        row_dict = {}
        for idx, val in enumerate(row):
            if idx < len(headers):
                row_dict[headers[idx]] = val
        # Skip completely empty rows
        if any(v is not None and str(v).strip() != "" for v in row):
            data_rows.append(row_dict)
    return headers, data_rows


def _jaccard_iou(set_a, set_b):
    """Compute Jaccard IoU between two sets."""
    if not set_a and not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def _match_sheets(wb, gold):
    """Match sheets to settlement/payment using IoU content matching."""
    gold_channels = set(gold["channels"])

    # For settlement sheet: look for 25Q4/26Q1 pattern in headers or content
    # For payment sheet: look for 25Q1/26Q1 pattern in headers or content
    best_settle = None
    best_settle_score = -1
    best_pay = None
    best_pay_score = -1

    for ws in wb.worksheets:
        headers, data_rows = _read_sheet(ws)
        if not headers or not data_rows:
            continue

        headers_str = " ".join(headers).lower()
        # Collect all text in the sheet for pattern matching
        all_text = headers_str

        # Check channel coverage
        ch_col = None
        for h in headers:
            h_lower = h.lower().strip()
            if h_lower in ["渠道", "渠道商", "渠道名称", "channel_name", "channel"]:
                ch_col = h
                break
        if not ch_col:
            # Try first column as channel
            ch_col = headers[0] if headers else None

        found_channels = set()
        if ch_col:
            for row in data_rows:
                val = str(row.get(ch_col, "")).strip()
                if val in gold_channels:
                    found_channels.add(val)

        channel_iou = _jaccard_iou(found_channels, gold_channels)

        # Determine if this looks more like settlement or payment
        # Settlement has 25Q4, payment has 25Q1
        is_settle = ("25q4" in all_text or "q4" in all_text or
                     "结算" in all_text or "佣金" in all_text or
                     "订单" in all_text or "commission" in all_text.lower())
        is_pay = ("b端" in all_text or "回款" in all_text or
                  "平台费" in all_text or "服务费" in all_text or
                  "人数" in all_text or "headcount" in all_text.lower())

        # If headers mention both Q4 terms → likely settlement
        # If headers mention 25Q1 terms → likely payment
        has_q4_header = any("q4" in h.lower() or "Q4" in h for h in headers)
        has_25q1_header = any(("25q1" in h.lower() or "25Q1" in h) for h in headers)

        settle_score = channel_iou
        if is_settle or has_q4_header:
            settle_score += 1.0
        if is_pay:
            settle_score -= 0.5

        pay_score = channel_iou
        if is_pay or has_25q1_header:
            pay_score += 1.0
        if is_settle and not is_pay:
            pay_score -= 0.5

        if settle_score > best_settle_score:
            best_settle_score = settle_score
            best_settle = ws

        if pay_score > best_pay_score:
            best_pay_score = pay_score
            best_pay = ws

    # If both matched the same sheet, try to differentiate
    if best_settle is not None and best_pay is not None and best_settle == best_pay:
        # Assign by sheet order, using heuristics
        sheets = list(wb.worksheets)
        if len(sheets) >= 2:
            # Re-evaluate: pick best unique assignment
            scores = []
            for ws in sheets:
                headers, _ = _read_sheet(ws)
                hstr = " ".join(headers).lower()
                s_score = 0
                p_score = 0
                if "q4" in hstr or "佣金" in hstr or "结算" in hstr or "订单" in hstr:
                    s_score += 1
                if "b端" in hstr or "回款" in hstr or "人数" in hstr or "平台" in hstr or "服务" in hstr:
                    p_score += 1
                scores.append((ws, s_score, p_score))

            # Greedy assignment
            scores.sort(key=lambda x: x[1], reverse=True)
            best_settle = scores[0][0]
            remaining = [s for s in scores if s[0] != best_settle]
            if remaining:
                remaining.sort(key=lambda x: x[2], reverse=True)
                best_pay = remaining[0][0]
            else:
                best_pay = None

    return best_settle, best_pay


def _match_rows_by_channel(data_rows, headers, gold_channels, alias_map):
    """Match agent rows to gold channels by channel name."""
    ch_col = _find_column(headers, "channel", alias_map)
    if not ch_col:
        return {}
    matched = {}
    for row in data_rows:
        ch_val = str(row.get(ch_col, "")).strip()
        if ch_val in gold_channels:
            matched[ch_val] = row
    return matched


def _check_val(agent_val, gold_val, rel_tol=0.01, abs_tol=0.5):
    """Check if agent value matches gold within tolerance."""
    if agent_val is None or gold_val is None:
        return False
    if gold_val == 0:
        return abs(agent_val) < abs_tol
    return abs(agent_val - gold_val) / abs(gold_val) <= rel_tol or abs(agent_val - gold_val) < abs_tol


def evaluate(output_path: str) -> dict:
    gold = load_gold()
    checks = []

    output_file = Path(output_path)
    if not output_file.exists():
        checks.append({"name": "output_is_valid_xlsx", "passed": False,
                       "detail": f"文件不存在: {output_path}"})
        return _build_result(checks, 22)

    try:
        wb = openpyxl.load_workbook(str(output_file), data_only=True)
    except Exception as e:
        checks.append({"name": "output_is_valid_xlsx", "passed": False,
                       "detail": f"无法读取: {e}"})
        return _build_result(checks, 22)

    # ── Check 1: output_is_valid_xlsx ──
    checks.append({"name": "output_is_valid_xlsx", "passed": True,
                   "detail": f"文件有效, {len(wb.sheetnames)} sheets"})

    # ── Check 2: has_2_sheets ──
    has_2 = len(wb.sheetnames) >= 2
    checks.append({"name": "has_2_sheets", "passed": has_2,
                   "detail": f"sheets={wb.sheetnames}"})

    # Match sheets to settlement/payment
    settle_ws, pay_ws = _match_sheets(wb, gold)

    gold_channels = set(gold["channels"])
    spot_chs = gold["spot_channels"]
    gold_settle_by_ch = {g["channel"]: g for g in gold["settlement_dimension"]}
    gold_pay_by_ch = {g["channel"]: g for g in gold["payment_dimension"]}

    # ── Settlement sheet checks ──
    if settle_ws is not None:
        s_headers, s_rows = _read_sheet(settle_ws)
        s_matched = _match_rows_by_channel(s_rows, s_headers, gold_channels, _SETTLE_COL_ALIASES)
    else:
        s_headers, s_rows, s_matched = [], [], {}

    # ── Check 3: settlement_sheet_has_all_channels ──
    checks.append({
        "name": "settlement_sheet_has_all_channels",
        "passed": len(s_matched) >= 20,
        "detail": f"匹配渠道数={len(s_matched)}/20"
    })

    # ── Payment sheet checks ──
    if pay_ws is not None:
        p_headers, p_rows = _read_sheet(pay_ws)
        p_matched = _match_rows_by_channel(p_rows, p_headers, gold_channels, _PAY_COL_ALIASES)
    else:
        p_headers, p_rows, p_matched = [], [], {}

    # ── Check 4: payment_sheet_has_all_channels ──
    checks.append({
        "name": "payment_sheet_has_all_channels",
        "passed": len(p_matched) >= 20,
        "detail": f"匹配渠道数={len(p_matched)}/20"
    })

    # ── Settlement spot checks (5 metrics × 2 channels = 10) ──
    for i, ch in enumerate(spot_chs):
        gold_s = gold_settle_by_ch[ch]
        agent_row = s_matched.get(ch, {})

        # GMV 26Q1
        col = _find_column(s_headers, "gmv_26q1", _SETTLE_COL_ALIASES)
        agent_v = _to_float(agent_row.get(col)) if col and agent_row else None
        gold_v = gold_s["gmv_26q1"]
        passed = agent_v is not None and _check_val(agent_v, gold_v)
        checks.append({
            "name": f"settlement_gmv_26q1_spot_ch{i+1}",
            "passed": passed,
            "detail": f"{ch}: agent={agent_v}, gold={gold_v}"
        })

        # GMV change
        col = _find_column(s_headers, "gmv_change", _SETTLE_COL_ALIASES)
        agent_v = _to_float(agent_row.get(col)) if col and agent_row else None
        gold_v = gold_s["gmv_change"]
        passed = agent_v is not None and _check_val(agent_v, gold_v)
        checks.append({
            "name": f"settlement_gmv_change_spot_ch{i+1}",
            "passed": passed,
            "detail": f"{ch}: agent={agent_v}, gold={gold_v}"
        })

        # Revenue 26Q1 (newly added per review P1)
        col = _find_column(s_headers, "revenue_26q1", _SETTLE_COL_ALIASES)
        agent_v = _to_float(agent_row.get(col)) if col and agent_row else None
        gold_v = gold_s["revenue_26q1"]
        passed = agent_v is not None and _check_val(agent_v, gold_v)
        checks.append({
            "name": f"settlement_revenue_26q1_spot_ch{i+1}",
            "passed": passed,
            "detail": f"{ch}: agent={agent_v}, gold={gold_v}"
        })

        # Commission rate (either quarter, check 26Q1)
        col = _find_column(s_headers, "comm_rate_26q1", _SETTLE_COL_ALIASES)
        agent_v = _to_float(agent_row.get(col)) if col and agent_row else None
        gold_v = gold_s["comm_rate_26q1"]
        passed = agent_v is not None and abs(agent_v - gold_v) < 0.005
        checks.append({
            "name": f"settlement_commission_rate_spot_ch{i+1}",
            "passed": passed,
            "detail": f"{ch}: agent={agent_v}, gold={gold_v}"
        })

        # Order count (26Q1)
        col = _find_column(s_headers, "order_26q1", _SETTLE_COL_ALIASES)
        agent_v = _to_int(agent_row.get(col)) if col and agent_row else None
        gold_v = gold_s["order_count_26q1"]
        passed = agent_v is not None and agent_v == gold_v
        checks.append({
            "name": f"settlement_order_count_spot_ch{i+1}",
            "passed": passed,
            "detail": f"{ch}: agent={agent_v}, gold={gold_v}"
        })

    # ── Payment spot checks (4 metrics × 2 channels = 8) ──
    for i, ch in enumerate(spot_chs):
        gold_p = gold_pay_by_ch[ch]
        agent_row = p_matched.get(ch, {})

        # GMV 26Q1
        col = _find_column(p_headers, "gmv_26q1", _PAY_COL_ALIASES)
        agent_v = _to_float(agent_row.get(col)) if col and agent_row else None
        gold_v = gold_p["gmv_26q1"]
        passed = agent_v is not None and _check_val(agent_v, gold_v)
        checks.append({
            "name": f"payment_gmv_spot_ch{i+1}",
            "passed": passed,
            "detail": f"{ch}: agent={agent_v}, gold={gold_v}"
        })

        # Revenue 26Q1 (newly added per review P1)
        col = _find_column(p_headers, "revenue_26q1", _PAY_COL_ALIASES)
        agent_v = _to_float(agent_row.get(col)) if col and agent_row else None
        gold_v = gold_p["revenue_26q1"]
        passed = agent_v is not None and _check_val(agent_v, gold_v)
        checks.append({
            "name": f"payment_revenue_26q1_spot_ch{i+1}",
            "passed": passed,
            "detail": f"{ch}: agent={agent_v}, gold={gold_v}"
        })

        # B端收益 26Q1
        col = _find_column(p_headers, "b_rev_26q1", _PAY_COL_ALIASES)
        agent_v = _to_float(agent_row.get(col)) if col and agent_row else None
        gold_v = gold_p["b_revenue_26q1"]
        passed = agent_v is not None and _check_val(agent_v, gold_v)
        checks.append({
            "name": f"payment_b_revenue_spot_ch{i+1}",
            "passed": passed,
            "detail": f"{ch}: agent={agent_v}, gold={gold_v}"
        })

        # Headcount 26Q1
        col = _find_column(p_headers, "hc_26q1", _PAY_COL_ALIASES)
        agent_v = _to_int(agent_row.get(col)) if col and agent_row else None
        gold_v = gold_p["headcount_26q1"]
        passed = agent_v is not None and agent_v == gold_v
        checks.append({
            "name": f"payment_headcount_spot_ch{i+1}",
            "passed": passed,
            "detail": f"{ch}: agent={agent_v}, gold={gold_v}"
        })

    return _build_result(checks, 22)


def _build_result(checks, expected_total=22):
    # Pad with failed checks if we short-circuited
    passed_count = sum(1 for c in checks if c["passed"])
    total_count = len(checks)
    return {
        "passed_count": passed_count,
        "total_count": total_count,
        "pass_rate": round(passed_count / total_count, 4) if total_count > 0 else 0,
        "checks": checks,
    }


def main():
    if len(sys.argv) < 2:
        print("用法: python eval.py <agent_output_xlsx_path>")
        sys.exit(1)

    output_path = sys.argv[1]
    result = evaluate(output_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["pass_rate"] >= 0.5 else 1)


if __name__ == "__main__":
    main()
