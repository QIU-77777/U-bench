"""Render a dataset version into a Harbor tasks directory."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

STANDARD_DOCKERFILE = """\
FROM node:22-alpine
RUN apk add --no-cache bash curl coreutils python3 py3-pytest
WORKDIR /app
"""

# M1 ships a passing stub. Scoring moves to ConsoleVerifier in M2.
TEST_SH = """\
#!/bin/bash
# Stub verifier: scoring is provided by the console Scorer (M2).
echo 1 > /logs/verifier/reward.txt
"""

SOLVE_SCRIPT = """\
#!/bin/bash
set -euo pipefail
python3 /solution/runner.py
"""

TASK_TOML = """\
schema_version = "1.4"
artifacts = []

[task]
name = "{task_name}"
version = "1.0.0"
description = "Console-rendered task from dataset {dataset_name} v{version_no}"
authors = []
keywords = ["console", "{dataset_name}"]

[metadata]
row_id = {row_id}
expected = {expected}
rubric = {rubric}
tags = {tags}

[verifier]
timeout_sec = 300.0
collect = []

[verifier.env]

[agent]
timeout_sec = 600.0

[environment]
network_mode = "public"
build_timeout_sec = 600.0
os = "linux"
mcp_servers = []

[environment.env]

[solution.env]
"""


def _toml_literal(value):
    if isinstance(value, dict):
        return "{" + ", ".join(json.dumps(str(key), ensure_ascii=False) + " = " + _toml_literal(child) for key, child in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_toml_literal(child) for child in value) + "]"
    if value is None:
        return '"null"'
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def render_tasks(
    rows: list[dict],
    out_dir: Path,
    env_template: str,
    dataset_name: str,
    version_no: int,
) -> Path:
    """Write one Harbor task directory per row under out_dir/tasks/.

    Every task gets the generic skeleton: instruction, task.toml, a stub
    test.sh and a standard environment Dockerfile. The author completes the
    environment definition, solution/ and tests/ per the task contract.
    ``env_template`` is kept for call-site compatibility.
    """
    tasks_dir = out_dir / "tasks"
    if tasks_dir.exists():
        shutil.rmtree(tasks_dir)
    tasks_dir.mkdir(parents=True)

    for row in rows:
        task_dir = tasks_dir / row["row_id"]
        task_dir.mkdir()
        (task_dir / "instruction.md").write_text(row["input"])
        (task_dir / "task.toml").write_text(
            TASK_TOML.format(
                task_name=f"{dataset_name}/{row['row_id']}",
                dataset_name=dataset_name,
                version_no=version_no,
                row_id=_toml_literal(row["row_id"]),
                expected=_toml_literal(row["expected"]),
                rubric=_toml_literal(row["rubric"]),
                tags=_toml_literal(row["tags"]),
            )
        )
        tests_dir = task_dir / "tests"
        tests_dir.mkdir()
        test_sh = tests_dir / "test.sh"
        test_sh.write_text(TEST_SH)
        test_sh.chmod(0o755)

        env_dir = task_dir / "environment"
        env_dir.mkdir()
        (env_dir / "Dockerfile").write_text(STANDARD_DOCKERFILE)

    return tasks_dir
