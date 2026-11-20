在 `/workspace` 下实现命令行工具 `csvagg.py`（仅使用 Python 标准库），读取 CSV 文件，按某一列分组，对另一列做聚合，并以 JSON 输出结果。`/workspace/sample.csv` 是示例数据。

## 调用方式

```
python csvagg.py <csv_path> --group-by <列名> --value <列名> --op {sum,avg,min,max,count}
```

## 输出

成功时在标准输出打印一个 JSON 对象，退出码为 0：

```json
{"op": "sum", "group_by": "region", "value": "units", "groups": {"East": 13, "North": null, "West": 9}}
```

- `groups` 的键按字典序（字符串升序）排列，键为分组列的原始文本，空文本也是合法的键。
- `sum`、`avg`、`min`、`max` 的结果为数字，`avg` 与其他非整数结果保留 2 位小数（四舍五入）；`count` 的结果为整数。
- `count` 统计该组的行数，不要求 `--value` 列有值，也不解析它的内容。
- 其余操作忽略该组中 `--value` 列为空（去除空白后为空串）的单元格；如果某组所有单元格都为空，该组的值为 `null`。
- 数值单元格按浮点数解析，允许首尾空白。
- CSV 按标准 CSV 规则解析（支持带引号、含逗号和换行的字段），文件编码为 UTF-8，可能带 BOM。
- 只有表头没有数据行时，`groups` 为 `{}`。

## 错误处理

出错时标准输出不得有内容，在标准错误输出一行以 `error:` 开头的说明：

- 命令行参数不合法（缺少必需参数、`--op` 不在给定取值内）：退出码 2。
- 文件不存在或无法读取、文件为空（没有表头）、`--group-by` 或 `--value` 指定的列不存在、非 `count` 操作遇到无法解析为数字的非空单元格：退出码 1。

## 验收

隐藏测试会通过子进程调用 `python /workspace/csvagg.py ...` 检查输出与退出码。
