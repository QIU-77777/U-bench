请在当前任务目录里做一次中等彻底的代码/文档探索，只读检查 `input/sample_workspace/citrinectl/` 这个示例源码仓库，帮我整理一份可直接写进中文使用手册的 Markdown 说明：这个工具的 CLI 和 Python API 到底应该怎么用。

执行边界：

- 只做研究和最终回复，不要修改、生成、删除或重命名任何文件。
- 不要访问外部网络、真实 package registry、真实 API、浏览器、私有服务、账号后台或该示例仓库之外的资料。
- 回答用中文 Markdown，必要的 English CLI/API/code/path terms 保留原样。
- 关键说法必须给出工作区内路径证据，例如引用相关 docs、source、config、schema、examples 或 sample output 文件路径。
- 不要只看 README，也不要把单个文件当作唯一依据；请从 docs/source/config/schema/examples/output samples 等材料之间交叉验证。

请重点覆盖：

1. CLI commands/options：可执行入口、命令格式、重要参数、典型调用示例。
2. Python API entry points：主要 import / function / class 入口、调用方式、和 CLI 的差异。
3. config/default/schema 关系：默认配置来自哪里，schema 约束什么，示例配置如何落到实际行为。
4. examples 与 output format：示例输入、示例输出、输出字段/格式如何确认。
5. unsupported/ambiguous caveats：哪些信息看起来来自 stale docs、roadmap note、experimental/unregistered code 或未接入路径，不能当作当前支持功能；如果行为不明确，请明确写成 caveat，不要编造。

输出建议按「功能/入口」「命令或 API 示例」「关键参数」「证据文件」「caveat」组织，简洁但要能支撑开发者实际上手。

请将最终中文 Markdown 保存到 `final_answer.md`，不要修改 `input/sample_workspace/citrinectl/`。
