#!/usr/bin/env python3
"""Read the citrinectl sample repository (read-only) and write final_answer.md."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

sys.dont_write_bytecode = True


def read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def load_cli_facts(root: Path) -> dict:
    sys.path.insert(0, str(root / "src"))
    from citrinekit.cli import build_parser  # noqa: E402

    parser = build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    commands = {}
    for name, sp in sub.choices.items():
        flags = {}
        for act in sp._actions:
            for opt in act.option_strings:
                if opt.startswith("--") and opt != "--help":
                    flags[opt] = list(act.choices) if act.choices else None
        commands[name] = flags
    return commands


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    root = Path(args.workspace)

    scripts = re.search(r"\[project\.scripts\]\s*\n\s*(\S+)\s*=\s*\"([^\"]+)\"", read(root, "pyproject.toml"))
    script_name, script_target = scripts.group(1), scripts.group(2)
    commands = load_cli_facts(root)
    assert set(commands) == {"scan", "explain"}, commands
    assert "--format" in commands["scan"] and "--format" not in commands["explain"]
    fmt_choices = "|".join(commands["scan"]["--format"])

    defaults = yaml.safe_load(read(root, "config/defaults.yaml"))
    profiles = yaml.safe_load(read(root, "config/profiles.example.yaml"))["profiles"]
    local = profiles["local-dev"]
    config_src = read(root, "src/citrinekit/config.py")
    env_vars = sorted(set(re.findall(r"CITRINE_[A-Z_]+", config_src)))
    assert env_vars == ["CITRINE_DEFAULT_PROFILE", "CITRINE_PROFILE_FILE"], env_vars

    profile_schema = json.loads(read(root, "schemas/profile.schema.json"))
    prof_props = profile_schema["properties"]["profiles"]["additionalProperties"]["properties"]
    schema_fields = [f"{sec}.{key}" for sec, body in prof_props.items() for key in body["properties"]]
    assert schema_fields == ["scan.retry_count", "scan.timeout_seconds", "output.format", "output.include_warnings"]

    rec_schema = json.loads(read(root, "schemas/scan-result.schema.json"))
    required = rec_schema["required"]
    record_types = rec_schema["properties"]["record_type"]["enum"]

    d_retry = defaults["scan"]["retry_count"]
    d_timeout = defaults["scan"]["timeout_seconds"]
    d_fmt = defaults["output"]["format"]
    d_warn = str(defaults["output"]["include_warnings"]).lower()
    l_retry = local["scan"]["retry_count"]
    l_timeout = local["scan"]["timeout_seconds"]
    l_fmt = local["output"]["format"]
    l_warn = str(local["output"]["include_warnings"]).lower()
    req = ", ".join(f"`{r}`" for r in required)

    md = f"""# citrinectl 使用手册：CLI 与 Python API

本文基于 `input/sample_workspace/citrinectl` 示例仓库整理，覆盖 CLI、Python API、config、schema、examples、output 和 caveat。README 很简短，不能作为完整参考（`README.md`），所以下面的结论同时对照了 docs、source、config、schema 和 examples。

## 1. CLI 命令与参数

可执行入口：项目脚本 `{script_name}` 映射到 `{script_target}`（`pyproject.toml`）。解析器在 `src/citrinekit/cli.py` 中注册了两个子命令：`scan` 和 `explain`。

```bash
citrinectl scan JOB_FILE [--profile NAME] [--format {fmt_choices}] [--include-warnings]
citrinectl explain JOB_FILE [--profile NAME]
```

