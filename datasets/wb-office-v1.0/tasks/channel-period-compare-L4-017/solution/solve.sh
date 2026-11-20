#!/bin/bash
set -euo pipefail
cd /workspace
mkdir -p output
python3 "$(dirname "$0")/solve.py" /workspace/input /workspace/output/result.xlsx
