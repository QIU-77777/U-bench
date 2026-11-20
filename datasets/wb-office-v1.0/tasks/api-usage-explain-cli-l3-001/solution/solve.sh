#!/bin/bash
set -euo pipefail
SOLUTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd /workspace
export PYTHONDONTWRITEBYTECODE=1
python "$SOLUTION_DIR/build_answer.py" \
  --workspace /workspace/input/sample_workspace/citrinectl \
  --output /workspace/final_answer.md