- `citrinectl scan JOB_FILE`：检查 job YAML 并输出结果（`docs/quickstart.md`、`src/citrinekit/cli.py`）。
- `--profile NAME`：在加载 defaults 之后选择命名 profile（`docs/quickstart.md`）。
- `--format {fmt_choices}`：选择渲染模式。省略时由解析后的 config 中的 `output.format` 决定，即回退到 config（`src/citrinekit/cli.py` 中 `args.format or settings["output"]["format"]`）。
- `--include-warnings`：在 `jsonl` 和 `summary` 输出中保留 warning 细节；profile 中 `output.include_warnings` 为 true 时同样生效（`src/citrinekit/cli.py`）。
- `citrinectl explain JOB_FILE`：打印 config 与 schema 说明，只接受 `--profile NAME`，不接受 `--format`（`docs/quickstart.md`、`src/citrinekit/cli.py`）。

典型调用，来自 examples：

```bash
citrinectl scan tests/fixtures/minimal_job.yaml --format summary
citrinectl scan tests/fixtures/minimal_job.yaml --profile local-dev --include-warnings
```

- `examples/cli/scan_minimal.sh` 使用 `--format summary`。
- `examples/cli/scan_with_profile.sh` 使用 `--profile local-dev --include-warnings`。

## 2. Python API 入口

包 `citrinekit` 只导出 `ScanClient` 和 `ScanResult`（`src/citrinekit/__init__.py`）。调用方式见 `docs/api-client.md` 与 `examples/python/use_client.py`：

```python
from citrinekit.client import ScanClient

client = ScanClient.from_profile("local-dev")
result = client.scan_job("tests/fixtures/minimal_job.yaml", include_warnings=True)
for record in result.to_records():
    print(record)
print(result.to_summary())
```

- `ScanClient.from_profile(profile_name)`：按 profile 名称加载解析后的 config 并构造 client（`src/citrinekit/client.py`）。
- `ScanClient.scan_job(job_path, include_warnings=False)`：返回 `ScanResult`。
- `ScanResult.to_records()`：返回 JSONL 兼容的 dict 列表。
- `ScanResult.to_summary()`：返回紧凑的 summary 字符串。

CLI 与 API 的差异（`docs/api-client.md`、`src/citrinekit/render.py`）：`scan_job` 没有 `format` 参数，不支持 `format="table"` 这类 CLI 渲染选项；渲染要在得到 `ScanResult` 之后，用 `to_records()` 或 `to_summary()` 自行选择。`table`、`jsonl`、`summary` 三种渲染由 CLI 通过 `render_result` 完成。

## 3. config、默认值与 schema 的关系

解析顺序（`docs/config-resolution.md`、`src/citrinekit/config.py`），后一层只覆盖它实际提供的字段：

1. `config/defaults.yaml` 中的 packaged defaults；
2. 命名 profile：来自 `config/profiles.example.yaml`，或由 `CITRINE_PROFILE_FILE` 指向的 profile 文件；
3. 解析器暴露的 CLI flags（`--profile`、`--format`、`--include-warnings`）。

默认 profile 名称是 `default`（`config/defaults.yaml`）：`retry_count: {d_retry}`、`timeout_seconds: {d_timeout}`、`output.format: {d_fmt}`、`include_warnings={d_warn}`。示例 profile `local-dev`（`config/profiles.example.yaml`）：`retry_count: {l_retry}`、`timeout_seconds: {l_timeout}`、`output.format: {l_fmt}`、`include_warnings={l_warn}`，所以 `--profile local-dev` 会得到短超时和 JSONL 输出。

环境变量只有两个：`{env_vars[1]}` 指向备用 profile YAML 文件，`{env_vars[0]}` 在没有传 `--profile` 时改变使用的 profile 名称（`docs/config-resolution.md`、`src/citrinekit/config.py`）。没有用于单次指定输出格式的环境变量；输出格式在 CLI 用 `--format`，在 Python 用 `ScanResult` 的 `to_records()` 或 `to_summary()`。

profile schema（`schemas/profile.schema.json`）约束的字段是 {", ".join(f"`{f}`" for f in schema_fields)}；`output.format` 的枚举是 `table`、`jsonl`、`summary`，其余字段不允许额外属性。

