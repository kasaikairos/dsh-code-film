"""Choose fixed or moving camera paths for authored dramatic beats."""
import argparse
import json
from math import cos, dist, isfinite, radians, sin, tan
from pathlib import Path


def vector(values):
    if len(values) != 3 or not all(map(isfinite, values)):
        raise ValueError("expected three finite coordinates")
    return tuple(values)


def dot(a, b):
    return sum(x*y for x,y in zip(a,b))


def blocked(camera, point, boxes):
    # Ray segment from the camera to the point. Boxes represent opaque blockers.
    for lo, hi in boxes:
        enter, leave = 0, 1-1e-7
        for origin, end, low, high in zip(camera, point, lo, hi):
            direction = end-origin
            if abs(direction)<1e-10:
                if not low<=origin<=high:
                    enter, leave = 1, 0
                    break
                continue
            a,b = sorted(((low-origin)/direction,(high-origin)/direction))
            enter,leave = max(enter,a),min(leave,b)
            if enter>leave:
                break
        if enter<=leave:
            return True
    return False


LENS=("az","el","dist","fov")


def valid_lens(preset):
    az,el,distance,fov=(preset[key] for key in LENS)
    return all(map(isfinite,(az,el,distance,fov))) and distance>0 and abs(el)<89 and 1<=fov<=150


def path_keys(beat,preset):
    start={**{key:preset[key] for key in LENS},"t":beat["t"],
           "target":vector(beat["target"]),"focus":preset["dist"],"cut":True}
    move=beat.get("move")
    if not move:
        return [start]
    finish={**start,"t":move["end"],"cut":False,
            "target":vector(move.get("target",start["target"])),
            "az":start["az"]+move.get("azDelta",0),"el":start["el"]+move.get("elDelta",0),
            "dist":start["dist"]*move.get("distScale",1)}
    finish["focus"]=finish["dist"]
    if not valid_lens(finish):
        return []
    begins=move.get("start",start["t"])
    return [start,*([{**start,"t":begins,"cut":False}] if begins>start["t"] else []),finish]


def lens_at(keys,time):
    if len(keys)==1:
        return keys[0]
    start,finish=keys[-2:]
    u=max(0,min(1,(time-start["t"])/(finish["t"]-start["t"])))
    u=u*u*(3-2*u)
    def blend(a,b):
        return a+(b-a)*u
    return {**{key:blend(start[key],finish[key]) for key in LENS},
            "target":tuple(map(blend,start["target"],finish["target"]))}


def projected_span(sample,lens,aspect,margin):
    target=lens["target"]
    az,el,distance,fov=(lens[key] for key in LENS)
    a,e = radians(az),radians(el)
    outward = (sin(a)*cos(e),sin(e),cos(a)*cos(e))
    right = (cos(a),0,-sin(a))
    up = (-sin(a)*sin(e),cos(e),-cos(a)*sin(e))
    camera = tuple(x+distance*d for x,d in zip(target,outward))
    near = max(.004,min(.1,distance*.08))
    focal = tan(radians(fov/2))
    boxes=[(vector(lo),vector(hi)) for lo,hi in sample.get("boxes",[])]
    if any(any(a>=b for a,b in zip(lo,hi)) for lo,hi in boxes):
        raise ValueError("occluder boxes need positive extent on all axes")
    points=[]
    for xyz in sample["points"]:
        point=vector(xyz)
        offset=tuple(x-c for x,c in zip(point,camera))
        depth=-dot(offset,outward)
        if not near<depth<max(60,distance*40) or blocked(camera,point,boxes):
            return None
        x=.5+.5*dot(offset,right)/(depth*focal*aspect)
        y=.5-.5*dot(offset,up)/(depth*focal)
        if not (margin<=x<=1-margin and margin<=y<=1-margin):
            return None
        points.append((x,y))
    width=max(x for x,y in points)-min(x for x,y in points)
    height=max(y for x,y in points)-min(y for x,y in points)
    return max(width,height)


def evaluate(beat, keys, aspect):
    if not keys:
        return None
    positions=[]
    for sample in beat["samples"]:
        lens=lens_at(keys,sample.get("t",beat["t"]))
        size=projected_span(sample,lens,aspect,beat.get("margin",.06))
        if size is None:
            return None
        positions.append(size)
    span=beat.get("span",.55)
    return sum(abs(size-span) for size in positions)/len(positions)


