#!/usr/bin/env bash
# 评测入口：校验后调用 Harbor 原生 `harbor run`。
#
#   scripts/run.sh <bench> <agent> [harbor run 参数...]     评测一个 agent 原型
#   scripts/run.sh --oracle <bench> [harbor run 参数...]    用参考解验收任务集
#
# <bench> 对应 configs/benches/<bench>.yaml（任务集合与评分连接），
# <agent> 对应 configs/agents/<agent>.yaml（harness + 模型 = agent 原型）。
# 两个文件都是 Harbor JobConfig 片段，由 `harbor run -c` 原生合并；
# 密钥经 .env 与 `--env-file` 注入，配置里用 ${VAR} 引用。
# 额外参数原样交给 harbor run，例如 --dry-run、-i '*任务名*'、-k 3、-n 2。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PATH="$PATH:/Applications/Docker.app/Contents/Resources/bin"

fail() { echo "ERROR: $*" >&2; exit 1; }
usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 1; }

ORACLE=0
if [ "${1:-}" = "--oracle" ]; then ORACLE=1; shift; fi
BENCH="${1:-}"; [ -n "$BENCH" ] || usage; shift
if [ "$ORACLE" = "0" ]; then AGENT="${1:-}"; [ -n "$AGENT" ] || usage; shift; else AGENT="oracle"; fi

HARBOR=".venv/bin/harbor"
[ -x "$HARBOR" ] || fail "缺少 $HARBOR，先按 README 创建虚拟环境。"
[ -f .env ] || fail "缺少 .env，先执行 cp .env.example .env 并填写密钥。"
BENCH_FILE="configs/benches/$BENCH.yaml"
[ -f "$BENCH_FILE" ] || fail "未找到 $BENCH_FILE"
docker version >/dev/null 2>&1 || fail "无法连接 Docker，先启动 Docker Desktop。"

CONFIG_ARGS=(-c "$BENCH_FILE")
AGENT_ARGS=(-a oracle)
if [ "$ORACLE" = "0" ]; then
    AGENT_FILE="configs/agents/$AGENT.yaml"
    [ -f "$AGENT_FILE" ] || fail "未找到 $AGENT_FILE"
    CONFIG_ARGS+=(-c "$AGENT_FILE")
    AGENT_ARGS=()
    # agent 配置挂载的镜像必须与 harness manifest 一致，且已构建。
    .venv/bin/python - "$AGENT_FILE" <<'PY' || exit 1
import subprocess
import sys

import yaml

config = yaml.safe_load(open(sys.argv[1])) or {}
for mount in (config.get("environment") or {}).get("mounts") or []:
    if mount.get("type") != "image":
        continue
    image = mount["source"]
    name = image.split("/")[-1].split(":")[0]
    manifest = yaml.safe_load(open(f"harness/{name}/manifest.yaml"))
    expected = f"{manifest['image_repository']}:{manifest['version']}"
    if image != expected or mount["target"] != manifest["mount_path"]:
        sys.exit(f"ERROR: {sys.argv[1]} 挂载 {image} → {mount['target']}，"
                 f"harness/{name}/manifest.yaml 要求 {expected} → {manifest['mount_path']}")
    if subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode:
        sys.exit(f"ERROR: 镜像 {image} 不存在，先执行 scripts/build-harness.sh {name}")
PY
fi

# harbor run 的任务过滤参数（-i/-x/-l）要求同时给出 -p；bench 配置里的任务目录在此自动补上。
FILTER=0; HAS_PATH=0
for arg in "$@"; do
    case "$arg" in
        -i|--include-task-name|-x|--exclude-task-name|-l|--n-tasks) FILTER=1 ;;
        -p|--path) HAS_PATH=1 ;;
    esac
done
if [ "$FILTER" = "1" ] && [ "$HAS_PATH" = "0" ]; then
    BENCH_PATH="$(.venv/bin/python -c 'import sys,yaml; print(yaml.safe_load(open(sys.argv[1]))["datasets"][0]["path"])' "$BENCH_FILE")"
    set -- -p "$BENCH_PATH" "$@"
fi

JOB_NAME="${BENCH}-${AGENT}-$(date '+%Y%m%d-%H%M%S')"
echo "job: $JOB_NAME"
PYTHONPATH="$PWD" exec "$HARBOR" run "${CONFIG_ARGS[@]}" ${AGENT_ARGS[@]+"${AGENT_ARGS[@]}"} \
    --env-file .env --job-name "$JOB_NAME" -y "$@"
