import sys
from collections import OrderedDict
from pathlib import Path

import openpyxl
from openpyxl.styles import Font


def load_rows(path):
    ws = openpyxl.load_workbook(path, data_only=True).worksheets[0]
    it = ws.iter_rows(values_only=True)
    header = list(next(it))
    rows, seen = [], set()
    for row in it:
        if all(v is None for v in row):
            continue
        rec = dict(zip(header, row))
        if rec["QUARTER"] is None or str(rec["QUARTER"]).strip() == "":
            continue
        key = tuple(row)
        if key in seen:
            continue
        seen.add(key)
        rec["QUARTER"] = str(rec["QUARTER"]).strip()
        rows.append(rec)
    return rows


def aggregate(rows, quarters, fields):
    agg = OrderedDict()
    for r in rows:
        if r["QUARTER"] not in quarters:
            continue
        ch = str(r["CHANNEL_NAME"]).strip()
        d = agg.setdefault(ch, {q: {f: 0.0 for f in fields} for q in quarters})
        for f in fields:
            d[r["QUARTER"]][f] += float(r[f] or 0)
    return agg


def main(in_dir, out_path):
    in_dir = Path(in_dir)
    settle = load_rows(in_dir / "渠道结算明细.xlsx")
    pay = load_rows(in_dir / "渠道回款明细.xlsx")
    for r in pay:
        r["B_REV"] = float(r["PLATFORM_FEE"] or 0) + float(r["SERVICE_FEE"] or 0)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "结算对比"
    ws.append(["渠道", "GMV_25Q4", "GMV_26Q1", "GMV变化", "营收_25Q4", "营收_26Q1", "营收变化",
               "佣金率_25Q4", "佣金率_26Q1", "佣金率变化", "订单量_25Q4", "订单量_26Q1", "订单量变化"])
    qs = ("25Q4", "26Q1")
    agg = aggregate(settle, qs, ["GMV", "REVENUE", "COMMISSION", "ORDER_COUNT"])
    for ch in sorted(agg):
        a, b = agg[ch]["25Q4"], agg[ch]["26Q1"]
        ra = a["COMMISSION"] / a["GMV"] if a["GMV"] else 0
        rb = b["COMMISSION"] / b["GMV"] if b["GMV"] else 0
        ws.append([ch, round(a["GMV"], 2), round(b["GMV"], 2), round(b["GMV"] - a["GMV"], 2),
                   round(a["REVENUE"], 2), round(b["REVENUE"], 2), round(b["REVENUE"] - a["REVENUE"], 2),
                   round(ra, 4), round(rb, 4), round(rb - ra, 4),
                   int(a["ORDER_COUNT"]), int(b["ORDER_COUNT"]), int(b["ORDER_COUNT"] - a["ORDER_COUNT"])])

    ws2 = wb.create_sheet("回款对比")
    ws2.append(["渠道", "GMV_25Q1", "GMV_26Q1", "GMV变化", "营收_25Q1", "营收_26Q1", "营收变化",
                "B端收益_25Q1", "B端收益_26Q1", "B端收益变化", "人数_25Q1", "人数_26Q1", "人数变化"])
    qs = ("25Q1", "26Q1")
    agg = aggregate(pay, qs, ["GMV", "REVENUE", "B_REV", "HEADCOUNT"])
    for ch in sorted(agg):
        a, b = agg[ch]["25Q1"], agg[ch]["26Q1"]
        ws2.append([ch, round(a["GMV"], 2), round(b["GMV"], 2), round(b["GMV"] - a["GMV"], 2),
                    round(a["REVENUE"], 2), round(b["REVENUE"], 2), round(b["REVENUE"] - a["REVENUE"], 2),
                    round(a["B_REV"], 2), round(b["B_REV"], 2), round(b["B_REV"] - a["B_REV"], 2),
                    int(a["HEADCOUNT"]), int(b["HEADCOUNT"]), int(b["HEADCOUNT"] - a["HEADCOUNT"])])

    for sheet in wb.worksheets:
        for c in sheet[1]:
            c.font = Font(bold=True)
        sheet.column_dimensions["A"].width = 18
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