命名歧义 caveat：`docs/config-resolution.md` 写的是 `scan.timeout`，而 `config/defaults.yaml`、`config/profiles.example.yaml` 和 `schemas/profile.schema.json` 使用 `scan.timeout_seconds`。两者很可能指同一个设置，文档命名不一致；应以 config 和 schema 的 `timeout_seconds` 为准，不要把它当成两个独立字段，也不要编造 `scan.timeout` 的行为。

## 4. examples 与 output 格式

三种渲染模式（`docs/output-format.md`、`src/citrinekit/render.py`）：

- `table`：简短终端表格，供人工查看，可能只显示 warning 数量。
- `summary`：紧凑文本摘要，包含数量和最终状态；启用 warning 细节且存在 warning 时追加 `warning_details=included`。
- `jsonl`：每行一个 JSON 对象，适合下游工具处理。

JSONL 记录有三类 `record_type`：{", ".join(f"`{t}`" for t in record_types)}。机器可读约定在 `schemas/scan-result.schema.json`：必填字段是 {req}；`metric` 记录必须有 `metrics`，`summary` 和 `warning` 记录必须有 `message`；`status` 取值 `ok`、`warning`、`blocked`。

示例输出 `examples/output/scan_summary.jsonl` 包含 summary、metric、warning 三行记录，可与 schema 逐字段对照。输入样例是 `tests/fixtures/minimal_job.yaml`，它引用 `examples/data/sample-items.txt`。

warning 行为：`jsonl` 模式只有在 `include_warnings` 解析为 true 时才输出 warning 记录；`summary` 和 `table` 模式只汇总或折叠 warning 细节（`docs/output-format.md`、`src/citrinekit/render.py`）。

## 5. caveat：不支持与不明确的内容

下列内容来自过期文档、规划笔记或未接入的实验代码，不能当作当前支持的功能：

- `--json`：历史的 pre-0.4 草稿写法，当前解析器未注册；需要机器可读输出时改用 `--format jsonl`（`docs/migration-v1.md`、`examples/legacy/old_json_flag.txt`、`src/citrinekit/cli.py`）。
- `citrinectl run`：历史命令，已不再使用；当前命令是 `citrinectl scan`（`docs/migration-v1.md`、`src/citrinekit/cli.py`）。
- `stream_scan_events`：experimental 草稿函数，只抛出 `NotImplementedError`，未接入 CLI 和公开 API 文档（`src/citrinekit/experimental.py`）；roadmap 中的 streaming 同样属于规划，不支持（`notes/roadmap_draft.txt`、`docs/output-format.md`）。
- `sync_remote_profile` 与 remote profile sync：roadmap placeholder，没有服务端点，不支持（`src/citrinekit/experimental.py`、`notes/roadmap_draft.txt`）。
- CSV export：只在 roadmap 中作为未来 dashboard adapter 出现，当前不支持；renderer 也不输出 XML 或 remote webhook 事件（`notes/roadmap_draft.txt`、`docs/output-format.md`、`src/citrinekit/render.py`）。
- `README.md` 与 `docs/glossary.md` 只是概览和术语说明，不是完整参考；判断当前行为时以解析器源码、维护中的 docs 和 schema 为准。

判断规则：一个命令、参数或函数，只有同时出现在 `src/citrinekit/cli.py` 的解析器或 `src/citrinekit/__init__.py` 的导出中，并且在维护中的 docs 里有说明，才可以当作当前可用。
"""

    Path(args.output).write_text(md, encoding="utf-8")

    cited = set(re.findall(r"(?:docs|src|config|schemas|examples|tests|notes)/[A-Za-z0-9_./-]+\.[A-Za-z0-9]+|README\.md|pyproject\.toml", md))
    missing = sorted(p for p in cited if not (root / p).exists())
    if missing:
        raise SystemExit(f"cited paths missing: {missing}")
    print(f"wrote {args.output} ({len(md)} chars, {len(cited)} cited paths)")


if __name__ == "__main__":
    main()
