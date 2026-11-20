"""文本报表：销售、费用、工时三种汇总。"""

from dataclasses import dataclass
from typing import Callable, Optional


def parse_amount(text):
    """解析金额文本：支持 "$1,234.50" 与会计式负数 "(12.00)"。"""
    text = text.strip()
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    value = float(text.replace("$", "").replace(",", ""))
    return -value if negative else value


def group_totals(records, key, value, parse=parse_amount):
    """按 key 字段分组，对 value 字段经 parse 解析后求和。"""
    totals = {}
    for record in records:
        group = record[key]
        totals[group] = totals.get(group, 0.0) + parse(record[value])
    return totals


@dataclass
class ReportSpec:
    title: str
    key: str
    value: str
    parse: Callable = parse_amount
    number_format: str = "{:,.2f}"
    record_filter: Optional[Callable] = None


def format_report(title, totals, number_format="{:,.2f}"):
    """把分组合计渲染为带标题、分隔线与 TOTAL 行的文本表格。"""
    names = sorted(totals)
    total = sum(totals.values())
    amounts = [number_format.format(totals[name]) for name in names]
    total_text = number_format.format(total)
    name_width = max([len(name) for name in names] + [len("TOTAL")])
    amount_width = max(len(text) for text in amounts + [total_text])
    lines = [title, "=" * len(title)]
    for name, text in zip(names, amounts):
        lines.append(name.ljust(name_width) + "  " + text.rjust(amount_width))
    lines.append("-" * (name_width + 2 + amount_width))
    lines.append("TOTAL".ljust(name_width) + "  " + total_text.rjust(amount_width))
    return "\n".join(lines)


def build_report(records, spec):
    """按 spec 过滤、汇总并渲染报表。"""
    if spec.record_filter is not None:
        records = [record for record in records if spec.record_filter(record)]
    totals = group_totals(records, spec.key, spec.value, spec.parse)
    return format_report(spec.title, totals, spec.number_format)


SALES = ReportSpec("Sales Report", "region", "amount")
EXPENSES = ReportSpec("Expense Report", "category", "cost",
                      record_filter=lambda record: record.get("approved", True))
HOURS = ReportSpec("Hours Report", "employee", "hours", parse=float, number_format="{:.1f}")


def sales_report(records):
    return build_report(records, SALES)


def expense_report(records):
    return build_report(records, EXPENSES)


def hours_report(records):
    return build_report(records, HOURS)
