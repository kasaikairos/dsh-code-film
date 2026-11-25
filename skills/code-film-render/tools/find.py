"""Bounded filename/line lookup in authored source; full output stays off the chat."""
import argparse
import os
from pathlib import Path
ap=argparse.ArgumentParser()
ap.add_argument("root",type=Path)
ap.add_argument("query")
ap.add_argument("--offset",type=int,default=0)
args=ap.parse_args()
if not args.root.is_dir() or not args.query.strip() or args.offset<0:
    ap.error("expected a directory, non-empty search term and nonnegative offset")
skip={"node_modules","vendor","out","deliver",".git","__pycache__","venv","wheels"}
count=0
query=args.query.casefold()
for folder,dirs,files in os.walk(args.root):
    dirs[:]=sorted(d for d in dirs if not d.startswith(".") and d not in skip)
    for name in sorted(files):
        p=Path(folder)/name
        if p.suffix.lower() not in {".md",".js",".html",".mjs",".py",".css",".json",".ps1"} or name=="package-lock.json":
            continue
        with p.open(encoding="utf-8-sig",errors="replace") as f:
            for line,text in enumerate(f,1):
                if query not in text.casefold():
                    continue
                if count==args.offset+8:
                    print("more: --offset",count)
                    raise SystemExit
                if count>=args.offset:
                    print(f"{p.relative_to(args.root).as_posix()[:150]}:{line} {text.strip()[:100]}")
                count+=1
if count<=args.offset:
    print("no further matches")
