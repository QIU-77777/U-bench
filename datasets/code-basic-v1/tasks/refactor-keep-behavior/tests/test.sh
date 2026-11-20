#!/bin/bash
# Harbor 评分入口：对 /workspace 运行隐藏测试，按通过比例写入 reward。
set -u
mkdir -p /logs/verifier
cd /workspace
python -m pytest /tests/test_hidden.py -q -p no:cacheprovider --junitxml=/logs/verifier/junit.xml \
    > /logs/verifier/pytest.log 2>&1
python - <<'PY'
import json
import xml.etree.ElementTree as ET

root = ET.parse("/logs/verifier/junit.xml").getroot()
suite = root if root.tag == "testsuite" else root.find("testsuite")
total = int(suite.get("tests", 0))
bad = int(suite.get("failures", 0)) + int(suite.get("errors", 0)) + int(suite.get("skipped", 0))
if total == 0:
    raise SystemExit("no tests collected: verifier result invalid")
reward = (total - bad) / total
json.dump({"reward": round(reward, 4)}, open("/logs/verifier/reward.json", "w"))
print(f"passed {total - bad}/{total}")
PY
