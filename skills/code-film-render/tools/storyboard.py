"""Find a feasible causal storyboard without sampling images or calling a model."""
import argparse
from fractions import Fraction
from itertools import combinations
import json
from math import ceil, floor, isfinite
from pathlib import Path


def facts(values, label):
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ) or len(set(values)) != len(values):
        raise ValueError(f"{label}: expected unique, nonempty fact labels")
    return set(values)


def solve(document):
    brief = document["brief"].strip()
    required = facts(document["goals"], "goals")
    starting = facts(document.get("initial", []), "initial")
    fps = document.get("fps", 24)
    duration = Fraction(str(document["seconds"]))
    if not brief or not required or required & starting or type(fps) is not int or fps <= 0 or duration <= 0:
        raise ValueError("need brief, positive duration/fps and goals shown on screen")
    target = round(duration * fps)
    rows = document["beats"]
    cap = document.get("maxShots", len(rows))
    if not 1 <= len(rows) <= 16 or type(cap) is not int or cap<1:
        raise ValueError("use 1–16 ordered candidates per sequence and positive maxShots")

    grouped=any("setup" in beat for beat in rows)
    seen_ids=set()
    beats=[]
    rejected=[]
    for beat in rows:
        identifier = beat["id"]
        if not isinstance(identifier, str) or not identifier.strip() or identifier in seen_ids:
            raise ValueError("candidate IDs must be unique")
        seen_ids.add(identifier)
        anchor = beat["based_on"].strip()
        if not anchor or anchor not in brief or not beat["visible"].strip():
            raise ValueError(f"{identifier}: supply an exact brief quote and visible action")
        minimum = ceil(Fraction(str(beat["minSeconds"])) * fps)
        maximum = floor(Fraction(str(beat["maxSeconds"])) * fps)
        if not 1 <= minimum <= maximum:
            raise ValueError(f"{identifier}: invalid screen-time range at {fps} fps")
        reveals=facts(beat["reveals"],identifier)
        setup=beat.get("setup",identifier)
        if not isinstance(setup,str) or not setup.strip():
            raise ValueError(f"{identifier}: give this continuous view a setup name")
        for label,observation in beat.get("view",{}).items():
            pixels,needed=observation["pixels"],observation["minPixels"]
            if label not in reveals or not all(map(isfinite,(pixels,needed))) or pixels<0 or needed<=0:
                raise ValueError(f"{identifier}: invalid view evidence for {label}")
            if pixels<needed:
                reveals.remove(label)
                rejected.append(dict(beat=identifier,label=label,pixels=pixels,minPixels=needed))
        beats.append(({**beat,"setup":setup},facts(beat.get("requires",[]),identifier),
                      reveals,minimum,maximum))

    best = None
    limit=len(beats) if grouped else min(cap,len(beats))
    for count in range(1,limit+1):
        for sequence in combinations(beats,count):
            setups=[beat["setup"] for beat,*_ in sequence]
            shots=1+sum(a!=b for a,b in zip(setups,setups[1:]))
            if shots>cap or (best and shots>best[0][0]):
                continue
            minimum = sum(beat[3] for beat in sequence)
            maximum = sum(beat[4] for beat in sequence)
            if not minimum<=target<=maximum:
                continue
            known = starting.copy()
            for _, needs, reveals, _, _ in sequence:
                if not needs<=known:
                    break
                known |= reveals
            else:
                if not required<=known:
                    continue
                needed = required.copy()
                for _, needs, reveals, _, _ in reversed(sequence):
                    if not needed & reveals:
                        break
                    needed = (needed-reveals)|needs
                else:
                    if needed<=starting:
                        excess = len(known-required-starting)
                        # Fewer unrelated facts first, then a larger readability budget.
                        rank=(shots,excess,minimum,count)
                        if best is None or rank<best[0]:
                            best = rank, sequence, minimum, maximum
        if best and not grouped:
            break
    if best is None:
        attainable = starting.copy()
        for _, needs, reveals, _, _ in beats:
            if needs<=attainable:
                attainable |= reveals
        missing = sorted(required-attainable)
        if missing:
            return {"status":"blocked","missing":missing[:6],"viewFailures":rejected[:6],
                    "action":"Add a readable on-screen reveal after its prerequisites."}
        return {"status":"blocked","action":"No causal sequence fits the time/shot limits; revise candidate ranges or combine related events."}

    _, sequence, minimum, maximum = best
    slack = target-minimum
    capacity = maximum-minimum
    cursor = weight = distributed = 0
    shots=[]
    for beat,_,reveals,shortest,longest in sequence:
        weight+=longest-shortest
        share=round(Fraction(slack*weight,capacity)) if capacity else 0
        frames=shortest+share-distributed
        phase=dict(id=beat["id"],startFrame=cursor,frames=frames,seconds=frames/fps,
                   based_on=beat["based_on"],visible=beat["visible"])
        if not grouped:
            shots.append(phase)
        else:
            phase["reveals"]=sorted(reveals)
            if shots and shots[-1]["setup"]==beat["setup"]:
                shot=shots[-1]
                shot["beats"].append(phase)
                shot["frames"]+=frames
                shot["seconds"]=shot["frames"]/fps
                shot["visible"]+=" / "+phase["visible"]
            else:
                shot=dict(**phase,setup=beat["setup"],beats=[phase])
                if shots:
                    shot["cutReason"]=beat.get("cutReason") or (
                        "show "+", ".join(sorted(reveals)))
                shots.append(shot)
        cursor+=frames
        distributed=share
    result=dict(status="ready",brief=brief,fps=fps,frames=cursor,shots=shots)
    if grouped:
        result["cuts"]=len(shots)-1
        result["viewFailures"]=rejected[:6]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec",type=Path)
    parser.add_argument("--out",required=True,type=Path)
    args = parser.parse_args()
    try:
        result = solve(json.loads(args.spec.read_text(encoding="utf-8-sig")))
        args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    except (ValueError,TypeError,AttributeError,KeyError,OSError,OverflowError,ZeroDivisionError) as exc:
        parser.exit(2,str(exc)[:400]+"\n")
    if result["status"]!="ready":
        print(json.dumps(result,ensure_ascii=False)[:550])
        return 1
    print(f"{len(result['shots'])} shots | {result['frames']} frames | {args.out}")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
