"""Compact handoff for an existing film; never reads scene source or tool logs."""
import argparse
from fractions import Fraction
import json
from pathlib import Path
import render_job


def short(value, limit):
    return " ".join(str(value).split())[:limit]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--out", type=Path, help="same final output path as cut.py")
    parser.add_argument("--shot",type=int,help="return the current shot and only its adjacent shot labels")
    parser.add_argument("--fps",type=int,help="include frame positions at the delivery rate")
    a = parser.parse_args()
    plan = json.loads(a.plan.read_text(encoding="utf-8-sig"))
    shots = plan["shots"]
    seconds = sum(float(s["seconds"]) for s in shots)
    lines = [f'{short(plan.get("title",""),100)} | {len(shots)} shots | {seconds:g}s',
             f'plan: {a.plan.resolve()}']
    if a.out:
        state = render_job.read(a.out.resolve())
        lines.append("job: " + json.dumps(state, ensure_ascii=False)[:400])
    if plan.get("soundtrack"):
        lines.append("soundtrack: " + short(plan["soundtrack"],100))
    if a.shot is not None:
        if not 1<=a.shot<=len(shots) or (a.fps is not None and a.fps<=0):
            parser.error("provide a valid shot number and positive fps")
        shot=shots[a.shot-1]
        start=sum(Fraction(str(s["seconds"])) for s in shots[:a.shot-1])
        end=start+Fraction(str(shot["seconds"]))
        lines.append(f"shot {a.shot} | {float(start):.3f}–{float(end):.3f}s")
        if a.fps:
            lines.append(f"frames [{round(start*a.fps)}, {round(end*a.fps)}) @ {a.fps} fps")
        for key,limit in (("source",180),("based_on",360),("visible",280),("review",200),("next",160)):
            if key in shot:
                lines.append(key+" "+short(shot[key],limit))
        if a.shot>1:
            lines.append("previous "+short(shots[a.shot-2].get("visible",""),100))
        if a.shot<len(shots):
            lines.append("next shot "+short(shots[a.shot].get("visible",""),100))
        print("\n".join(lines))
        return
    budget = 2200
    for i, shot in enumerate(shots,1):
        src = Path(shot["source"])
        exists = (a.plan.parent / src).is_file()
        line = f'{i:02d} {float(shot["seconds"]):g}s {"source" if exists else "missing"} {short(src,75)} | {short(shot.get("visible",""),42)}'
        if sum(map(len, lines)) + len(line) + len(lines) + 60 > budget:
            lines.append(f'... {len(shots)-i+1} more in plan')
            break
        lines.append(line)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
