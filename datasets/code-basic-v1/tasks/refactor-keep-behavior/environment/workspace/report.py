"""文本报表：销售、费用、工时三种汇总。"""


def sales_report(records):
    totals = {}
    for r in records:
        text = r["amount"].strip()
        negative = False
        if text.startswith("(") and text.endswith(")"):
            negative = True
            text = text[1:-1]
        text = text.replace("$", "").replace(",", "")
        value = float(text)
        if negative:
            value = -value
        key = r["region"]
        totals[key] = totals.get(key, 0.0) + value
    lines = ["Sales Report", "=" * len("Sales Report")]
    names = sorted(totals)
    total = sum(totals.values())
    name_width = max([len(n) for n in names] + [len("TOTAL")])
    amounts = ["{:,.2f}".format(totals[n]) for n in names] + ["{:,.2f}".format(total)]
    amount_width = max(len(a) for a in amounts)
    for n in names:
        lines.append(n.ljust(name_width) + "  " + "{:,.2f}".format(totals[n]).rjust(amount_width))
    lines.append("-" * (name_width + 2 + amount_width))
    lines.append("TOTAL".ljust(name_width) + "  " + "{:,.2f}".format(total).rjust(amount_width))
    return "\n".join(lines)


def expense_report(records):
    totals = {}
    for r in records:
        if not r.get("approved", True):
            continue
        text = r["cost"].strip()
        negative = False
        if text.startswith("(") and text.endswith(")"):
            negative = True
            text = text[1:-1]
        text = text.replace("$", "").replace(",", "")
        value = float(text)
        if negative:
            value = -value
        key = r["category"]
        totals[key] = totals.get(key, 0.0) + value
    lines = ["Expense Report", "=" * len("Expense Report")]
    names = sorted(totals)
    total = sum(totals.values())
    name_width = max([len(n) for n in names] + [len("TOTAL")])
    amounts = ["{:,.2f}".format(totals[n]) for n in names] + ["{:,.2f}".format(total)]
    amount_width = max(len(a) for a in amounts)
    for n in names:
        lines.append(n.ljust(name_width) + "  " + "{:,.2f}".format(totals[n]).rjust(amount_width))
    lines.append("-" * (name_width + 2 + amount_width))
    lines.append("TOTAL".ljust(name_width) + "  " + "{:,.2f}".format(total).rjust(amount_width))
    return "\n".join(lines)


def hours_report(records):
    totals = {}
    for r in records:
        value = float(r["hours"])
        key = r["employee"]
        totals[key] = totals.get(key, 0.0) + value
    lines = ["Hours Report", "=" * len("Hours Report")]
    names = sorted(totals)
    total = sum(totals.values())
    name_width = max([len(n) for n in names] + [len("TOTAL")])
    amounts = ["{:.1f}".format(totals[n]) for n in names] + ["{:.1f}".format(total)]
    amount_width = max(len(a) for a in amounts)
    for n in names:
        lines.append(n.ljust(name_width) + "  " + "{:.1f}".format(totals[n]).rjust(amount_width))
    lines.append("-" * (name_width + 2 + amount_width))
    lines.append("TOTAL".ljust(name_width) + "  " + "{:.1f}".format(total).rjust(amount_width))
    return "\n".join(lines)
