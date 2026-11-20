import json
import subprocess
import sys

import pytest

TOOL = "/workspace/csvagg.py"
SAMPLE = "/workspace/sample.csv"


def run(*args):
    return subprocess.run([sys.executable, TOOL, *args], capture_output=True, text=True,
                          cwd="/workspace", timeout=30)


def ok(*args):
    proc = run(*args)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.fixture
def make_csv(tmp_path):
    def make(text, name="data.csv", encoding="utf-8"):
        path = tmp_path / name
        path.write_bytes(text.encode(encoding))
        return str(path)
    return make


def test_sum_sample():
    out = ok(SAMPLE, "--group-by", "region", "--value", "units", "--op", "sum")
    assert out == {"op": "sum", "group_by": "region", "value": "units",
                   "groups": {"East": 13, "North": None, "West": 9}}
    assert list(out["groups"]) == ["East", "North", "West"]


def test_avg_rounding_and_min_max():
    assert ok(SAMPLE, "--group-by", "product", "--value", "price", "--op", "avg")["groups"] == {
        "book": 12.0, "lamp": 25.25, "pen": 1.5}
    assert ok(SAMPLE, "--group-by", "region", "--value", "price", "--op", "min")["groups"] == {
        "East": 1.5, "North": 12.0, "West": 1.5}
    assert ok(SAMPLE, "--group-by", "region", "--value", "price", "--op", "max")["groups"] == {
        "East": 12.0, "North": 12.0, "West": 25.25}


def test_avg_two_decimals(make_csv):
    path = make_csv("g,v\na,1\na,1\na,2\n")
    assert ok(path, "--group-by", "g", "--value", "v", "--op", "avg")["groups"] == {"a": 1.33}


def test_count_includes_empty_cells():
    out = ok(SAMPLE, "--group-by", "region", "--value", "units", "--op", "count")
    assert out["groups"] == {"East": 2, "North": 1, "West": 2}


def test_count_does_not_parse_value(make_csv):
    path = make_csv("g,v\na,hello\na,\nb,x\n")
    assert ok(path, "--group-by", "g", "--value", "v", "--op", "count")["groups"] == {"a": 2, "b": 1}


def test_quoted_fields_and_empty_key(make_csv):
    path = make_csv('name,amount\n"Smith, J",5\n"Smith, J",7\n,3\n"multi\nline",1\n')
    out = ok(path, "--group-by", "name", "--value", "amount", "--op", "sum")
    assert out["groups"] == {"": 3, "Smith, J": 12, "multi\nline": 1}
    assert list(out["groups"]) == ["", "Smith, J", "multi\nline"]


def test_bom_and_whitespace(make_csv):
    path = make_csv("\ufeffg,v\na, 4 \na,6\n", encoding="utf-8")
    assert ok(path, "--group-by", "g", "--value", "v", "--op", "sum")["groups"] == {"a": 10}


def test_header_only(make_csv):
    path = make_csv("g,v\n")
    out = ok(path, "--group-by", "g", "--value", "v", "--op", "sum")
    assert out["groups"] == {}


def test_unicode_keys_sorted(make_csv):
    path = make_csv("g,v\nbeta,1\n阿,2\nalpha,3\n")
    out = ok(path, "--group-by", "g", "--value", "v", "--op", "sum")
    assert list(out["groups"]) == ["alpha", "beta", "阿"]


def test_stdout_is_single_json_document():
    proc = run(SAMPLE, "--group-by", "region", "--value", "units", "--op", "sum")
    assert json.loads(proc.stdout)
    assert proc.stdout.strip().count("\n") == 0


def test_missing_args_exit_2():
    proc = run(SAMPLE, "--group-by", "region")
    assert proc.returncode == 2
    assert proc.stdout == ""


def test_invalid_op_exit_2():
    proc = run(SAMPLE, "--group-by", "region", "--value", "units", "--op", "median")
    assert proc.returncode == 2
    assert proc.stdout == ""


def test_missing_file_exit_1():
    proc = run("/nonexistent/file.csv", "--group-by", "a", "--value", "b", "--op", "sum")
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.startswith("error:")


def test_missing_column_exit_1():
    for args in (("--group-by", "nope", "--value", "units"), ("--group-by", "region", "--value", "nope")):
        proc = run(SAMPLE, *args, "--op", "sum")
        assert proc.returncode == 1
        assert proc.stdout == ""
        assert proc.stderr.startswith("error:")


def test_non_numeric_exit_1(make_csv):
    path = make_csv("g,v\na,1\na,abc\n")
    proc = run(path, "--group-by", "g", "--value", "v", "--op", "sum")
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.startswith("error:")


def test_empty_file_exit_1(make_csv):
    path = make_csv("")
    proc = run(path, "--group-by", "g", "--value", "v", "--op", "sum")
    assert proc.returncode == 1
    assert proc.stdout == ""
