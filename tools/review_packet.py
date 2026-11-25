"""Render selected native frames and emit one model-sized review sheet."""
import argparse
import json
import os
import re
import shutil
from collections import defaultdict
from math import isfinite
from pathlib import Path
import subprocess
import tempfile
import time

from PIL import Image, ImageDraw, ImageOps


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("renderer",type=Path)
    parser.add_argument("html",type=Path,nargs="?")
    parser.add_argument("--picture",type=Path,help="decode samples from an existing local video")
    parser.add_argument("--manifest",type=Path,help="JSON list of {source,time}, relative to this file")
    parser.add_argument("--times",help="one to four times in seconds, comma separated")
    parser.add_argument("--variants",nargs="+",help="named candidates at the same time, using setReviewVariant(id)")
    parser.add_argument("--min-spread",type=float)
    parser.add_argument("--max-clipped",type=float)
    parser.add_argument("--preset",choices=["draft","hd","qhd","uhd"],default="uhd")
    parser.add_argument("--roi",nargs=4,type=float,metavar=("X","Y","W","H"),
                        help="optional normalized native-resolution detail crop")
    parser.add_argument("--out",required=True,type=Path,help="output JPEG sheet")
    parser.add_argument("--native-out",type=Path,help="also keep the native PNG samples on disk")
    args=parser.parse_args()
    try:
        if args.picture:
            if args.html or args.manifest or args.variants or args.times is None:
                parser.error("use --picture FILE with --times and no scene variants")
            if not args.picture.is_file():
                parser.error("picture not found")
            samples=[(args.picture.resolve(),float(t)) for t in args.times.split(",")]
        elif args.manifest:
            if args.html or args.times is not None or args.variants:
                parser.error("choose manifest or HTML and times")
            rows=json.loads(args.manifest.read_text(encoding="utf-8-sig"))
            samples=[((args.manifest.parent/row["source"]).resolve(),float(row["time"])) for row in rows]
        else:
            if not args.html or args.times is None:
                parser.error("supply HTML plus --times, or --manifest")
            samples=[(args.html.resolve(),float(x)) for x in args.times.split(",")]
    except (KeyError,TypeError,ValueError,OSError) as exc:
        parser.error(f"invalid samples: {exc}")
    times=[t for _,t in samples]
    if not 1<=len(times)<=4 or not all(isfinite(t) and t>=0 for t in times):
        parser.error("use one to four finite nonnegative times")
    if len(set(samples))!=len(samples):
        parser.error("duplicate samples")
    if args.variants:
        if (len(samples)!=1 or not 2<=len(args.variants)<=4 or len(set(args.variants))!=len(args.variants)
            or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,32}",name) for name in args.variants)):
            parser.error("supply one common time and two to four distinct candidate names")
        samples *= len(args.variants)
        times *= len(args.variants)
    for threshold in (args.min_spread,args.max_clipped):
        if threshold is not None and not 0<=threshold<=1:
            parser.error("thresholds must be between zero and one")
    if args.roi:
        x,y,w,h=args.roi
        if not all(map(isfinite,args.roi)) or min(x,y)<0 or min(w,h)<=0 or x+w>1 or y+h>1:
            parser.error("ROI must fit the normalized frame")

    then=time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="codefilm-review-") as folder:
        if args.native_out and args.native_out.exists():
            parser.error("--native-out must be a new directory")
        groups=defaultdict(list)
        for i,(path,t) in enumerate(samples):
            groups[path].append((i,t))
        paths={}
        native_size=None
        for group_number,(path,entries) in enumerate(groups.items(),1):
            native=Path(folder)/str(group_number)
            log=Path(folder)/"worker.log"
            variant_flags=[]
            if args.variants:
                choices=Path(folder)/"variants.json"
                choices.write_text(json.dumps(args.variants),encoding="utf8")
                variant_flags=["--variant-stills",str(choices)]
            if args.picture:
                native.mkdir()
                for j,(_,timecode) in enumerate(entries,1):
                    frame=native/f"frame-{j:02d}.png"
                    result=subprocess.run([os.environ.get("FFMPEG_PATH","ffmpeg"),"-v","error",
                        "-ss",str(timecode),"-i",str(path),"-map","0:v:0","-frames:v","1",str(frame)],
                        capture_output=True)
                    if result.returncode or not frame.is_file():
                        parser.exit(1,f"no picture frame at {timecode:g}s\n"+
                                    result.stderr[-500:].decode("utf8","replace"))
                with Image.open(native/"frame-01.png") as first:
                    native_size=list(first.size)
            else:
                with log.open("w",encoding="utf8") as stream:
                    result=subprocess.run(["node",str(args.renderer),str(path),"--timeline","--quiet",
                        "--stills",",".join(str(t) for _,t in entries),"--preset",args.preset,
                        "--out",str(native),*variant_flags],stdout=stream,stderr=subprocess.STDOUT)
                if result.returncode:
                    with log.open("rb") as stream:
                        stream.seek(max(0,log.stat().st_size-1200))
                        print(stream.read().decode("utf8","replace"))
                    return result.returncode
                metadata=json.loads((native/"stills.json").read_text(encoding="utf8"))
                native_size=[metadata["width"],metadata["height"]]
            for j,(i,_) in enumerate(entries,1):
                paths[i]=native/f"frame-{j:02d}.png"
        cell_w,cell_h=480,292
        columns=min(2,len(times))
        rows=(len(times)+columns-1)//columns
        sheet=Image.new("RGB",(cell_w*columns,cell_h*rows*(2 if args.roi else 1)),(17,20,24))
        draw=ImageDraw.Draw(sheet)
        diagnostics=[]
        for i,t in enumerate(times):
            left=(i%columns)*cell_w
            top=(i//columns)*cell_h*(2 if args.roi else 1)
            with Image.open(paths[i]) as original:
                width,height=original.size
                whole=ImageOps.contain(original,(480,270),Image.Resampling.LANCZOS)
                sheet.paste(whole,(left+(cell_w-whole.width)//2,top))
                label=args.variants[i] if args.variants else str(i+1)
                clock="video" if args.picture else "local"
                draw.text((left+8,top+273),f"{label} | {t:.3f}s {clock} | full frame",fill="white")
                crop=original
                if args.roi:
                    crop=original.crop((int(x*width),int(y*height),int((x+w)*width+0.999999),
                                        int((y+h)*height+0.999999)))
                    detail=ImageOps.contain(crop,(480,270),Image.Resampling.LANCZOS)
                    sheet.paste(detail,(left+(cell_w-detail.width)//2,top+cell_h))
                    draw.text((left+8,top+cell_h+273),f"{t:.3f}s | region {crop.width}x{crop.height}",fill="white")
                if args.variants or args.min_spread is not None or args.max_clipped is not None:
                    histogram=crop.convert("L").histogram()
                    count=sum(histogram)
                    def quantile(fraction):
                        acc=0
                        for gray,frequency in enumerate(histogram):
                            acc+=frequency
                            if acc>=count*fraction:
                                return gray
                    spread=(quantile(.9)-quantile(.1))/255
                    clipped=(sum(histogram[:3])+sum(histogram[-3:]))/count
                    diagnostics.append(dict(sample=label,spread=round(spread,3),
                        clipped=round(clipped,3),eligible=(spread>=(args.min_spread or 0) and
                            clipped<=(args.max_clipped if args.max_clipped is not None else 1))))
        args.out.parent.mkdir(parents=True,exist_ok=True)
        sheet.save(args.out,format="JPEG",quality=89)
        if args.native_out:
            args.native_out.mkdir(parents=True)
            for i,frame in sorted(paths.items()):
                with (args.native_out/f"frame-{i+1:02d}.png").open("xb") as target, frame.open("rb") as source:
                    shutil.copyfileobj(source,target)
    print(json.dumps({"sheet":str(args.out),"samples":times,
                      "native":native_size,
                      "seconds":round(time.perf_counter()-then,2),
                      **({"nativeFrames":str(args.native_out)} if args.native_out else {}),
                      **({"diagnostics":diagnostics} if diagnostics else {})},ensure_ascii=False))
    return int(bool(diagnostics) and not any(row["eligible"] for row in diagnostics))


if __name__=="__main__":
    raise SystemExit(main())