def link_board(document,board):
    if board.get("status")!="ready" or not board.get("shots"):
        raise ValueError("use a ready storyboard")
    fps=board["fps"]
    authored={beat["shot"]:beat for beat in document["beats"]}
    if len(authored)!=len(document["beats"]):
        raise ValueError("each storyboard shot can have one camera brief")
    selected=[]
    for shot in board["shots"]:
        name=shot["id"]
        if name not in authored:
            raise ValueError(f"missing camera brief for storyboard shot {name}")
        beat={**authored.pop(name),"t":shot["startFrame"]/fps,
              "until":(shot["startFrame"]+shot["frames"])/fps}
        if beat.get("move"):
            move={**beat["move"]}
            move.setdefault("end",(shot["startFrame"]+shot["frames"]-1)/fps)
            beat["move"]=move
        selected.append(beat)
    if authored:
        raise ValueError("camera briefs contain shots absent from the selected storyboard")
    return {**document,"beats":selected}


def decide(document):
    aspect=document.get("aspect",16/9)
    transition=document.get("continuity",.35)
    if not isfinite(aspect) or aspect<=0 or not isfinite(transition) or transition<0:
        raise ValueError("invalid aspect or continuity")
    cameras=document["candidates"]
    if not cameras or not document["beats"]:
        raise ValueError("need candidates and beats")
    for camera in cameras:
        if not valid_lens(camera):
            raise ValueError("invalid candidate")
    costs,parents={},[]
    previous_paths={}
    last=-1
    beats=document["beats"]
    for index,beat in enumerate(beats):
        t=beat["t"]
        if not isfinite(t) or t<0 or t<=last:
            raise ValueError("beat times must be increasing")
        last=t
        if not beat["samples"] or any(len(s["points"])<2 for s in beat["samples"]):
            raise ValueError("need at least two visible points per sample")
        if not 0<=beat.get("margin",.06)<.5 or not 0<beat.get("span",.55)<=1:
            raise ValueError("invalid composition margins or span")
        until=beat.get("until",beats[index+1]["t"] if index+1<len(beats) else float("inf"))
        move=beat.get("move")
        if move:
            end=move["end"]
            begins=move.get("start",t)
            times=[sample["t"] for sample in beat["samples"]]
            if not (isfinite(end) and t<=begins<end<until and
                    all(isfinite(time) and t<=time<until for time in times) and
                    any(abs(time-begins)<=1e-7 for time in times) and any(abs(time-end)<=1e-7 for time in times)
                    and any(begins<time<end for time in times)):
                raise ValueError(f"{t:g}s: sample the start, middle and end of the move inside the shot")
        layer,links,paths={},{},{}
        for i,camera in enumerate(cameras):
            path=path_keys(beat,camera)
            score=evaluate(beat,path,aspect)
            if score is None:
                continue
            if costs:
                def total(j):
                    prior=previous_paths[j][-1]
                    difference=abs((camera["az"]-prior["az"]+180)%360-180)
                    return costs[j]+transition*(difference/180+
                        abs(camera["el"]-prior["el"])/180)
                j=min(costs,key=total)
                score+=total(j)
                links[i]=j
            layer[i]=score
            paths[i]=path
        if not layer:
            raise ValueError(f"no feasible camera at {t}s: check target, points, occluders or candidates")
        costs=layer
        previous_paths=paths
        parents.append((links,paths))
    choice=min(costs,key=costs.get)
    final_cost=costs[choice]
    keys=[]
    for links,paths in reversed(parents):
        keys.extend(reversed(paths[choice]))
        choice=links.get(choice)
    return {"cost":round(final_cost,5),"keys":keys[::-1]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input",type=Path)
    parser.add_argument("--board",type=Path,help="use selected shot ids and times from storyboard output")
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    try:
        document=json.loads(args.input.read_text(encoding="utf-8-sig"))
        if args.board:
            document=link_board(document,json.loads(args.board.read_text(encoding="utf-8-sig")))
        result=decide(document)
        args.out.write_text(json.dumps(result,indent=2)+"\n",encoding="utf8")
    except (ValueError,KeyError,TypeError,OSError) as exc:
        parser.exit(1,str(exc)[:500]+"\n")
    print(f"{len(result['keys'])} camera keys | cost {result['cost']} | {args.out}")


if __name__=="__main__":
    main()
