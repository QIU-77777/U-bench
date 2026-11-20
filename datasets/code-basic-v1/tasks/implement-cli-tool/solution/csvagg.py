import argparse
import csv
import json
import sys

OPS = ("sum", "avg", "min", "max", "count")


def fail(message, code=1):
    print(f"error: {message}", file=sys.stderr)
    sys.exit(code)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        fail(message, 2)


def aggregate(op, values, row_count):
    if op == "count":
        return row_count
    if not values:
        return None
    if op == "sum":
        result = sum(values)
    elif op == "avg":
        result = sum(values) / len(values)
    elif op == "min":
        result = min(values)
    else:
        result = max(values)
    result = round(result, 2)
    return int(result) if result == int(result) else result


def main(argv=None):
    parser = Parser(prog="csvagg.py")
    parser.add_argument("csv_path")
    parser.add_argument("--group-by", required=True)
    parser.add_argument("--value", required=True)
    parser.add_argument("--op", required=True, choices=OPS)
    args = parser.parse_args(argv)

    try:
        with open(args.csv_path, newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.reader(handle))
    except (OSError, UnicodeDecodeError) as exc:
        fail(f"cannot read {args.csv_path}: {exc}")
    if not rows:
        fail("empty file")
    header = rows[0]
    for column in (args.group_by, args.value):
        if column not in header:
            fail(f"column not found: {column}")
    group_index = header.index(args.group_by)
    value_index = header.index(args.value)

    counts = {}
    values = {}
    for row in rows[1:]:
        if not row:
            continue
        key = row[group_index] if group_index < len(row) else ""
        cell = row[value_index].strip() if value_index < len(row) else ""
        counts[key] = counts.get(key, 0) + 1
        values.setdefault(key, [])
        if args.op != "count" and cell:
            try:
                values[key].append(float(cell))
            except ValueError:
                fail(f"non-numeric value: {cell!r}")

    groups = {key: aggregate(args.op, values[key], counts[key]) for key in sorted(counts)}
    print(json.dumps({"op": args.op, "group_by": args.group_by, "value": args.value, "groups": groups},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
