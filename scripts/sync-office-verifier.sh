#!/bin/bash
# Install the Harbor-native composite verifier into every wb-office task.
#
# Each task's tests/ directory is uploaded to /tests by Harbor, so the
# verifier must be self-contained per task. This script keeps the five
# copies in sync with the canonical source under scripts/office-verifier/.
#
# Usage: scripts/sync-office-verifier.sh [tasks-dir]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

TASKS_DIR="${1:-datasets/wb-office-v1.0/tasks}"
PY=".venv/bin/python"

[ -d "$TASKS_DIR" ] || { echo "ERROR: tasks dir not found: $TASKS_DIR" >&2; exit 1; }

for task_dir in "$TASKS_DIR"/*/; do
    task_name="$(basename "$task_dir")"
    tests_dir="$task_dir/tests"
    [ -d "$tests_dir" ] || { echo "SKIP $task_name (no tests/)"; continue; }

    # Canonical verifier implementation.
    cp scripts/office-verifier/verify.py "$tests_dir/verify.py"

    # Harbor entry point: replaces the upstream stub test.sh.
    cp scripts/office-verifier/test.sh "$tests_dir/test.sh"
    chmod +x "$tests_dir/test.sh"

    # judge.yaml -> judge.json so the verifier needs no yaml dependency.
    "$PY" - "$tests_dir" <<'PY'
import json
import sys
from pathlib import Path

import yaml

tests_dir = Path(sys.argv[1])
source = tests_dir / "judge.yaml"
if not source.is_file():
    (tests_dir / "judge.json").write_text("{}", encoding="utf-8")
    print(f"  judge.json: empty (no judge.yaml)")
    raise SystemExit(0)
data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
(tests_dir / "judge.json").write_text(
    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
)
rubrics = len(((data.get("llm_judge") or {}).get("rubrics")) or [])
print(f"  judge.json: {rubrics} rubrics")
PY

    # The judge prompt quotes the task instruction; it is agent-visible
    # anyway, and tests/ only reaches the container after the agent finishes.
    if [ -f "$task_dir/instruction.md" ]; then
        cp "$task_dir/instruction.md" "$tests_dir/instruction.md"
    fi

    echo "SYNCED $task_name"
done
