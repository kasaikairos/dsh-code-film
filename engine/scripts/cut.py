"""Render independently cached shots, then score the complete timeline."""
import argparse
from fractions import Fraction
import render_job
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts"
SIZE = {"draft":(1280,720),"hd":(1920,1080),"uhd":(3840,2160)}

# Windows 控制台默认 cp936/cp1252，中文摘要会直接抛 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def cache_key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read_dependencies(manifest, root):
    try:
        deps = json.loads(manifest.read_text(encoding="utf8"))
        if not isinstance(deps, dict) or not deps:
            return None
        for name, expected in deps.items():
            path = (root / name).resolve()
            if not path.is_relative_to(root):
                return None
            current = digest(path) if path.is_file() else None
            if current != expected:
                return None
        return deps
    except (OSError, ValueError, TypeError):
        return None


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--plan",type=Path)
    ap.add_argument("--background", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--wait", action="store_true", help="wait for the independent worker and return one summary")
    ap.add_argument("--out",required=True,type=Path)
    ap.add_argument("--preset",choices=SIZE,default="draft")
    ap.add_argument("--fps",type=int,default=24)
    a=ap.parse_args()
    a.out = a.out.resolve()
    if a.status or a.wait:
        state = render_job.read(a.out)
        while a.wait and state["state"] == "running":
            time.sleep(3)
            state = render_job.read(a.out)
        print(json.dumps(state, ensure_ascii=False))
        if a.wait and state["state"] != "complete":
            raise SystemExit(1)
        return
    if not a.plan:
        ap.error("--plan required")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    if a.background:
        return render_job.start(a.out)
    with render_job.try_lock(a.out) as acquired:
        if not acquired:
            print("already rendering", a.out)
            return
        render_job.update(a.out, state="running", stage="plan")
        try:
            result = render(a, ap)
        except BaseException as exc:
            render_job.update(a.out, state="failed", error=str(exc)[-400:])
            raise
        render_job.update(a.out, state="complete", **result)


def render(a, ap):
    plan=json.loads(a.plan.read_text(encoding="utf-8-sig"))
    brief=plan["brief"].strip()
    title=plan["title"].strip()
    shots=plan["shots"]
    if not shots or not title or not brief or a.fps<=0:
        ap.error("需要用户标题、原始要求和镜头")
    # Section settings apply only to authored HTML, whose entry renders the actual pixels.
    video=plan.get("video")
    video_args=[]
    if video is not None:
        allowed={"shot":{"jpeg","png","png-fast"},
                 "encpreset":{"ultrafast","superfast","veryfast","faster","fast","medium","slow","slower","veryslow"}}
        if not isinstance(video,dict) or set(video)-{"shot","encpreset","crf"}:
            ap.error("video supports shot, encpreset and crf")
        for name,value in video.items():
            if name=="crf":
                if type(value) is not int or not 0<=value<=51:
                    ap.error("video.crf must be an integer from 0 to 51")
            elif not isinstance(value,str) or value not in allowed[name]:
                ap.error(f"invalid video.{name}")
            video_args.extend(["--"+name,value])
    boundaries = [0]
    elapsed = Fraction(0)
    for shot in shots:
        quote=shot["based_on"].strip()
        if not quote or quote not in brief or not shot["visible"].strip():
            ap.error("每镜写一个可见动作，based_on 必须逐字来自用户原话")
        elapsed += Fraction(str(shot["seconds"])) * a.fps
        boundary = round(elapsed)
        if boundary <= boundaries[-1]: ap.error("镜头不足一帧")
        boundaries.append(boundary)
    parent=a.plan.resolve().parent
    for number, shot in enumerate(shots, 1):
        src = parent / shot["source"]
        if not src.is_file():
            ap.error(f"第 {number} 镜找不到源文件：{src}")
        if (video_args or "timeline_start" in shot) and src.suffix.lower()!=".html":
            ap.error("video settings and timeline_start require HTML section entries")
        if "timeline_start" in shot:
            try:
                if Fraction(str(shot["timeline_start"]))<0:
                    raise ValueError
            except (ValueError,ZeroDivisionError):
                ap.error("timeline_start must be nonnegative seconds")
    cache=parent/".codefilm-cache";cache.mkdir(exist_ok=True)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    started=time.perf_counter()
    # Renderer, shaders, shared scripts, fonts and vendored resources can affect pixels.
    library=hashlib.sha256()
    for directory in ("scripts","assets","vendor"):
        for p in sorted((ROOT/directory).rglob("*")):
            if directory == "scripts" and p.name not in {
                "render_spec.py", "render_html.mjs", "page_server.mjs"
            }: continue
            if p.is_file() and p.suffix.lower() in (".html",".js",".mjs",".css",".py",".json",".otf",".ttf",".woff2",".glsl",".jpg",".png"):
                library.update(p.relative_to(ROOT).as_posix().encode());library.update(bytes.fromhex(digest(p)))
    for name in ("kit_space.html", "scene3d.html", "scenekit.html", "scene_poster.html", "package-lock.json"):
        library.update(bytes.fromhex(digest(ROOT/name)))
    for name in ("SHOT_FMT", "RENDER_GPU", "PUPPETEER_EXECUTABLE_PATH", "CHROME_PATH", "FFMPEG_PATH"):
        library.update(str(os.environ.get(name, "")).encode())
    with tempfile.TemporaryDirectory(dir=a.out.parent) as scratch, a.out.with_suffix(".cut.log").open("w",encoding="utf8") as log:
        tmp=Path(scratch).resolve()
        def run(cmd):
            subprocess.run(list(map(str,cmd)),stdout=log,stderr=subprocess.STDOUT,check=True,env={**os.environ,"PYTHONUTF8":"1"})
        clips=[]; frames_total=0;hits=0; timeline_cues=[]
        local_sfx = []
        for i,s in enumerate(shots):
            render_job.update(a.out, state="running", stage="shot", shot=i+1, total=len(shots), hits=hits)
            frames=boundaries[i+1]-boundaries[i];frames_total=boundaries[i+1]
            path=(parent/s["source"]).resolve()
            start = round(Fraction(str(s.get("timeline_start",0)))*a.fps)
            timeline_mode = "timeline_start" in s
            settings = [library.hexdigest(),path.name,frames,a.fps,a.preset,start,timeline_mode,video_args]
            html = path.suffix.lower() == ".html"
            if html:
                identity = cache_key([str(path), settings])
                manifest = cache / (identity + ".deps.json")
                payload = read_dependencies(manifest, path.parent)
            else:
                spec=json.loads(path.read_text(encoding="utf-8-sig"))
                offset=(frames_total-frames)/a.fps
                score = spec.get("music") or {}
                if score.get("sfx"):
                    local_sfx.append({"start_frame": boundaries[i], "frames": frames,
                                      "gain": score.get("sfx_level", 1), "sfx": score["sfx"]})
                for cue in score.get("cues",[]):
                    if "at" in cue:
                        events = spec.get("events", {})
                        if cue["at"] not in events:
                            continue
                        local = float(events[cue["at"]])
                    else:
                        local = float(cue["time"])
                    if 0<=local<frames/a.fps:
                        entry = {**cue, "time":offset+local}
                        if "pull" in entry: entry["pull"] += offset
                        timeline_cues.append(entry)
                spec.pop("music",None);spec["duration"]=frames/a.fps
                emo=(spec.get("emotion") or {}).get("src")
                payload=[spec]
                if emo:
                    emotion=(path.parent/emo).resolve()
                    payload.append(digest(emotion));spec["emotion"]["src"]=str(emotion)
            clip = cache/(cache_key([settings,payload])+".mp4") if payload is not None else None
            if clip is not None and clip.is_file():
                hits += 1
            else:
                part=tmp/f"shot{i}.mp4"
                opts=["--fps",a.fps,"--frames",frames,"--preset",a.preset,"--out",part]
                if path.suffix.lower()==".html":
                    report = tmp/f"deps{i}.json"
                    timeline_flags=["--timeline","--start",start] if timeline_mode else []
                    run(["node",SCRIPT/"render_html.mjs",path,*opts,*timeline_flags,*video_args,
                         "--quiet","--deps-out",report])
                    payload = json.loads(report.read_text(encoding="utf8"))
                    if not payload:
                        clips.append(part)
                        continue
                    clip = cache/(cache_key([settings,payload])+".mp4")
                else:
                    sp=tmp/"spec.json";sp.write_text(json.dumps(spec),encoding="utf8")
                    run([sys.executable,SCRIPT/"render_spec.py","--spec",sp,*opts,"--quiet"])
                # cache is on the plan filesystem
                if part.stat().st_dev == cache.stat().st_dev:
                    os.replace(part,clip)
                else:
                    import shutil
                    with tempfile.NamedTemporaryFile(dir=cache,delete=False) as dest,part.open("rb") as src:
                        shutil.copyfileobj(src,dest)
                    os.replace(dest.name,clip)
                if html:
                    with tempfile.NamedTemporaryFile(mode="w", encoding="utf8", dir=cache, delete=False) as f:
                        json.dump(payload, f)
                    os.replace(f.name, manifest)
            clips.append(clip)
        render_job.update(a.out,state="running",stage="mux and quality check",total=len(shots),hits=hits)
        listing=tmp/"list.txt"
        listing.write_text("\n".join("file '"+str(p.resolve()).replace("\\","/").replace("'","'\\''")+"'" for p in clips),encoding="utf8")
        silent=tmp/"cut.mp4"
        if len(clips) == 1:
            silent = clips[0]
        else:
            run(["ffmpeg","-v","error","-f","concat","-safe","0","-i",listing,"-c","copy",silent])
        music=dict(plan.get("music",{})); music.setdefault("cues",timeline_cues)
        if "sfx" not in music and local_sfx:
            music["shot_sfx"] = local_sfx
        sp=tmp/"score.json";sp.write_text(json.dumps({"duration":frames_total/a.fps,"music":music}),encoding="utf8")
        audio_args = ["--soundtrack", parent / plan["soundtrack"]] if plan.get("soundtrack") else []
        run([sys.executable,SCRIPT/"make_video.py",*audio_args,"--report",tmp/"quality.json","--picture",silent,"--spec",sp,"--fps",a.fps,"--preset",a.preset,"--out",a.out])
        quality = json.loads((tmp/"quality.json").read_text(encoding="utf8"))
    print(f"{a.out} | {frames_total} 帧 | 镜头缓存 {hits}/{len(clips)} | 总耗时 {time.perf_counter()-started:.1f}s")

    return dict(quality=quality, frames=frames_total, shots=len(clips), hits=hits, seconds=round(time.perf_counter()-started,1))

if __name__=="__main__": main()

