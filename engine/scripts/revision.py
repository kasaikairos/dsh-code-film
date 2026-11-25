"""Render a time range of one shot or replace a finished film's audio locally."""
import argparse
from fractions import Fraction
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent


def run(args, log):
    subprocess.run(list(map(str, args)), check=True, stdout=log, stderr=subprocess.STDOUT)


def probe(path, selector):
    streams = json.loads(subprocess.check_output(["ffprobe","-v","error","-select_streams",selector,
        "-show_entries","stream=duration","-of","json",str(path)]))["streams"]
    return float(streams[0]["duration"])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="mode", required=True)
    audio = sub.add_parser("audio")
    audio.add_argument("--picture", required=True, type=Path)
    audio.add_argument("--track", required=True, type=Path)
    shot = sub.add_parser("shot")
    shot.add_argument("--plan", required=True, type=Path)
    shot.add_argument("--shot", required=True, type=int)
    shot.add_argument("--start", type=float, default=0)
    shot.add_argument("--seconds", type=float, required=True)
    shot.add_argument("--fps", type=int, default=24)
    shot.add_argument("--preset", choices=["draft","hd","qhd","uhd"], default="uhd")
    for parser in (shot,audio):
        parser.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=a.out.parent) as tmp, a.out.with_suffix(".revision.log").open("w",encoding="utf8") as log:
        final = Path(tmp).resolve()/"final.mp4"
        if a.mode=="audio":
            if a.out.resolve() in (a.picture.resolve(), a.track.resolve()):
                ap.error("choose a new output path")
            duration = probe(a.picture,"v:0")
            if probe(a.track,"a:0")+0.025 < duration:
                ap.error("track too short")
            run(["ffmpeg","-v","error","-i",a.picture,"-i",a.track,"-map","0:v:0","-map","1:a:0",
                 "-map","0:s?","-c","copy","-c:a","aac","-b:a","192k","-t",duration,
                 "-movflags","+faststart",final],log)
        else:
            shots = json.loads(a.plan.read_text(encoding="utf-8-sig"))["shots"]
            if not 1<=a.shot<=len(shots) or a.fps<=0 or a.start<0 or a.seconds<=0:
                ap.error("invalid shot or time range")
            item=shots[a.shot-1]
            first=round(a.start*a.fps)
            elapsed = sum(Fraction(str(s["seconds"])) for s in shots[:a.shot-1])
            length = round((elapsed+Fraction(str(item["seconds"])))*a.fps) - round(elapsed*a.fps)
            end=min(round((a.start+a.seconds)*a.fps),length)
            if end<=first: ap.error("empty frame range")
            src=(a.plan.parent/item["source"]).resolve()
            opts=["--fps",a.fps,"--start",first,"--end",end,"--frames",end-first,"--out",final,"--preset",a.preset,"--quiet"]
            if src.suffix.lower()==".html":
                run(["node",HERE/"render_html.mjs",src,*opts],log)
            else:
                spec=json.loads(src.read_text(encoding="utf-8-sig"))
                spec["duration"]=length/a.fps
                emo=(spec.get("emotion") or {}).get("src")
                if emo: spec["emotion"]["src"]=str((src.parent/emo).resolve())
                staged=Path(tmp)/"shot.json"
                staged.write_text(json.dumps(spec),encoding="utf8")
                run([sys.executable,HERE/"render_spec.py","--spec",staged,*opts],log)
        os.replace(final,a.out)
    print(a.out)


if __name__=="__main__":
    main()
