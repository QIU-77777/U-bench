# U-bench：编码与办公任务的 Agent 评测

U-bench 使用 Harbor 调度评测试验，在任务自带的 Docker 环境中运行 CLI 编码 Agent，记录模型轨迹、工具调用与评分证据。框架提供三种 harness（OpenCode、pi、Claude Code）、任务级 Docker 环境、Console 评测工作台。

座舱 agent 评测已从本仓库剥离，移回 [ESA-bench](https://github.com/QIU-77777/ESA-bench)。本仓库的远程仓库为 <https://github.com/QIU-77777/U-bench>。

## 组成

| 位置 | 内容 |
|---|---|
| `harbor_test_agents.py` | 三种 harness 的挂载版实现：CLI 来自预构建镜像，只读挂载到容器 `/usr/local`，版本由镜像 tag 固定 |
| `harbor_test_env.py` | Docker 环境扩展：镜像挂载的 API 版本协商（需要 ≥ 1.48），版本不足时提前失败 |
| `harbor_test_verifier.py` | 把 Console 的 Scorer 接入 trial 生命周期 |
| `harness/<name>/` | 各 harness 的 `manifest.yaml`：镜像仓库、版本、挂载路径的唯一来源 |
| `configs/bench/` | 任务集合定义（`hello` 为当前集合，等待作者录入编码任务） |
| `configs/jobs/` | 运行模板：bench、harness、model 的组合 |
| `configs/models/` | 模型标识与连接变量映射 |
| `console/` | 评测工作台：数据集、评分器、实验、结果分析、人工复核、闭环回流 |
| `scripts/` | `run.sh`（预检后调 Harbor）、`render-job.py`、`build-harness.sh`、`fix-litellm-viewer.py` |
| `tasks/` | 任务目录，每题含 `instruction.md`、`environment/`、`solution/`、`tests/` |

默认运行流程：

```text
Harbor trial
  └─ MountedOpenCode / MountedPi / MountedClaudeCode
       └─ 容器内 CLI（镜像挂载）→ 模型 Responses/Chat API
  └─ 任务环境（任务自带 Dockerfile，Harbor 构建）
  └─ verifier → Console Scorer（llm_judge 或 code_runner）
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

### 2. 构建 harness 镜像

```bash
scripts/build-harness.sh opencode     # 或 pi / claude-code
```

镜像仓库与版本以 `harness/<name>/manifest.yaml` 为准。

### 3. 配置模型

```bash
cp .env.example .env
chmod 600 .env
```

按 `<PREFIX>_*` 变量组填写一组 provider 的连接与密钥（`GO_`、`DEEPSEEK_`、`STEPFUN_` 三组示例）。模型标识写成 `provider/model-id`，`scripts/run.sh` 会校验 `.env` 中的模型 ID 与请求一致。

### 4. 运行

```bash
# 预检（不运行）：校验 harness 挂载、镜像版本、模型端点连通性
scripts/run.sh --bench hello --harness opencode --model go/mimo-v2.6-flash --dry-run

# 正式运行
scripts/run.sh --bench hello --harness opencode --model go/mimo-v2.6-flash

# 或用模板
scripts/run.sh --job go-opencode-hello
```

`hello` 集合当前没有任务。录入第一批评编码任务的步骤：

1. 复制任务骨架，写 `instruction.md`（用户指令）；
2. 写 `environment/Dockerfile`（语言工具链、测试数据、应用依赖）；
3. 写 `solution/`：`solve.sh` 入口加参考程序；
4. 写 `tests/`：`test.sh` 加评分实现，错误答案测试放 `tests/`；
5. 把任务加入 `configs/bench/hello.yaml`，并配一份原生 Oracle 验收 job 配置；
6. 通过 Harbor 原生 Oracle 的实际 Docker 验收后才可进入正式评测。

评分有两种入口：Console 的 `llm_judge`（提示词模板加结构化 JSON 输出）与 `code_runner`（代码评分）。经 `--scorer-config` 指定：

```bash
scripts/run.sh --bench hello --harness opencode --model go/mimo-v2.6-flash \
  --scorer-config /path/to/scorer.json
```

### 5. 查看结果

```bash
.venv/bin/harbor view "$PWD/jobs"
```

默认打开 `http://127.0.0.1:8080`，结果位于 `jobs/<job-name>/`。Console 启动时自动拉起该服务：

```bash
nohup .venv/bin/python -m uvicorn console.app.main:app --host 127.0.0.1 --port 8899 &
```

浏览器打开 `http://127.0.0.1:8899`。Console 页面覆盖数据集管理、评分器版本管理、实验快照冻结、Trace 轨迹（内嵌 Harbor view）、Dashboards 与人工复核。

## 开发验证

```bash
.venv/bin/python -m unittest discover -s console -t . -v   # Console 单测
node --test console/test_*.mjs 2>/dev/null || true
```

Harbor 0.24.0 的 Viewer 若出现 `KeyError: 'litellm'` 日志异常，应用 `scripts/fix-litellm-viewer.py` 后重启 Viewer；该修复仅适用于指定 LiteLLM 版本，重装依赖可能覆盖它。
