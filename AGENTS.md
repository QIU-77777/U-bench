# Repository rules

- 本项目使用 Harbor 评测编码与办公任务的 agent。agent 原型 = harness（opencode、pi、claude-code）+ 模型，写在 `configs/agents/<原型>.yaml`；任务集合与评分连接写在 `configs/benches/<bench>.yaml`。两者都是 Harbor JobConfig 片段，由 `harbor run -c` 原生合并，密钥经 `.env` 与 `--env-file` 注入。
- 优先使用 Harbor 已有能力（`harbor run`、`view`、`analyze`、`job regrade`、`--diff`、`check`、Oracle/nop agent、`verifier.env`、`${VAR}` 模板），不重复实现。新增自制代码前先确认 Harbor 没有对应功能。
- 所有活动任务必须兼容 Harbor 原生 OracleAgent。参考解必须提供标准 `solution/solve.sh` 入口。辅助 Python 程序放在 `solution/`，评分和错误答案测试放在 `tests/`。
- 新增或修改任务后，必须使用原生 Oracle 执行实际 Docker 环境验收（`scripts/run.sh --oracle <bench>`），并确认统一 verifier 通过。自定义 Agent 验证不能替代此项验收。
- 普通模型运行不得收到参考解或评分答案。Oracle 仅在原生执行阶段接收 `solution/`，verifier 在评分阶段接收 `tests/`。
- 参考验证、Oracle 和正式模型评分必须使用同一个评分实现。程序异常或证据缺失必须使评分无效：verifier 不写 `reward.json` 并以非零码退出，不给默认分。
- 任务环境由任务自己的 `environment/Dockerfile` 定义，Harbor 负责构建。任务镜像与 harness 镜像同属 glibc（`python:3.12-slim`、`node:22-slim`）。
- harness 镜像版本由 `harness/<name>/manifest.yaml` 单一来源控制；agent 配置里的镜像挂载必须与 manifest 一致，`scripts/run.sh` 启动时校验。
- 新增任务须同时加入 benchmark 配置（`configs/benches/*.yaml`）并通过原生 Oracle 验收。
- 未经用户要求，不提交代码。
