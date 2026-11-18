# U-bench：编码与办公任务的 Agent 评测

U-bench 使用 Harbor 调度评测试验，在任务自带的 Docker 环境中运行 CLI 编码 Agent，记录模型轨迹、工具调用与评分证据。框架提供三种 harness（OpenCode、pi、Claude Code）、任务级 Docker 环境、Console 评测工作台。

座舱 agent 评测已从本仓库剥离，移回 [ESA-bench](https://github.com/QIU-77777/ESA-bench)。本仓库的远程仓库为 <https://github.com/QIU-77777/U-bench>。

当前仓库内置一个完整可跑的 benchmark 实例：`wb-office`（源自腾讯 WorkBuddy Bench 的办公子集，前 5 个任务），覆盖「题目、环境、规则指标、LLM rubric、agent、模型、评测、trace」全链路。新用户可沿本文档走完一遍标准工作流，再按同样模式录入自己的评测集。

## 组成

| 位置 | 内容 |
|---|---|
| `harbor_test_agents.py` | 三种 harness 的挂载版实现：CLI 来自预构建镜像，只读挂载进容器，版本由镜像 tag 固定 |
| `harbor_test_env.py` | Docker 环境扩展：镜像挂载的 API 版本协商（需要 ≥ 1.48），版本不足时提前失败 |
| `harbor_test_verifier.py` | 把 Console 的 Scorer 接入 trial 生命周期（用于不自带 `tests/` 评分入口的任务） |
| `harness/<name>/` | 各 harness 的 `manifest.yaml`：镜像仓库、版本、挂载路径的唯一来源 |
| `configs/bench/` | 任务集合定义（`wb-office` 为内置实例，`hello` 为空模板） |
| `configs/jobs/` | 运行模板：bench、harness、model 的组合 |
| `configs/models/` | 模型标识与连接变量映射 |
| `datasets/` | 评测集：`wb-office-v1.0/` 含 5 个办公任务与复刻版验证器说明 |
| `scripts/office-verifier/` | 复刻版复合验证器唯一实现（`verify.py` 加 `test.sh`，仅标准库） |
| `scripts/sync-office-verifier.sh` | 把复刻版验证器同步进各任务的 `tests/` |
| `scripts/ensure-base-images.sh` | 确保任务镜像的基础镜像在本地存在（Docker Hub 不可达时的回退） |
| `scripts/run.sh` | 评测入口：预检后调 Harbor |
| `scripts/render-job.py` | 把 bench、harness、model、job 四层配置渲染成 Harbor job YAML |
| `scripts/build-harness.sh` | 按 manifest 构建 harness 镜像 |
| `console/` | 评测工作台：数据集、评分器、实验、结果分析、人工复核、闭环回流 |

默认运行流程：

```text
Harbor trial
  └─ MountedOpenCode / MountedPi / MountedClaudeCode
       └─ 容器内 CLI（镜像挂载）→ 模型 Responses/Chat API
  └─ 任务环境（任务自带 Dockerfile，Harbor 构建）
  └─ verifier
       ├─ 任务自带 tests/test.sh（Harbor 原生契约，wb-office 走这条）
       └─ 或 Console Scorer（llm_judge 或 code_runner，经 --scorer-config 指定）
```

## 快速开始

### 1. 准备环境

需要 Git、Docker（API ≥ 1.48，镜像挂载需要）、Python 3.12 和 uv。

```bash
git clone https://github.com/QIU-77777/U-bench.git
cd U-bench
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
docker info >/dev/null
```

### 2. 准备基础镜像与 harness 镜像

```bash
scripts/ensure-base-images.sh          # python:3.12-slim、node:22-slim
scripts/build-harness.sh pi-debian     # 办公任务用 glibc 版
scripts/build-harness.sh pi            # alpine 系任务用 musl 版
scripts/build-harness.sh opencode      # 或 claude-code
```

镜像仓库、版本、挂载路径以 `harness/<name>/manifest.yaml` 为准，`run.sh` 启动时校验三者一致。

**harness 镜像与任务镜像的 C 库必须同家族**：`*-alpine` 基础镜像是 musl，`*-slim`、`python:*`（非 alpine）、`debian:*` 是 glibc，两者二进制互不通用。musl 的 node 在 glibc 镜像里执行会报 `node: No such file or directory`（缺失动态链接器，文件本身在 PATH 里）。判定方法：看任务 `environment/Dockerfile` 的 `FROM` 行。`harness/pi-debian` 就是为 Debian 系任务建的 glibc 先例，挂载点为 `/opt/pi-debian`（避免遮挡任务镜像 `/usr/local` 下的 python），其 PATH 经 `configs/harnesses/pi-debian.yaml` 的 `env` 注入。

### 3. 配置模型

```bash
cp .env.example .env
chmod 600 .env
```

按 `<PREFIX>_*` 变量组填写一组 provider 的连接与密钥（`.env` 内有注释说明）。模型标识写成 `provider/model-id`，`configs/models/<provider>/<model-id>.yaml` 声明该模型支持的协议与连接变量名；`run.sh` 会校验 `.env` 中的模型 ID 与请求一致。harness 按协议取用：OpenAI 协议读 `OPENAI_BASE_URL` 与 `OPENAI_API_KEY`，Anthropic 协议读 `ANTHROPIC_BASE_URL` 与 `ANTHROPIC_API_KEY`。

### 4. 发起评测

```bash
# 预检（不运行）：校验 harness 挂载、镜像版本、模型端点连通性
scripts/run.sh --job wb-office-pi-deepseek --dry-run

# 正式运行
scripts/run.sh --job wb-office-pi-deepseek

# 等价的手动组合
scripts/run.sh --bench wb-office --harness pi-debian --model deepseek/deepseek-flash
```

`--bench` 选任务集合，`--harness` 选 agent，`--model` 选模型；`--job` 等价于一份写好的三件套模板（`configs/jobs/<slug>.yaml`）。结果落在 `jobs/<job 名>/`。

### 5. 查看结果与 trace

```bash
.venv/bin/harbor view "$PWD/jobs"
```

默认绑定 `127.0.0.1`，端口范围 `8080-8089`（自动选用空闲端口），可浏览每次 trial 的轨迹。Console 启动时自动拉起该服务：

```bash
nohup .venv/bin/python -m uvicorn console.app.main:app --host 127.0.0.1 --port 8899 &
```

浏览器打开 `http://127.0.0.1:8899`。Console 页面覆盖数据集管理、评分器版本管理、实验快照冻结、Trace 轨迹（内嵌 Harbor view）、Dashboards 与人工复核。

## 标准评测工作流

以下五步覆盖从零搭建一套评测的完整路径，`wb-office` 实例可作参照。

### 第 1 步：创建 benchmark（题目与环境）

每个任务是一个目录，Harbor 原生布局：

```text
tasks/<task-name>/
├── instruction.md        # 给 agent 的用户指令
├── task.toml             # 超时、资源、网络等运行配置
├── environment/
│   ├── Dockerfile        # 语言工具链、测试数据、应用依赖；Harbor 负责构建
│   └── workspace.tar.gz  # 初始工作区（可选，Dockerfile 内解包）
└── tests/                # 评分入口与证据，agent 结束后由 Harbor 上传到 /tests
```

录入步骤：

1. 复制任务骨架，写 `instruction.md`；
2. 写 `environment/Dockerfile`，确认基础镜像的 C 库家族与拟用 harness 一致；
3. 写评分（见第 2 步）；
4. 把任务目录加进 `configs/bench/<bench>.yaml` 的 `datasets.path`；
5. 按 `AGENTS.md` 规则完成验收后才可进入正式评测。

仓库认可两条题目路径：

- **仓库原生风格**：提供 `solution/solve.sh` 参考解，配一份原生 Oracle 验收 job，通过实际 Docker 环境验收；评分用 Console Scorer（`llm_judge` 或 `code_runner`），经 `--scorer-config` 指定。
- **导入风格**（`wb-office` 实例）：题目自带 `tests/grading`（规则 pytest）、`tests/gold`（真值答案）、`tests/judge.yaml`（LLM rubric），复刻版 `tests/test.sh` 完成复合评分。此路径暂未提供 `solution/` 参考解，Oracle 验收是后续待补项。

### 第 2 步：定义指标与 rubric

指标分两类，均落在 Harbor 原生验证器契约内：`tests/test.sh` 是入口，分数写进 `/logs/verifier/reward.json`。

- **规则指标（code verifier）**：`tests/grading` 下的 pytest 把 agent 产物与 `tests/gold/gold_answer.json` 做代码判定（集合匹配、召回率、精确率、陷阱行、列完整性等），解析 JUnit XML 得到规则分。
- **LLM 指标（LLM as judge）**：`tests/judge.yaml` 声明 artifacts（判定对象）、rubrics（每条含 question、pass_criteria、fail_criteria）与 `score_merge` 权重。判定时按 rubric 逐条送 judge 模型，输出 pass 或 fail 取均值，再与规则分按 `score_merge` 加权合并。judge 不读 gold，输入只有任务指令与 agent 产物证据（由评分阶段产出的 `artifact_manifest.json` 定位）。

复刻版验证器的使用方式：

```bash
scripts/sync-office-verifier.sh          # 把 scripts/office-verifier/ 同步进各任务 tests/
```

`scripts/office-verifier/verify.py` 是唯一实现，仅依赖标准库（xlsx 证据用 zipfile 加 XML 解析）。judge 连接经 Harbor 原生 `--verifier-env` 注入：`JUDGE_BASE_URL`、`JUDGE_API_KEY`、`JUDGE_MODEL`；`run.sh` 自动从当前模型组透传，未配置时规则分直接生效。自定义指标时改 `verify.py` 后重跑同步脚本即可，五个任务的副本保持一致。

### 第 3 步：注册 agent（harness）

一个新 harness 需要三处配套：

1. `harness/<name>/Dockerfile`：把 CLI 装进镜像，镜像根目录即挂载内容；
2. `harness/<name>/manifest.yaml`：镜像仓库、版本、挂载路径的唯一来源；
3. `configs/harnesses/<name>.yaml`：`import_path`（指向 `harbor_test_agents.py` 里的挂载版实现）、协议、CLI 参数；镜像挂在 `/usr/local` 之外时，用 `env` 补 PATH（参考 `pi-debian`）。

`scripts/build-harness.sh <name>` 构建镜像，`run.sh` 校验 job 挂载与 manifest 一致。harness 镜像的 C 库家族必须匹配任务镜像（见快速开始第 2 步）。

### 第 4 步：模型接入

1. 在 `.env` 增加一组 `<PREFIX>_*` 变量：`<PREFIX>_OPENAI_MODEL_ID`、`<PREFIX>_OPENAI_BASE_URL`、`<PREFIX>_ANTHROPIC_MODEL_ID`、`<PREFIX>_ANTHROPIC_BASE_URL`、`<PREFIX>_API_KEY`（按 harness 协议取用，另一协议可缺）；
2. 在 `configs/models/<provider>/<model-id>.yaml` 声明 `id`、`protocols`（各协议的 `model_id_env` 与 `base_url_env`）与 `api_key_env`；
3. `model:` 写成 `provider/model-id`，`run.sh` 负责校验与注入；judge 默认复用同一模型组，可在验证器环境里拆分。

### 第 5 步：发起评测与 trace 分析

1. 写 `configs/bench/<bench>.yaml`：`datasets.path` 指向任务目录，可加 `task_names` 过滤、`n_attempts`、`n_concurrent_trials`、`timeout_multiplier`；
2. 写 `configs/jobs/<slug>.yaml`：bench、harness、model 三件套，便于一键复现；
3. `scripts/run.sh --job <slug>` 发起，`--dry-run` 预检；
4. 分析结果：

```text
jobs/<job 名>/
├── result.json                      # 任务级汇总：指标均值、token 统计、异常分类
├── config.json / lock.json          # 本次运行的完整配置与锁定快照
└── <task 名>__<trial id>/
    ├── result.json / config.json    # 单次 trial 的结果与配置
    ├── trial.log                    # 运行日志
    ├── agent/
    │   ├── trajectory.json          # ATIF 格式轨迹（harbor view 与 Console 读取）
    │   ├── pi.txt                   # pi 的 CLI 原始输出（opencode 为 opencode.txt）
    │   ├── pi/sessions/*.jsonl      # pi 的原生会话日志（claude-code 为 sessions/projects/）
    │   └── setup/                   # agent 安装阶段输出（部分 harness 为空目录）
    └── verifier/
        ├── reward.json              # 最终分数（Harbor 读取的契约文件）
        ├── score.json               # 评分明细：规则分、LLM 分、逐条 rubric 判定、合并权重
        ├── results.xml              # 规则 pytest 的 JUnit 结果
        ├── rule_pytest_output.txt   # 规则 pytest 原始输出
        └── artifact_text/ …         # 评分阶段归档的 agent 产物证据
```

定位一次失败：先看 `result.json` 的异常分类，再看 `verifier/score.json` 的规则分与逐条 rubric 判定，最后看 `agent/trajectory.json` 还原 agent 行为。批量对比与人工复核走 Console。

## 开发验证

```bash
.venv/bin/python -m unittest discover -s console -t . -v   # Console 单测
node --test console/test_*.mjs 2>/dev/null || true
```

Harbor 0.24.0 的 Viewer 若出现 `KeyError: 'litellm'` 日志异常，应用 `scripts/fix-litellm-viewer.py` 后重启 Viewer；该修复仅适用于指定 LiteLLM 版本，重装依赖可能覆盖它。
