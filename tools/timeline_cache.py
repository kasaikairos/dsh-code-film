"""Reuse the exact encoded picture of a deterministic local HTML timeline."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile


def digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def current(root, dependencies):
    if not isinstance(dependencies, dict) or not dependencies:
        return False
    try:
        for name, expected in dependencies.items():
            file=(root/name).resolve()
            if not file.is_relative_to(root):
                return False
            observed=digest(file) if file.is_file() else None
            if observed!=expected:
                return False
    except OSError:
        return False
    return True


def program_identity(name):
    resolved=shutil.which(name) if name else None
    if not resolved:
        return name
    real=Path(resolved).resolve()
    stat=real.stat()
    return [str(real),stat.st_size,stat.st_mtime_ns]


def atomic_copy(source, destination):
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".picture-copy-",dir=destination.parent) as temp:
        stage=Path(temp)/"picture.mp4"
        shutil.copyfile(source,stage)
        os.replace(stage,destination)


def render(renderer, options):
    if "--out" not in options or "--out" == options[-1]:
        raise ValueError("--cache-picture requires --out FILE.mp4")
    if any(flag in options for flag in ("--stills","--metrics","--deps-out","--log")):
        raise ValueError("use --cache-picture for MP4 output without a separate render metrics, log or stills request")
    out_index=options.index("--out")+1
    output=Path(options[out_index]).resolve()
    html=Path(options[0]).resolve(strict=True)
    if output.suffix.lower()!=".mp4" or output==html:
        raise ValueError("--cache-picture requires a separate MP4 output")

    root=html.parent
    cache=root/".codefilm-cache"/"timeline"
    cache.mkdir(parents=True,exist_ok=True)
    manifests={flag:Path(options[options.index(flag)+1]).resolve()
               for flag in ("--ranges","--holds") if flag in options}
    source_hashes={flag:digest(file) for flag,file in manifests.items()}
    inputs={
        "engine":str(renderer.parents[1]),
        "renderer":digest(renderer),
        "localHost":platform.node(),
        "entry":html.name,
        "options":options[1:out_index]+options[out_index+1:],
        "settings":{key:os.environ.get(key) for key in ("SHOT_FMT","RENDER_GPU")},
        "node":program_identity("node"),
        "browser":program_identity(os.environ.get("PUPPETEER_EXECUTABLE_PATH") or
                                   os.environ.get("CHROME_PATH")),
        "encoder":program_identity(os.environ.get("FFMPEG_PATH","ffmpeg")),
        "manifests":source_hashes,
    }
    key=hashlib.sha256(json.dumps(inputs,sort_keys=True).encode()).hexdigest()
    manifest=cache/(key+".json")
    if output.is_relative_to(cache):
        raise ValueError("choose an output outside the picture cache")
    try:
        provenance=json.loads(manifest.read_text(encoding="utf8"))
        expected=provenance["picture"]
        if not re.fullmatch(r"[a-f0-9]{64}",expected):
            raise ValueError("invalid cached picture digest")
        picture=cache/(expected+".mp4")
        hit=(html.name in provenance["dependencies"] and current(root,provenance["dependencies"])
             and digest(picture)==expected)
    except (OSError,ValueError,KeyError,TypeError):
        hit=False
    if hit:
        atomic_copy(picture,output)
        print(json.dumps({"pictureCache":"hit","output":output.name},ensure_ascii=False))
        return 0

    with tempfile.TemporaryDirectory(prefix=".picture-render-",dir=cache) as temp:
        scratch=Path(temp)
        stage=scratch/"picture.mp4"
        report=scratch/"dependencies.json"
        command=options.copy()
        command[out_index]=str(stage)
        result=subprocess.call(["node",renderer,*command,"--timeline","--quiet","--deps-out",report])
        if result:
            return result
        dependencies=json.loads(report.read_text(encoding="utf8"))
        stable_manifests=all(digest(file)==source_hashes[flag] for flag,file in manifests.items())
        reusable=bool(stable_manifests and dependencies and html.name in dependencies and current(root,dependencies))
        if reusable:
            recorded=scratch/"entry.json"
            checksum=digest(stage)
            recorded.write_text(json.dumps({"dependencies":dependencies,"picture":checksum}),encoding="utf8")
            atomic_copy(stage,output)
            os.replace(stage,cache/(checksum+".mp4"))
            os.replace(recorded,manifest)
        else:
            atomic_copy(stage,output)
        print(json.dumps({"pictureCache":"stored" if reusable else "skipped","output":output.name},
                         ensure_ascii=False))
    return 0
