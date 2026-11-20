#!/bin/bash
set -euo pipefail
cd /workspace
mkdir -p output
python3 "$(dirname "$0")/build_extract.py"
