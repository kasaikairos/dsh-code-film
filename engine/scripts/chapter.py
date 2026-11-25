"""Read a single chapter brief in bounded pages; never enumerate other briefs."""
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("brief", type=Path)
parser.add_argument("--offset", type=int, default=0)
args = parser.parse_args()
if args.offset < 0:
    parser.error("offset must be nonnegative")
with args.brief.open(encoding="utf-8-sig") as source:
    source.read(args.offset)
    block = source.read(1800)
    more = source.read(1)
print(block)
if more:
    print(f"[continue only if needed: --offset {args.offset+len(block)}]")
