#!/bin/bash
set -euo pipefail
cd /workspace
exec python3 "$(dirname "$(readlink -f "$0")")/sync_calendar.py" /workspace
