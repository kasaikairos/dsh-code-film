"""Audit an authored shot's actual sampled pose against its own motion intent."""
import argparse
import json
import math
import subprocess
import sys
from pathlib import Path


def audit(spec, samples, fps):
    checks = spec["checks"]
    if not checks or not samples:
        raise ValueError("need checks and samples")
    findings = []
    for check in checks:
        kind = check["kind"]
        start, end = check.get("interval", [0, (len(samples)-1)/fps])
        if not all(map(math.isfinite,(start,end))) or start < 0 or start > end:
            raise ValueError("invalid check interval")
        values = []
        limit = check["limit"]
        if not math.isfinite(limit) or limit < 0:
            raise ValueError("invalid tolerance")
        floor=check.get("speedFloor") if kind=="activity" else None
        if kind=="activity" and (limit>1 or not isinstance(floor,(int,float)) or not math.isfinite(floor) or floor<=0):
            raise ValueError("activity needs a positive speedFloor and a limit from zero to one")
        previous = None
        velocity = None
        baseline = None
        for frame, pose in enumerate(samples):
            if not start <= frame/fps <= end:
                continue
            a = pose[check["point"]]
            if len(a) not in (2,3) or not all(map(math.isfinite,a)):
                raise ValueError("invalid sampled point")
            if kind in ("speed","velocity_jump","activity"):
                if kind in ("velocity_jump","activity") and "relative_to" in check:
                    b=pose[check["relative_to"]]
                    if len(a)!=len(b) or not all(map(math.isfinite,b)):
                        raise ValueError("incompatible motion reference")
                    a=[u-v for u,v in zip(a,b)]
                if previous is not None:
                    step=[(u-v)*fps for u,v in zip(a,previous)]
                    if kind in ("speed","activity"):
                        values.append((math.hypot(*step),frame))
                    elif velocity is not None:
                        values.append((math.dist(step,velocity),frame-1))
                    velocity=step
                previous = a
            elif kind in ("intrinsic_travel","hold"):
                anchors = check.get("anchors", [])
                if kind=="hold" and not anchors:
                    if baseline is None:
                        baseline=a
                    values.append((math.dist(a,baseline),frame))
                    continue
                if len(anchors)<2 or len(set(anchors))!=len(anchors):
                    raise ValueError("use distinct landmarks, at least two")
                refs=[pose[name] for name in anchors]
                if any(len(b)!=len(a) or not all(map(math.isfinite,b)) for b in refs):
                    raise ValueError("incompatible sampled landmarks")
                scale=math.dist(*refs[:2])
                if scale<=1e-9:
                    raise ValueError("first two landmarks must be separated")
                signature=[math.dist(a,b)/scale for b in refs]
                if baseline is None:
                    baseline=signature
                values.append((math.dist(signature,baseline),frame))
            elif kind in ("attachment","relative_travel"):
                b = pose[check["relative_to"]]
                if len(b)!=len(a) or not all(map(math.isfinite,b)):
                    raise ValueError("incompatible sampled points")
                delta = [x-y for x,y in zip(a,b)]
                if baseline is None:
                    baseline = delta
                amount = math.dist(delta,baseline) if kind=="relative_travel" else math.dist(a,b)
                values.append((amount,frame))
            else:
                raise ValueError("unknown kind: "+kind)
        if not values or (kind in ("relative_travel","intrinsic_travel","hold") and len(values)<2):
            raise ValueError("check interval too short")
        if kind=="activity":
            active=sum(speed>=floor for speed,_ in values)
            fraction=active/len(values)
            findings.append(dict(check=check["name"],passed=fraction>=limit,activeRatio=round(fraction,5),
                                 activeFrames=active,sampledFrames=len(values),limit=limit))
            continue
        amount, frame = max(values,key=lambda x:x[0])
        passed = amount>=limit if kind in ("relative_travel","intrinsic_travel") else amount<=limit
        findings.append(dict(check=check["name"],passed=passed,peak=round(amount,5),
                             frame=frame,time=round(frame/fps,4),limit=limit))
    return findings


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("module",type=Path)
    args=ap.parse_args()
    js="""import {pathToFileURL} from 'node:url';
const {motionSpec:s, poseAt} = await import(pathToFileURL(process.argv[1]));
if (!(Number.isFinite(s.fps)&&s.fps>0&&Number.isSafeInteger(s.frames)&&s.frames>0)) throw Error('invalid fps/frames');
const samples=Array.from({length:s.frames},(_,i)=>poseAt(i/s.fps));
process.stdout.write(JSON.stringify({s,samples}));"""
    result=subprocess.run(["node","--input-type=module","-e",js,str(args.module.resolve())],
                          capture_output=True,encoding="utf8")
    if result.returncode:
        sys.exit(result.stderr[-1200:])
    data=json.loads(result.stdout)
    findings=audit(data["s"],data["samples"],data["s"]["fps"])
    for row in findings:
        print(json.dumps(row,ensure_ascii=False))
    return int(any(not row["passed"] for row in findings))

if __name__=="__main__":
    sys.exit(main())
