#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""precision_probe.py —— "渲染够不够精细"的量化（不看分辨率，看画面质量）。

分辨率不等于精细。可测的精细度指标：
  sharp        边缘锐度：梯度 p99 / mean（越高越"脆"，糊图会低）
  edge_width   边缘过渡宽度（像素）：越窄越锐（4K 缩到同尺寸仍应更窄）
  alias        Nyquist 附近能量占比：抗锯齿差会有高频尖峰
  banding      平滑区的色阶台阶数：渐变 8bit 直出会有明显的带
  grain        平坦区高频 σ：胶片颗粒量
  halo         高光溢出面积（>0.95 亮度占比）：泛光/写实感
  detail_ratio 细节/平滑比：Laplacian 方差 / 局部均值方差

    python scripts/precision_probe.py --video x.mp4
    python scripts/precision_probe.py --dir <目录> --out p.json --frames 24
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import subprocess
import sys

import numpy as np

try:
    import cv2
    _HAS_CV = True
except Exception:          # 没 opencv 用 numpy/PIL 兜底，保证验收不静默跳过
    cv2 = None
    _HAS_CV = False
    from PIL import Image

    def _imread(path):
        return np.asarray(Image.open(path).convert("RGB"))[:, :, ::-1]

    def _gray(bgr):
        a = bgr[:, :, ::-1].astype(np.float32) / 255.0
        return a @ np.array([0.299, 0.587, 0.114], np.float32)

    def _sobel(g, dx, dy):
        return np.gradient(g, axis=1) if dx else np.gradient(g, axis=0)

    def _laplacian(g):
        k = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], np.float32)
        out = np.zeros_like(g)
        out[1:-1, 1:-1] = (k[0, 1] * g[:-2, 1:-1] + k[1, 0] * g[1:-1, :-2] +
                           k[1, 2] * g[1:-1, 2:] + k[2, 1] * g[2:, 1:-1] - 4 * g[1:-1, 1:-1])
        return out

    def _gauss(g, sig):
        rad = max(1, int(round(sig * 2)))
        x = np.arange(-rad, rad + 1)
        k = np.exp(-(x ** 2) / (2 * sig * sig)); k /= k.sum()
        t = np.apply_along_axis(lambda m: np.convolve(m, k, mode="same"), 0, g)
        return np.apply_along_axis(lambda m: np.convolve(m, k, mode="same"), 1, t)



def _find_knowledge(name):
    """兼容新旧结构：evidence/ → knowledge/ 根 → models/ → atlas/。"""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    k = os.path.join(root, "knowledge")
    for sub in ("evidence", "", "models", "atlas", "rules"):
        p = os.path.join(k, sub, name) if sub else os.path.join(k, name)
        if os.path.exists(p):
            return p
    return None

def frames(video, n=24, w=1280):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", video], capture_output=True, text=True)
    try:
        dur = float((r.stdout or "10").strip() or 10)
    except ValueError:
        dur = 10
    with tempfile.TemporaryDirectory(prefix="codefilm-qa-") as tmp:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-vf",
                        f"fps={max(1e-3, n / dur)},scale={w}:-2", "-frames:v", str(n), os.path.join(tmp, "%02d.png")],
                       check=False)
        out = []
        for fn in sorted(os.listdir(tmp))[:n]:
            im = (cv2.imread(os.path.join(tmp, fn)) if _HAS_CV else _imread(os.path.join(tmp, fn)))
            if im is not None:
                out.append(im)
    return out


def analyse(frames, mask_bottom=0.0):
    """mask_bottom：裁掉底部比例（字幕区），避免"锐度"被文字抬高。"""
    sharp, ew, alias, band, grain, halo, dr = [], [], [], [], [], [], []
    for im in frames:
        if mask_bottom > 0:
            h0 = im.shape[0]
            im = im[: max(16, int(h0 * (1.0 - mask_bottom))), :, :]
        g = (cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0) if _HAS_CV else _gray(im)
        gx = _sobel(g, 1, 0) if not _HAS_CV else cv2.Sobel(g, cv2.CV_32F, 1, 0, 3)
        gy = _sobel(g, 0, 1) if not _HAS_CV else cv2.Sobel(g, cv2.CV_32F, 0, 1, 3)
        mag = np.hypot(gx, gy)
        m99 = float(np.percentile(mag, 99)); mmean = float(mag.mean()) + 1e-9
        sharp.append(m99 / mmean)
        # 边缘宽度：强边处沿梯度方向的半高宽近似（用 Laplacian/梯度比）
        lap = _laplacian(g) if not _HAS_CV else cv2.Laplacian(g, cv2.CV_32F, ksize=3)
        ew.append(float(np.mean(np.abs(lap)) / (m99 + 1e-9)))
        # 抗锯齿：频谱高频段能量
        F = np.abs(np.fft.fftshift(np.fft.fft2(g)))
        h, w = F.shape
        yy, xx = np.mgrid[0:h, 0:w]
        rr = np.hypot((yy - h / 2) / (h / 2), (xx - w / 2) / (w / 2))
        hi = F[rr > 0.9].mean(); allf = F.mean() + 1e-9
        alias.append(float(hi / allf))
        # banding：平滑区的唯一色阶数
        flat = mag < 2.0
        if flat.sum() > 1000:
            vals = (g[flat] * 255).astype(np.uint8)
            band.append(float(len(np.unique(vals)) / 255.0))
        else:
            band.append(0.0)
        # 颗粒：平坦区高频残差
        resid = g - (_gauss(g, 1.2) if not _HAS_CV else cv2.GaussianBlur(g, (0, 0), 1.2))
        grain.append(float(np.median(np.abs(resid[flat])) if flat.any() else 0.0))
        halo.append(float((g > 0.95).mean()))
        dr.append(float(lap.var() / (g.var() + 1e-9)))
    med = lambda v: round(float(np.median(v)), 4) if v else 0.0
    return dict(sharp=med(sharp), edge_width=med(ew), alias=med(alias),
                banding=med(band), grain=med(grain), halo=med(halo), detail_ratio=med(dr),
                n=len(frames))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default="")
    ap.add_argument("--dir", default="")
    ap.add_argument("--mask-bottom", type=float, default=0.0, help="裁掉底部比例（字幕区）")
    ap.add_argument("--out", default="")
    ap.add_argument("--frames", type=int, default=24)
    ap.add_argument("--pair", action="store_true", help="reuse sampled frames for full and subtitle-masked checks")
    a = ap.parse_args()
    if a.video:
        sampled = frames(a.video, a.frames)
        r = analyse(sampled, a.mask_bottom)
        if a.pair:
            r = {"full": r, "masked": analyse(sampled, 0.22)}
        print(json.dumps(r, ensure_ascii=False, indent=1))
        if a.out:
            json.dump({os.path.basename(a.video): r}, open(a.out, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        return
    if not a.dir:
        sys.exit("需要 --video 或 --dir")
    rows = {}
    for base, _, files in os.walk(a.dir):
        for n in sorted(files):
            if n.lower().endswith((".mp4", ".mov", ".mkv")):
                r = analyse(frames(os.path.join(base, n), a.frames), getattr(a, "mask_bottom", 0.0))
                rows[n] = r
                print(f"  ✓ {n[:44]:44s} sharp={r['sharp']:5.1f} ew={r['edge_width']:.3f} "
                      f"alias={r['alias']:.4f} banding={r['banding']:.2f} grain={r['grain']:.4f}")
    if a.out:
        json.dump(rows, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("->", a.out)


if __name__ == "__main__":
    main()
