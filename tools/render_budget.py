"""Sample multiple timeline intervals in one browser."""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile


def run_probes(args, ranges, output, folder, *, html=None, shot=None, holds=None):
    folder.mkdir(exist_ok=True)
    manifest=folder/"ranges.json"
    manifest.write_text(json.dumps(ranges),encoding="utf8")
    metrics=folder/"metrics.json"
    log=folder/"render.log"
    with log.open("w",encoding="utf8") as file:
        result=subprocess.run([
            "node",str(args.renderer),str(html or args.html),"--timeline","--quiet",
            "--preset",args.preset,"--encpreset",args.encpreset,"--crf",str(args.crf),
            "--codec",args.codec,"--blur",str(args.blur),
            *(["--canvas-only"] if args.canvas_only else []),
            *(["--shot",shot or args.shot] if shot or args.shot else []),
            *(["--holds",str(holds or args.holds)] if holds or args.holds else []),
            "--fps",str(args.fps),"--ranges",str(manifest),"--metrics",str(metrics),
            "--out",str(output)
        ],stdout=file,stderr=subprocess.STDOUT)
    if result.returncode:
        with log.open("rb") as file:
            file.seek(max(0,log.stat().st_size-1200))
            raise ValueError(file.read().decode("utf8","replace").strip())
    return json.loads(metrics.read_text(encoding="utf8"))


def probe_ranges(args):
    samples=[args.seconds,args.probe,*args.starts]
    if not all(map(math.isfinite,samples)) or min(args.seconds,args.probe)<=0 or min(args.starts)<0:
        raise ValueError("invalid times")
    if args.cap_minutes is not None and (not math.isfinite(args.cap_minutes) or args.cap_minutes<=0):
        raise ValueError("invalid cap")
    total=round(args.seconds*args.fps)
    frames=round(args.probe*args.fps)
    starts=sorted(set(round(t*args.fps) for t in args.starts))
    if not 1<=len(starts)<=12 or frames<=0 or max(starts)+frames>total:
        raise ValueError("provide up to 12 probes inside the timeline")
    return total,[dict(start=start,frames=frames) for start in starts]


def budget(args, folder):
    total,ranges=probe_ranges(args)
    metrics=run_probes(args,ranges,folder/"probe.mp4",folder)
    slowest=max(row["seconds"]/row["frames"] for row in metrics["ranges"])
    estimate=metrics["setupSeconds"]+slowest*total+metrics["drainSeconds"]
    over=args.cap_minutes is not None and estimate>args.cap_minutes*60
    print(json.dumps(dict(
        startupSeconds=round(metrics["setupSeconds"],2),drainSeconds=round(metrics["drainSeconds"],2),
        probes=[dict(startSeconds=row["start"]/args.fps,wallSeconds=round(row["seconds"],2))
                for row in metrics["ranges"]],
        projectedSeconds=round(estimate,1),overBudget=over)))
    return int(over)


def compare(args, folder):
    _,ranges=probe_ranges(args)
    total=sum(row["frames"] for row in ranges)
    base=folder/"baseline.mp4"
    candidate=folder/"candidate.mp4"
    base_metrics=run_probes(args,ranges,base,folder/"baseline")
    candidate_metrics=run_probes(args,ranges,candidate,folder/"candidate",
                                 html=args.candidate,shot=args.candidate_shot,holds=args.candidate_holds)

    def hashes(source):
        data=subprocess.check_output([os.environ.get("FFMPEG_PATH","ffmpeg"),"-v","error",
            "-i",source,"-map","0:v:0","-an","-f","framehash","-hash","sha256","-"],text=True)
        lines=data.splitlines()
        header=[line for line in lines if line.startswith(("#dimensions","#tb"))]
        return header,[line for line in lines if line and not line.startswith("#")]

    header_a,frames_a=hashes(base)
    header_b,frames_b=hashes(candidate)
    if len(frames_a)!=total or len(frames_b)!=total:
        raise ValueError(f"comparison expected {total} frames; got {len(frames_a)} and {len(frames_b)}")
    differences=[i for i,(a,b) in enumerate(zip(frames_a,frames_b)) if a!=b]

    def summary(metrics):
        rows=metrics["ranges"]
        return {
            "seconds":round(metrics["setupSeconds"]+metrics["drainSeconds"]+sum(r["seconds"] for r in rows),2),
            "sceneSeconds":round(sum(r["sceneSeconds"] for r in rows),2)
                if all(r["sceneSeconds"] is not None for r in rows) else None,
            "captureSeconds":round(sum(r["captureSeconds"] for r in rows),2),
            "pipeSeconds":round(sum(r["pipeSeconds"] for r in rows),2),
            **({key:metrics[key] for key in ("verifiedHolds","rejectedHolds","reusedSamples")}
                if "reusedSamples" in metrics else {}),
        }

    mismatches=[]
    offset=0
    for row in ranges:
        mismatches.extend(round((row["start"]+i-offset)/args.fps,5)
                          for i in differences if offset<=i<offset+row["frames"])
        offset+=row["frames"]
    identical=header_a==header_b and not differences
    result=dict(frames=total,identical=identical,changedFrames=len(differences),
                firstDifferences=mismatches[:5],baseline=summary(base_metrics),
                candidate=summary(candidate_metrics))
    if args.report:
        args.report.write_text(json.dumps({**result,"ranges":ranges,
            "baselineMetrics":base_metrics,"candidateMetrics":candidate_metrics},indent=2)+"\n",encoding="utf8")
    print(json.dumps(result,separators=(",",":")))
    return int(not identical)


