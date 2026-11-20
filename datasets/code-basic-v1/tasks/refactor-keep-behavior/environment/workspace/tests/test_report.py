from report import expense_report, hours_report, sales_report


def test_sales_report():
    records = [
        {"region": "West", "amount": "$1,200.50"},
        {"region": "East", "amount": "300"},
        {"region": "West", "amount": "(200.00)"},
    ]
    assert sales_report(records) == "\n".join([
        "Sales Report",
        "============",
        "East     300.00",
        "West   1,000.50",
        "---------------",
        "TOTAL  1,300.50",
    ])


def test_expense_report_skips_unapproved():
    records = [
        {"category": "Travel", "cost": "$80.00", "approved": True},
        {"category": "Travel", "cost": "$20.00", "approved": False},
        {"category": "Meals", "cost": "15.25"},
    ]
    assert expense_report(records) == "\n".join([
        "Expense Report",
        "==============",
        "Meals   15.25",
        "Travel  80.00",
        "-------------",
        "TOTAL   95.25",
    ])


def test_hours_report():
    records = [
        {"employee": "ann", "hours": 7.5},
        {"employee": "bob", "hours": "8"},
        {"employee": "ann", "hours": 8},
    ]
    assert hours_report(records) == "\n".join([
        "Hours Report",
        "============",
        "ann    15.5",
        "bob     8.0",
        "-----------",
        "TOTAL  23.5",
    ])
