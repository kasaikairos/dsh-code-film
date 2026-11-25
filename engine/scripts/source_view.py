"""Bounded source lookup. Default to an outline and read a line range only on request."""
import argparse
import ast
import json
from pathlib import Path
import re
import sys

BUDGET = 2200


def outline(path, source):
    if path.suffix.lower() == ".json":
        value = json.loads(source)
        items = value.items() if isinstance(value, dict) else [("root", value)]
        for key, item in items:
            count = f" [{len(item)}]" if isinstance(item, (dict, list)) else ""
            yield f"{key}: {type(item).__name__}{count}"
    elif path.suffix.lower() == ".py":
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                yield f"{node.lineno}: {node.name}"
    else:
        for n, line in enumerate(source.splitlines(),1):
            if re.match(r"^\s*(?:export\s+)?(?:async\s+)?(?:function|class)\s+\w+|^\s*export\s+(?:let|const)\s+\w+|^\s*<script\b", line):
                yield f"{n}: {line.strip()[:125]}"


def main():
    sys.stdout.reconfigure(encoding="utf8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file",type=Path)
    parser.add_argument("--line", type=int, help="first line of an excerpt")
    parser.add_argument("--offset", type=int, default=0, help="character offset within first line")
    parser.add_argument("--find", help="show matching line numbers")
    args = parser.parse_args()
    if (args.line is not None and args.line < 1) or args.offset < 0:
        parser.error("line must be positive and offset nonnegative")
    source = args.file.read_text(encoding="utf-8-sig")
    lines = source.splitlines()
    if args.line is not None:
        rows = (f"{n}: {lines[n-1][args.offset if n==args.line else 0:]}" for n in range(args.line,len(lines)+1))
    elif args.find:
        rows = (f"{n}: {line.strip()[:150]}" for n,line in enumerate(lines,1) if args.find in line)
    else:
        rows = outline(args.file,source)
    result = [f"{args.file.name[:120]} | {len(lines)} lines | {len(source)} characters"]
    remaining = BUDGET - len(result[0]) - 35
    for row in rows:
        if len(row)+1 > remaining:
            if remaining > 1:
                result.append(row[:remaining-1])
            result.append("… use --line N [--offset K]")
            break
        result.append(row)
        remaining -= len(row)+1
    print("\n".join(result))


if __name__ == "__main__":
    main()
