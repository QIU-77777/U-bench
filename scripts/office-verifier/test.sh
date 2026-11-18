#!/bin/bash
# Harbor-native composite verifier entry point (wb-office tasks).
#
# Harbor uploads tests/ to /tests and executes this script inside the task
# container after the agent finishes; verify.py writes the reward to
# /logs/verifier/reward.json.
set -u
cd /workspace
exec python /tests/verify.py
