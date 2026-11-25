#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""score_driver.py —— 用 JSON 文件调用 music_score（避免 shell 把 cues 的引号吃掉）。

  python score_driver.py score.json out.wav
score.json: {"seconds":9.5,"style":"ensemble","mood":"lyric","bpm":88,"seed":5,
             "arrangement":"light","cues":[{"time":4.567,"kind":"soft"}],"no_pedal":false}
"""
import json, subprocess, sys
from pathlib import Path

source = Path(sys.argv[1])
spec = json.loads(source.read_text(encoding="utf-8-sig"))
out = sys.argv[2]
here = Path(__file__).resolve().parent
cmd = [sys.executable, str(here.parent / "scripts" / "music_score.py"),
       "--seconds", str(spec["seconds"]),
       "--style", spec.get("style", "ensemble"),
       "--mood", spec.get("mood", "lyric"),
       "--bpm", str(spec.get("bpm", 80)),
       "--seed", str(spec.get("seed", 7)),
       "--arrangement", spec.get("arrangement", "chamber_live"),
       *(["--cues-file",str(source)] if "cues" in spec else []),
       "--out", out]
if spec.get("no_pedal"):
    cmd.append("--no-pedal")
r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
sys.stdout.write(r.stdout[-400:])
sys.stderr.write(r.stderr[-1500:])
sys.exit(r.returncode)
