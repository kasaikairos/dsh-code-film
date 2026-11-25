#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_chunks.py —— 分段并行渲染：把 60 秒的片子按帧数切给多个进程。

为什么不是 --jobs：同一浏览器里开多个页面会抢同一个 GPU 进程，实测反而更慢。
开多个进程各自持有浏览器上下文，才能真正吃满多核；代价是每段多 2–4 秒启动。

用法：
  python scripts/render_chunks.py --spec out/spec.json --out out/film.mp4 \
      --seconds 60 --workers 4 [--preset uhd --dpr 2] [--fps 30]

  # 先估时间，不渲
  python scripts/render_chunks.py --probe-only --seconds 60 --workers 4
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def run_part(spec, out, start, end, fps, preset, dpr, gpu, outres, extra):
    cmd = [PY, os.path.join(HERE, "render_spec.py"), "--spec", spec, "--out", out,
           "--frames", str(end - start), "--start", str(start), "--end", str(end),
           "--fps", str(fps), "--preset", preset, "--gpu", gpu]
    if dpr is not None:
        cmd.extend(["--dpr",str(dpr)])
    if outres:
        cmd.extend(["--outres",outres])
    cmd.extend(extra)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode or not os.path.exists(out):
        raise RuntimeError((r.stdout or "")[-600:] + (r.stderr or "")[-600:])
    return out


def concat(parts, out):
    listing = Path(parts[0]).parent / "list.txt"
    listing.write_text("".join(f"file '{Path(p).name}'\n" for p in parts), encoding="utf8")
    final = listing.parent / "merged.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "concat", "-safe", "1",
                    "-i", listing, "-c", "copy", final], check=True)
    os.replace(final, out)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=False)
    ap.add_argument("--out", required=False)
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--preset", default="uhd")
    ap.add_argument("--dpr", type=float)
    ap.add_argument("--outres", default="")
    ap.add_argument("--gpu", default="on")
    ap.add_argument("--probe-only", action="store_true")
    ap.add_argument("--extra", default="", help="透传给 render_spec 的其它参数，空格分隔")
    a = ap.parse_args()

    total = int(round(a.seconds * a.fps))
    w = max(1, min(16, a.workers))
    bounds = []
    for k in range(w):
        s = total * k // w
        e = total * (k + 1) // w
        if e > s:
            bounds.append((s, e))

    if a.probe_only:
        print(f"计划：{total} 帧（{a.seconds:g}s @ {a.fps}fps）分 {len(bounds)} 段")
        for s, e in bounds:
            print(f"  段 {s:>5}–{e:<5}  {e-s} 帧  {(e-s)/a.fps:5.1f}s 素材")
        print("\n参考吞吐（1080p / dpr1 / WebGL）：约 90ms/帧 → "
              f"单进程 {total*0.09/60:.1f} 分钟；{len(bounds)} 进程理想 {total*0.09/60/len(bounds):.1f} 分钟")
        return 0

    if not (a.spec and a.out):
        print("需要 --spec 与 --out（或只用 --probe-only）", file=sys.stderr)
        return 2

    extra = a.extra.split() if a.extra else []
    if not bounds:
        ap.error("duration and fps must yield at least one frame")
    target = Path(a.out).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="chunks_", dir=target.parent) as folder:
        with ThreadPoolExecutor(max_workers=len(bounds)) as pool:
            pending = [pool.submit(run_part, a.spec, str(Path(folder) / f"part_{k:02d}.mp4"),
                                   start, end, a.fps, a.preset, a.dpr, a.gpu, a.outres, extra)
                       for k, (start, end) in enumerate(bounds)]
            parts = [job.result() for job in pending]
        concat(parts, target)
    el = time.time() - t0
    print(f"\n完成：{a.out}")
    print(f"  {total} 帧 · {w} 进程 · {el:.0f}s（{el/60:.1f} 分钟）· "
          f"等效 {el/total*1000:.0f}ms/帧（按墙钟）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
