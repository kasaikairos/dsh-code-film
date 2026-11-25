"""Dispatch disk-only engine commands. Topic lookup never opens the engine archive."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import subprocess
import zipfile

base = Path(__file__).resolve().parent
args = sys.argv[1:]


def render_timeline(options):
    renderer=cache/"scripts/render_html.mjs"
    if "--cache-picture" not in options:
        return subprocess.call(["node",renderer,*options,"--timeline","--quiet"])
    sys.path.insert(0,str(base/"tools"))
    import timeline_cache
    try:
        return timeline_cache.render(renderer,[option for option in options if option!="--cache-picture"])
    except (OSError,ValueError,IndexError) as exc:
        sys.exit(f"picture cache: {exc}")


if args[:1] == ["topic"]:
    name = args[1] if len(args)==2 else ""
    topics = {p.stem:p for p in (base/"topics").glob("*.md")}
    if name not in topics:
        sys.exit("topics: " + ", ".join(sorted(topics)))
    sys.stdout.reconfigure(encoding="utf8")
    print(topics[name].read_text(encoding="utf-8-sig"))
    sys.exit(0)
assets={"layers":"layers.mjs","motion_kit":"motion-kit.mjs","optical_camera":"optical-camera.mjs",
        "environment":"environment.mjs","camera_track":"camera-track.mjs"}
if len(args)==2 and args[0] in assets:
    asset=assets[args[0]]
    dest=Path(args[1])
    with dest.open("xb") as out:
        out.write((base/"tools"/asset).read_bytes())
    print(dest)
    sys.exit(0)
if args and args[0] in ("find", "director", "storyboard", "construct", "shader", "score_plan"):
    sys.exit(subprocess.call([sys.executable,"-X","utf8",base/"tools"/(args[0]+".py"),*args[1:]]))
payload = base/"engine.zip"
with payload.open('rb') as stream:
    key = hashlib.file_digest(stream, 'sha256').hexdigest()[:24]
cache = Path(os.environ.get("LOCALAPPDATA",Path.home()/".cache"))/"CodeFilm"/key
cache.parent.mkdir(parents=True, exist_ok=True)
if not cache.exists():
    with tempfile.TemporaryDirectory(dir=cache.parent) as temp:
        stage = Path(temp)/"runtime"
        with zipfile.ZipFile(payload) as z:
            z.extractall(stage)
        try:
            stage.rename(cache)
        except OSError:
            if not cache.is_dir():
                raise
private = cache/"venv"/("Scripts/python.exe" if os.name=="nt" else "bin/python")
if os.name == "nt" and not os.environ.get("PUPPETEER_EXECUTABLE_PATH"):
    for root in ("ProgramFiles", "LOCALAPPDATA", "ProgramFiles(x86)"):
        browser = Path(os.environ.get(root,""))/"Google/Chrome/Application/chrome.exe"
        if browser.is_file():
            os.environ["PUPPETEER_EXECUTABLE_PATH"]=str(browser)
            break
if args == ["install"]:
    subprocess.run([sys.executable,"-m","venv",cache/"venv"],check=True)
    subprocess.run([private,"-m","pip","install","--no-index","--find-links",base/"wheels",
                    "-r",cache/"requirements.txt"],check=True)
    for tool in ("ffmpeg","ffprobe"):
        subprocess.run([tool,"-version"],stdout=subprocess.DEVNULL,check=True)
    subprocess.run(["node","--input-type=module","-e",
        "import p from 'puppeteer'; const b=await p.launch({executablePath:process.env.PUPPETEER_EXECUTABLE_PATH});await b.close()"],
        cwd=cache,check=True)
    print("CodeFilm ready")
elif args[:1] == ["score_wav"]:
    if not private.exists(): sys.exit("Initialize the runtime first.")
    if len(args)!=3: sys.exit("score_wav score.json output.wav")
    sys.exit(subprocess.call([private,"-X","utf8",cache/"tools/score_driver.py",*args[1:]]))
elif args[:1] == ["review_packet"]:
    if not private.exists(): sys.exit("Initialize the runtime first.")
    sys.exit(subprocess.call([private,"-X","utf8",base/"tools/review_packet.py",
                              cache/"scripts/render_html.mjs",*args[1:]]))
elif args and args[0] in ("render_budget","seam_review","render_compare"):
    if not private.exists(): sys.exit("Initialize the runtime first.")
    sys.exit(subprocess.call([private,"-X","utf8",base/"tools/render_budget.py",
                              cache/"scripts/render_html.mjs",*args]))
elif args and args[0] in ("preflight", "timeline"):
    if not private.exists(): sys.exit("Initialize the runtime first.")
    options=args[1:]
    if args[0]=="timeline" and any(flag in options for flag in ("--background","--status","--wait")):
        sys.exit(subprocess.call([private,"-X","utf8",cache/"scripts/timeline_job.py",
                                  Path(__file__).resolve(),*options]))
    profile_flag="--gate" if args[0]=="timeline" else "--profile"
    if profile_flag in options:
        index=options.index(profile_flag)
        if index < 1 or index+1>=len(options):
            sys.exit(f"{args[0]} HTML ... {profile_flag} profile.json")
        profile=options[index+1]
        result=subprocess.call([private,"-X","utf8",base/"tools/quality_gate.py",profile])
        if result:
            sys.exit(result)
        if args[0]=="timeline":
            result=subprocess.call(["node",base/"tools/preflight.mjs",cache,options[0],
                                    "--profile",profile])
            if result:
                sys.exit(result)
            del options[index:index+2]
    if args[0]=="timeline" and "--track" in options:
        if "--out" not in options or "--stills" in options or "--ranges" in options:
            sys.exit("timeline --track requires --out FILE.mp4 and video frames")
        track_index=options.index("--track")
        out_index=options.index("--out")
        if max(track_index,out_index)+1>=len(options):
            sys.exit("--track and --out require paths")
        track=Path(options[track_index+1]).resolve()
        output=Path(options[out_index+1]).resolve()
        if not track.is_file() or track==output:
            sys.exit("use an existing track and a separate output")
        del options[track_index:track_index+2]
        try:
            def value(flag,default):
                return int(options[options.index(flag)+1]) if flag in options else default
            fps,start,end=value("--fps",30),value("--start",0),value("--end",0)
            frames=end-start if end else value("--frames",300)
            if fps<=0 or start<0 or frames<=0:
                raise ValueError("invalid frame range")
            stream=json.loads(subprocess.check_output([
                "ffprobe","-v","error","-select_streams","a:0","-show_entries",
                "stream=duration","-of","json",track]))["streams"]
            if not stream:
                raise ValueError("audio track has no audio stream")
            if stream[0].get("duration") not in (None,"N/A") and float(stream[0]["duration"])+.025<frames/fps:
                raise ValueError("audio track too short; render has not started")
        except (IndexError,ValueError,subprocess.CalledProcessError,OSError) as error:
            sys.exit(str(error))
        output.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".film-delivery-",dir=output.parent) as tmp:
            picture=Path(tmp)/"picture.mp4"
            options[options.index("--out")+1]=str(picture)
            result=render_timeline(options)
            if result:
                sys.exit(result)
            sys.exit(subprocess.call([private,"-X","utf8",cache/"scripts/revision.py","audio",
                                      "--picture",picture,"--track",track,"--out",output]))
    if args[0]=="timeline":
        sys.exit(render_timeline(options))
    sys.exit(subprocess.call(["node",base/"tools/preflight.mjs",cache,*options]))
elif args and args[0].isidentifier() and (cache/"scripts"/(args[0]+".py")).is_file():
    if args[0] == "source_view" and len(args)>1 and args[1].startswith("references/"):
        args[1] = str(cache/args[1])
    if not private.exists(): sys.exit("Run START-HERE.cmd once, then retry.")
    sys.exit(subprocess.call([private,"-X","utf8",cache/"scripts"/(args[0]+".py"),*args[1:]]))
else:
    sys.exit("use: python film.py topic NAME | install | TOOL [args]")

