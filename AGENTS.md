# Repository rules

- 本项目使用 Harbor 评测编码与办公任务的 agent。harness 为 opencode、pi、claude-code 三种 CLI agent，模型连接经 `.env` 的 `<PREFIX>_*` 变量组注入。
- 所有活动任务必须兼容 Harbor 原生 OracleAgent。参考解必须提供标准 `solution/solve.sh` 入口。辅助 Python 程序放在 `solution/`，评分和错误答案测试放在 `tests/`。
- 新增或修改任务后，必须使用原生 Oracle 执行实际 Docker 环境验收，并确认统一 verifier 通过。自定义 Agent 验证不能替代此项验收。
- 普通模型运行不得收到参考解或评分答案。Oracle 仅在原生执行阶段接收 `solution/`，verifier 在评分阶段接收 `tests/`。
- 参考验证、Oracle 和正式模型评分必须使用同一个评分实现。程序异常或证据缺失必须使评分无效。
- 任务环境由任务自己的 `environment/Dockerfile` 定义，Harbor 负责构建。公共基础镜像的变更需要重新构建受影响的任务镜像。
- harness 镜像版本由 `harness/<name>/manifest.yaml` 单一来源控制；job 配置里的镜像挂载必须与 manifest 一致，`scripts/run.sh` 启动时会校验。
- 新增任务须同时加入 benchmark 配置（`configs/bench/*.yaml`）与原生 Oracle 验收配置。
- 未经用户要求，不提交代码。