def review(args, folder):
    if (not all(map(math.isfinite,[args.before,args.after,*args.cuts])) or
        min(args.before,args.after)<=0 or min(args.cuts)<0 or len(args.cuts)>12):
        raise ValueError("provide up to 12 nonnegative cut times and positive handles")
    if args.seconds is not None and (not math.isfinite(args.seconds) or args.seconds<=max(args.cuts)):
        raise ValueError("duration must follow the last cut")
    limit=round(args.seconds*args.fps) if args.seconds is not None else None
    intervals=[]
    cuts=sorted({math.ceil(t*args.fps-1e-9) for t in args.cuts})
    before=max(1,round(args.before*args.fps))
    after=max(1,round(args.after*args.fps))
    for cut in cuts:
        start,end=max(0,cut-before),cut+after+1
        if limit is not None:
            end=min(limit,end)
        if end<=cut:
            raise ValueError("a cut rounds beyond the last frame")
        if intervals and intervals[-1][1]>=start:
            intervals[-1]=(intervals[-1][0],max(intervals[-1][1],end))
        else:
            intervals.append((start,end))
    if sum(end-start for start,end in intervals)>40*args.fps:
        raise ValueError("keep the combined review under 40 seconds")
    metrics=run_probes(args,[dict(start=start,frames=end-start) for start,end in intervals],
                        args.out,folder)
    markers=[]
    elapsed=0
    for start,end in intervals:
        markers.extend([round(c/args.fps,3),round((elapsed+c-start)/args.fps,3)]
                       for c in cuts if start<=c<end)
        elapsed+=end-start
    print(json.dumps(dict(clip=str(args.out),sourceAndClipCuts=markers,frames=elapsed,
        seconds=round(metrics["setupSeconds"]+metrics["drainSeconds"]+
                      sum(row["seconds"] for row in metrics["ranges"]),2)),ensure_ascii=False))
    return 0


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("renderer",type=Path)
    parser.add_argument("mode",choices=["render_budget","seam_review","render_compare"])
    parser.add_argument("html",type=Path)
    parser.add_argument("--candidate",type=Path)
    parser.add_argument("--candidate-shot",choices=["jpeg","png","png-fast"])
    parser.add_argument("--candidate-holds",type=Path)
    parser.add_argument("--report",type=Path)
    parser.add_argument("--seconds",type=float)
    parser.add_argument("--fps",type=int)
    parser.add_argument("--preset",choices=["draft","hd","qhd","uhd"])
    parser.add_argument("--encpreset")
    parser.add_argument("--crf",type=int)
    parser.add_argument("--shot",choices=["jpeg","png","png-fast"])
    parser.add_argument("--holds",type=Path)
    parser.add_argument("--codec",choices=["x264","x265"],default="x264")
    parser.add_argument("--blur",type=int,default=1)
    parser.add_argument("--canvas-only",action="store_true",
                        help="match a production render whose entire image is on one canvas")
    parser.add_argument("--starts",type=float,nargs="+")
    parser.add_argument("--probe",type=float,default=1)
    parser.add_argument("--cap-minutes",type=float)
    parser.add_argument("--cuts",type=float,nargs="+")
    parser.add_argument("--before",type=float,default=.65)
    parser.add_argument("--after",type=float,default=.65)
    parser.add_argument("--out",type=Path)
    args=parser.parse_args()
    is_review=args.mode=="seam_review"
    if not is_review and (args.seconds is None or not args.starts):
        parser.error("provide --seconds and --starts")
    if args.mode=="render_compare" and not (args.candidate or args.candidate_shot or args.candidate_holds):
        parser.error("provide --candidate HTML, --candidate-shot or --candidate-holds for comparison")
    if is_review and (not args.cuts or args.out is None or args.out.suffix.lower()!=".mp4"):
        parser.error("seam_review needs --cuts and --out FILE.mp4")
    args.fps=args.fps if args.fps is not None else (30 if is_review else 24)
    args.preset=args.preset or ("hd" if is_review else "uhd")
    args.encpreset=args.encpreset or ("medium" if is_review else "slow")
    args.crf=args.crf if args.crf is not None else (17 if is_review else 14)
    if args.fps<=0 or args.blur<=0 or not 0<=args.crf<=51:
        parser.error("invalid fps, CRF or motion blur samples")
    try:
        with tempfile.TemporaryDirectory(prefix="codefilm-probe-") as folder:
            run={"render_budget":budget,"seam_review":review,"render_compare":compare}[args.mode]
            return run(args,Path(folder))
    except (ValueError,OSError,subprocess.CalledProcessError) as exc:
        parser.exit(1,str(exc)+"\n")


if __name__=="__main__":
    raise SystemExit(main())
