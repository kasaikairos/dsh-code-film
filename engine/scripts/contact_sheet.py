#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""contact_sheet.py —— 把 N 帧拼成一张印样（看一张图抵看六张）。

为什么要它：一次出片若逐帧看图，六张图就会吃掉大量上下文；
印样把 6 帧拼成一张，分辨率足够判断构图/明暗/细节，但只占一份图像的代价。

用法：
  python scripts/contact_sheet.py --video out/f.mp4 --out out/f.sheet.png --n 6
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont


def grab(video, n, width=640):
    tmp = tempfile.mkdtemp(prefix="sheet_")
    # 均匀取 n 帧：用 select 过滤 + 缩到 width
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nk=1:nw=1", video],
                         capture_output=True, text=True).stdout.strip()
    try:
        dur = float(dur)
    except Exception:
        dur = 10.0
    rate = max(0.2, min(4.0, n / max(0.5, dur)))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video,
                    "-vf", f"fps={rate:.4f},scale={width}:-2",
                    "-frames:v", str(n), "-start_number", "0",
                    os.path.join(tmp, "%02d.png")], capture_output=True)
    out = []
    for f in sorted(os.listdir(tmp)):
        if f.endswith(".png"):
            out.append((f, Image.open(os.path.join(tmp, f)).convert("RGB")))
    return out[:n], dur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--cols", type=int, default=3)
    a = ap.parse_args()

    frames, dur = grab(a.video, a.n)
    if not frames:
        print("取帧失败", file=sys.stderr)
        return 2
    w, h = frames[0][1].size
    cols = min(a.cols, len(frames))
    rows = (len(frames) + cols - 1) // cols
    pad, label = 8, 22
    sheet = Image.new("RGB", (cols * (w + pad) + pad, rows * (h + label + pad) + pad), (18, 18, 20))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 15)
    except Exception:
        font = ImageFont.load_default()
    for i, (fn, im) in enumerate(frames):
        r, c = divmod(i, cols)
        x = pad + c * (w + pad)
        y = pad + r * (h + label + pad) + label
        sheet.paste(im.resize((w, h)), (x, y))
        t = i / max(1, len(frames)) * dur
        d.text((x, y - label + 4), f"#{i}  t={t:.2f}s", fill=(220, 220, 220), font=font)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    sheet.save(a.out)
    print(f"印样 → {a.out}（{len(frames)} 帧 · {sheet.size[0]}×{sheet.size[1]}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
