# U-bench：编码与办公任务的 Agent 评测

在本地用 Harbor 评测 CLI 编码 Agent（OpenCode、pi、Claude Code）。任务自带 Docker 环境与评分，Agent 在容器里完成任务，Harbor 记录轨迹与分数，`harbor view` 浏览结果。所有操作都在命令行完成。

## 目录

```text
configs/agents/   agent 原型：harness + 模型，一个文件一个原型
configs/benches/  任务集合 + 评分连接
datasets/         Harbor 原生任务集（每个任务含 environment/ tests/ solution/）
harness/          harness 镜像（CLI 预装，只读挂载进 trial 容器）
scripts/          run.sh（评测入口）、build-harness.sh、sync-office-verifier.sh 等
harbor_test_agents.py   挂载版 agent（只替换 install）
jobs/             运行结果（git 忽略）
```

`configs/agents/*.yaml` 与 `configs/benches/*.yaml` 都是 Harbor JobConfig 片段，由 `harbor run -c a.yaml -c b.yaml` 原生合并；密钥写在 `.env`，配置里用 `${VAR}` 引用，缺失时 Harbor 直接报错。

## 准备

需要 Docker Desktop（API ≥ 1.48）、Python 3.12 和 uv。`docker` 不在 PATH 时脚本会自动补上 Docker Desktop 的路径。

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
cp .env.example .env && chmod 600 .env     # 填写密钥与 JUDGE_*
scripts/ensure-base-images.sh              # python:3.12-slim、node:22-slim（Docker Hub 不可达时走镜像站）
scripts/build-harness.sh --all             # 构建 pi、opencode、claude-code 镜像
```

## 评测

```bash
scripts/run.sh wb-office pi-deepseek-flash                  # 一个任务集 × 一个 agent 原型
scripts/run.sh code-basic claude-code-deepseek-flash
scripts/run.sh wb-office pi-deepseek-flash --dry-run        # 只校验配置，不运行
scripts/run.sh wb-office pi-deepseek-flash -i '*analyst*'   # 只跑匹配的任务
scripts/run.sh wb-office pi-deepseek-flash -k 3 -n 2        # 每任务 3 次，2 并发
scripts/run.sh --oracle wb-office                           # 用参考解验收任务集
```

`run.sh` 先校验 agent 配置挂载的镜像与 `harness/<name>/manifest.yaml` 一致且已构建，再调用 `harbor run`。多出的参数原样交给 `harbor run`（`harbor run --help` 查看全部）。结果写入 `jobs/<bench>-<agent>-<时间>/`。

## 查看与分析（Harbor 原生）

```bash
.venv/bin/harbor view jobs                          # 网页：任务列表、对比、轨迹、评分输出
.venv/bin/harbor analyze jobs/<job> --failing       # 用 LLM 分析失败轨迹
.venv/bin/harbor job regrade jobs/<job>             # 评分逻辑改动后，对已有 trial 重新评分
.venv/bin/harbor run -c ... --diff jobs/<job>       # 只重跑相对旧 job 有变化的 trial
.venv/bin/harbor job resume jobs/<job>              # 续跑中断的 job
```

单次 trial 的目录含 `agent/trajectory.json`（ATIF 轨迹）、`verifier/reward.json`（分数）、`verifier/score.json`（规则分、judge 分、逐条 rubric 判定）。

## 新增内容

- **agent 原型**：复制 `configs/agents/` 下同 harness 的文件，改 `model_name`、`env` 里的连接变量与 `kwargs`，在 `.env` 补变量。挂载镜像与 `PATH` 保持不变。
- **harness**：新建 `harness/<name>/{Dockerfile,manifest.yaml}`，在 `scripts/build-harness.sh` 补构建参数，在 `harbor_test_agents.py` 补挂载版类。
- **任务**：`harbor init` 生成骨架，写 `instruction.md`、`environment/Dockerfile`、`tests/test.sh`（把分数写入 `/logs/verifier/reward.json`）、`solution/solve.sh`；`harbor check <任务目录>` 检查质量。
- **任务集**：在 `configs/benches/<bench>.yaml` 写 `datasets[0].path` 与并发等运行参数。
- **验收**：`scripts/run.sh --oracle <bench>` 全部通过，且 `harbor run -c configs/benches/<bench>.yaml -a nop` 得分低于参考解，任务才算可用。

## 内置任务集

| bench | 内容 | 评分 |
|---|---|---|
| `wb-office` | 腾讯 WorkBuddy Bench 办公子集前 5 个任务 | 规则 pytest + LLM judge 加权，见 `datasets/wb-office-v1.0/README.md` |
| `code-basic` | 3 个代码任务：修 bug、实现命令行工具、保持行为的重构 | 隐藏 pytest 通过率，见 `datasets/code-basic-v1/README.md` |

## 约束

- harness 镜像与任务镜像同属 glibc（`node:22-slim`、`python:3.12-slim`）。
- harness 镜像挂载到 `/opt/<name>`，agent 配置的 `env.PATH` 必须包含 `/opt/<name>/bin`。
- 评分无效不给分：verifier 异常或 judge 不可用时，trial 记为异常，没有 `reward.json`。
- Harbor 0.24.0 的 Viewer 若出现 `KeyError: 'litellm'` 日志，执行 `.venv/bin/python scripts/fix-litellm-viewer.py` 后重启；该修复只适用于 litellm 1.105.0。
- `console/` 是早期的网页工作台，依赖已移除的旧运行入口，暂时冻结，待命令行流程稳定后基于 Harbor 原生输出重建。
