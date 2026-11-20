#!/usr/bin/env bash
set -euo pipefail
SOLUTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd /workspace
mkdir -p output
python3 "$SOLUTION_DIR/revise_deck.py" \
  --deck input/quarterly_governance_board_deck.pptx \
  --register input/program_milestone_update_register.xlsx \
  --out output/quarterly_governance_board_deck_revised.pptx
