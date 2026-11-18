# WorkBuddy Bench Office subset (wb-office-v1.0), first five tasks.
#
# Source: Tencent WorkBuddy Bench, office subset v1.0
#   /Users/jyxc-dz-0101032/qiguang/python-project/agent_eval/workbuddy-bench
#   datasets/wb-bench-office-v1.0/tasks
# Imported unchanged except for the verifier (see below). Task layout is
# Harbor-native: instruction.md + task.toml + environment/ + tests/.
#
# Tasks (alphabetical, first five of the source's 50):
#   analyst-forecast-extract-L3-018        xlsx + json      12 rubrics  0.8/0.2
#   api-usage-explain-cli-l3-001           md + json         8 rubrics  0.8/0.2
#   board-material-update-timeline-excel   md                9 rubrics  0.8/0.2
#   calendar-dida-sync-state               md               13 rubrics  0.8/0.2
#   channel-period-compare-L4-017          xlsx             13 rubrics  0.85/0.15
#
# Verifier (replicated, Harbor-native):
#   tests/test.sh    Harbor entry point; runs verify.py in /workspace
#   tests/verify.py  rule score (pytest grading + gold) + LLM judge
#                    (judge.json rubrics) + weighted_sum merge
#   tests/judge.json converted from the task's judge.yaml (no yaml dep)
#   tests/grading/   upstream rule-based pytest suite (unchanged)
#   tests/gold/      upstream gold answers (unchanged)
#   tests/verifier.toml  upstream composite-verifier spec, kept for
#                    provenance; Harbor does not read it, test.sh is the
#                    entry point. Keep copies in sync after edits:
#                    scripts/sync-office-verifier.sh
#
# Scoring: reward = (rule_weight * rule + llm_weight * llm) / (rule_weight
# + llm_weight), weights per task from judge.yaml score_merge. The LLM judge
# needs JUDGE_BASE_URL / JUDGE_API_KEY / JUDGE_MODEL in the verifier
# environment (scripts/run.sh forwards them from the model's .env group).
# Without judge env the rule score stands.
#
# Base image: every task image is FROM python:3.12-slim. Docker Hub is
# unreachable on this machine; ensure the tags exist locally before a run:
#   scripts/ensure-base-images.sh
#
# Harness: the task images are Debian-based, so the alpine-built default
# harness/pi image (musl node) cannot execute inside them
# ("/usr/bin/env: 'node': No such file or directory"). Use the glibc
# variant harness/pi-debian (configs/harnesses/pi-debian.yaml, job
# wb-office-pi-deepseek). Alpine-based task images keep harness/pi.
#
# Known gap: these tasks grade against gold answers, not a solution/solve.sh
# oracle, so they do not yet satisfy the repository's native-Oracle
# acceptance rule (AGENTS.md). Writing per-task oracles is follow-up work.
