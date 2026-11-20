`/workspace/report.py` 里有三个报表函数 `sales_report`、`expense_report`、`hours_report`，它们的实现几乎是复制粘贴，重复代码很多。请重构这个模块，让结构更清晰，同时保持三个函数的输出完全不变。`/workspace/tests/test_report.py` 记录了当前行为。

## 结构要求

在 `report.py` 中提供以下名称，并让三个报表函数通过它们实现：

- `parse_amount(text) -> float`：解析金额文本，支持 `"$1,234.50"` 与会计式负数 `"(12.00)"`。
- `group_totals(records, key, value, parse=parse_amount) -> dict`：按 `key` 字段分组，对 `value` 字段先经 `parse` 解析再求和，返回「分组 -> 合计」字典。
- `format_report(title, totals, number_format="{:,.2f}") -> str`：把分组合计渲染为文本表格（标题、分隔线、按分组名排序的各行、TOTAL 行），格式与现有输出一致。
- `ReportSpec`：描述一种报表的类，构造时接受关键字参数 `title`、`key`、`value`，以及可选的 `parse`（默认 `parse_amount`）、`number_format`（默认 `"{:,.2f}"`）、`record_filter`（默认 `None`；不为 `None` 时只保留返回真值的记录）。
- `build_report(records, spec) -> str`：按 `ReportSpec` 过滤、汇总并渲染。
- `sales_report`、`expense_report`、`hours_report` 保留原名与原签名，函数体各自只做一次对 `build_report` 的调用（函数体不超过 3 条语句）。

另外：`report.py` 中任何函数的长度（含定义行）不得超过 25 行；金额文本的清理逻辑（去掉 `$` 与 `,`）只能出现在一个位置。

## 验收

运行 `cd /workspace && python -m pytest tests -q` 应全部通过；隐藏测试还会检查行为不变与上述结构要求。
