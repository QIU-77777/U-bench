# wb-office-v1.0

腾讯 WorkBuddy Bench 办公子集（v1.0）的前 5 个任务（按名称排序），任务布局为 Harbor 原生：
`instruction.md`、`task.toml`、`environment/`、`tests/`、`solution/`。

| 任务 | 产物 | rubric 数 | 规则/judge 权重 |
|---|---|---|---|
| analyst-forecast-extract-L3-018 | xlsx + json | 10 | 0.8 / 0.2 |
| api-usage-explain-cli-l3-001 | md + json | 5 | 0.8 / 0.2 |
| board-material-update-timeline-excel | pptx | 4 | 0.8 / 0.2 |
| calendar-dida-sync-state | md + json | 5 | 0.8 / 0.2 |
| channel-period-compare-L4-017 | xlsx | 12 | 0.85 / 0.15 |

## 评分

`tests/test.sh` 是 Harbor 入口，运行 `tests/verify.py`，唯一实现在 `scripts/office-verifier/`，
由 `scripts/sync-office-verifier.sh` 同步到各任务（修改后必须重新同步）：

1. 规则分：`tests/grading` 的 pytest 对照 `tests/gold`，取 JUnit 通过率。
2. judge 分：`tests/judge.json`（由 `judge.yaml` 转换）的每条 rubric 送评审模型判定 pass 或 fail，取均值。judge 只看任务指令与产物证据，不读 gold。
3. 合并：按 `judge.yaml` 的 `score_merge` 加权求和。

评分无效时不产生分数：规则 pytest 无结果、judge 未配置、judge 请求重试后仍失败，`verify.py` 都以非零码退出且不写 `reward.json`，Harbor 将该 trial 记为异常。
judge 连接来自 `configs/benches/wb-office.yaml` 的 `verifier.env`，对应 `.env` 里的 `JUDGE_*`。

`tests/verifier.toml`、`tests/grading/judge/` 是上游原样保留的文件，Harbor 不读取。

与上游的差异：`api-usage-explain-cli-l3-001` 的 `eval_core.py` 把 `final_answer.md` 列入“不应出现的常见输出文件”，而 `instruction.md` 要求把答案保存到该文件，任何合规答案都会被扣一项。已从 `COMMON_OUTPUT_FILENAMES` 中移除该文件名。

`calendar-dida-sync-state` 的 `eval_core.py` 从 agent 已修改过的工作副本读取“初始”task_id 与 mapping_id，新建的 ID 因此被当作初始 ID，8 项 `new_create_*_uses_nonpublic_*` 对任何 agent 都失败。已改为从工作区 git 根提交读取初始文件。

## 参考解

每个任务的 `solution/solve.sh` 生成满足评分的产物，供 Harbor 原生 Oracle 验收：

```bash
scripts/run.sh --oracle wb-office
```

## 基础镜像

任务镜像基于 `python:3.12-slim`（glibc）。Docker Hub 不可达时先执行 `scripts/ensure-base-images.sh`。
