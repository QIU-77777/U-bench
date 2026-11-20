import ast
import dataclasses
import random

import pytest

import report
from report import (ReportSpec, build_report, expense_report, format_report, group_totals,
                    hours_report, parse_amount, sales_report)

SOURCE = open(report.__file__, encoding="utf-8").read()
TREE = ast.parse(SOURCE)
FUNCTIONS = {node.name: node for node in ast.walk(TREE) if isinstance(node, ast.FunctionDef)}


def reference(title, totals, fmt):
    names = sorted(totals)
    total = sum(totals.values())
    amounts = [fmt.format(totals[n]) for n in names]
    total_text = fmt.format(total)
    nw = max([len(n) for n in names] + [5])
    aw = max(len(a) for a in amounts + [total_text])
    lines = [title, "=" * len(title)]
    lines += [n.ljust(nw) + "  " + a.rjust(aw) for n, a in zip(names, amounts)]
    lines.append("-" * (nw + 2 + aw))
    lines.append("TOTAL".ljust(nw) + "  " + total_text.rjust(aw))
    return "\n".join(lines)


def money(value):
    return f"${value:,.2f}" if value >= 0 else f"({-value:,.2f})"


def test_sales_golden():
    records = [{"region": "West", "amount": "$1,200.50"}, {"region": "East", "amount": "300"},
               {"region": "West", "amount": "(200.00)"}]
    assert sales_report(records) == (
        "Sales Report\n============\nEast     300.00\nWest   1,000.50\n"
        "---------------\nTOTAL  1,300.50")


def test_expense_golden_and_filter():
    records = [{"category": "Travel", "cost": "$80.00", "approved": True},
               {"category": "Travel", "cost": "$20.00", "approved": False},
               {"category": "Meals", "cost": "15.25"}]
    assert expense_report(records) == (
        "Expense Report\n==============\nMeals   15.25\nTravel  80.00\n"
        "-------------\nTOTAL   95.25")


def test_hours_golden():
    records = [{"employee": "ann", "hours": 7.5}, {"employee": "bob", "hours": "8"},
               {"employee": "ann", "hours": 8}]
    assert hours_report(records) == (
        "Hours Report\n============\nann    15.5\nbob     8.0\n-----------\nTOTAL  23.5")


def test_empty_inputs():
    assert sales_report([]) == "Sales Report\n============\n-----------\nTOTAL  0.00"
    assert hours_report([]) == "Hours Report\n============\n----------\nTOTAL  0.0"
    assert expense_report([{"category": "x", "cost": "1", "approved": False}]) == \
        "Expense Report\n==============\n-----------\nTOTAL  0.00"


def test_randomized_equivalence():
    rng = random.Random(7)
    names = ["North", "South", "East-long-name", "W", "Ünï", ""]
    for _ in range(40):
        rows = [(rng.choice(names), rng.randint(-2_000_000, 5_000_000) / 100) for _ in range(rng.randint(0, 12))]
        sales = [{"region": n, "amount": money(v)} for n, v in rows]
        totals = {}
        for n, v in rows:
            totals[n] = totals.get(n, 0.0) + float(money(v).replace("$", "").replace(",", "")
                                                   .replace("(", "-").replace(")", ""))
        assert sales_report(sales) == reference("Sales Report", totals, "{:,.2f}")
        hours = [{"employee": n, "hours": abs(v) % 40} for n, v in rows]
        htotals = {}
        for r in hours:
            htotals[r["employee"]] = htotals.get(r["employee"], 0.0) + r["hours"]
        assert hours_report(hours) == reference("Hours Report", htotals, "{:.1f}")


def test_parse_amount():
    assert parse_amount("$1,234.50") == 1234.5
    assert parse_amount(" (12.00) ") == -12.0
    assert parse_amount("($1,000.25)") == -1000.25
    assert parse_amount("7") == 7.0
    assert parse_amount("-3.5") == -3.5


def test_group_totals():
    records = [{"k": "a", "v": "$1,000"}, {"k": "b", "v": "(2)"}, {"k": "a", "v": "5"}]
    assert group_totals(records, "k", "v") == {"a": 1005.0, "b": -2.0}
    assert group_totals([{"k": "a", "v": 2}], "k", "v", parse=float) == {"a": 2.0}
    assert group_totals([], "k", "v") == {}



def test_format_report():
    assert format_report("T", {"b": 2.0, "a": 1000.0}) == (
        "T\n=\na      1,000.00\nb          2.00\n---------------\nTOTAL  1,002.00")
    assert format_report("T", {"a": 1.25}, number_format="{:.1f}") == "T\n=\na      1.2\n----------\nTOTAL  1.2"


def test_report_spec_and_build_report():
    assert isinstance(ReportSpec, type)
    spec = ReportSpec(title="Custom", key="who", value="n")
    assert spec.parse is parse_amount
    assert spec.number_format == "{:,.2f}"
    assert spec.record_filter is None
    records = [{"who": "x", "n": "$1,000"}, {"who": "y", "n": "5", "keep": False}]
    assert build_report(records, spec) == reference("Custom", {"x": 1000.0, "y": 5.0}, "{:,.2f}")
    filtered = ReportSpec(title="F", key="who", value="n", record_filter=lambda r: r.get("keep", True))
    assert build_report(records, filtered) == reference("F", {"x": 1000.0}, "{:,.2f}")
    plain = ReportSpec(title="P", key="who", value="n", parse=float, number_format="{:.1f}")
    assert build_report([{"who": "x", "n": 2}], plain) == reference("P", {"x": 2.0}, "{:.1f}")


@pytest.mark.parametrize("name", ["sales_report", "expense_report", "hours_report"])
def test_public_functions_are_thin(name):
    func = FUNCTIONS[name]
    statements = [n for n in ast.walk(func) if isinstance(n, ast.stmt) and n is not func]
    assert len(statements) <= 3
    called = {n.func.id for n in ast.walk(func) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "build_report" in called


def test_function_length_limit():
    for name, func in FUNCTIONS.items():
        assert func.end_lineno - func.lineno + 1 <= 25, name


def test_amount_cleanup_not_duplicated():
    replaces = [n for n in ast.walk(TREE) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "replace"
                and any(isinstance(a, ast.Constant) and a.value in ("$", ",") for a in n.args)]
    assert len(replaces) <= 2
