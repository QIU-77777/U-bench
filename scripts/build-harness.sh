#!/usr/bin/env bash
# 构建 harness 镜像；每个 trial 以只读方式挂载它。
# 版本、标签、挂载点来自 harness/<name>/manifest.yaml。
#
# 用法：scripts/build-harness.sh <harness>      （pi | opencode | claude-code）
#       scripts/build-harness.sh --all
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PATH="$PATH:/Applications/Docker.app/Contents/Resources/bin"

[ $# -eq 1 ] || { sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 1; }
PY=".venv/bin/python"
[ -x "$PY" ] || { echo "ERROR: 缺少 $PY，先按 README 创建虚拟环境。" >&2; exit 1; }

if [ "$1" = "--all" ]; then
    for dir in harness/*/; do "$0" "$(basename "$dir")"; done
    exit 0
fi

HARNESS="$1"
[ -f "harness/$HARNESS/manifest.yaml" ] || { echo "ERROR: 未知 harness：$HARNESS" >&2; exit 1; }

read -r IMAGE VERSION < <("$PY" - "$HARNESS" <<'PY'
import sys
import yaml

m = yaml.safe_load(open(f"harness/{sys.argv[1]}/manifest.yaml"))
print(f"{m['image_repository']}:{m['version']}", m["version"])
PY
)

case "$HARNESS" in
    pi)          ARG="PI_VERSION" ;;
    opencode)    ARG="OPENCODE_CLI_VERSION" ;;
    claude-code) ARG="CLAUDE_CODE_VERSION" ;;
    *) echo "ERROR: build-harness.sh 没有 $HARNESS 的构建参数映射" >&2; exit 1 ;;
esac

docker build --build-arg "$ARG=$VERSION" -t "$IMAGE" "harness/$HARNESS"
echo "已构建 $IMAGE"
