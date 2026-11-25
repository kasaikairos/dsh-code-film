#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""frame_scan.py —— 逐帧扫描器（密集版）：8 fps × 24 维特征 × 多进程。

和 deep_scan 的区别：deep_scan 是 6 fps、14 维、只出镜头表；
这里是 8 fps、480 宽、24 维**每帧**向量，落盘成 npz，用来做帧级聚类/轨迹/跨模态对齐。

24 维（全部可算，跨片可比）：
 1 luma_mean   2 luma_std   3 p05       4 p95      5 high_frac  6 shadow_frac
 7 sat_mean    8 hue_cos    9 hue_sin  10 hue_cstd 11 edge      12 edge_sharp
13 orient_conc 14 hf_ratio 15 noise_slope 16 ms_far  17 ms_mid   18 ms_near
19 layer_ratio 20 text_tile 21 colors   22 vignette 23 motion    24 zoom

    python scripts/frame_scan.py --dir <目录> --out data/frames.npz --fps 8 --w 480 [--jobs 6]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from multiprocessing import Pool

try:
    import cv2
    _HAS_CV = True
except Exception:          # 没装 opencv 也能跑（numpy 兜底，慢一点）
    cv2 = None
    _HAS_CV = False


def _rgb2gray(rgb):
    if _HAS_CV:
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    a = rgb.astype(np.float32) / 255.0
    return a @ np.array([0.299, 0.587, 0.114], np.float32)


def _rgb2hsv(rgb):
    if _HAS_CV:
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    a = rgb.astype(np.float32) / 255.0
    mx = a.max(2); mn = a.min(2); d = mx - mn + 1e-9
    h = np.zeros_like(mx)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    h = np.where(mx == r, (g - b) / d % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60.0
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-9), 0.0) * 255.0
    return np.stack([h, s, mx * 255.0], axis=-1)


def _sobel(g, dx, dy):
    if _HAS_CV:
        return cv2.Sobel(g, cv2.CV_32F, dx, dy, 3)
    if dx:
        return np.gradient(g, axis=1)
    return np.gradient(g, axis=0)


def _resize_half(g):
    if _HAS_CV:
        return cv2.resize(g, (max(2, g.shape[1] // 2), max(2, g.shape[0] // 2)),
                          interpolation=cv2.INTER_AREA)
    h, w = max(2, g.shape[0] // 2), max(2, g.shape[1] // 2)
    return g[: h * 2, : w * 2].reshape(h, 2, w, 2).mean(axis=(1, 3))


def _gauss(g, sig):
    if _HAS_CV:
        return cv2.GaussianBlur(g, (0, 0), sig)
    rad = max(1, int(round(sig * 2)))
    k = np.exp(-(np.arange(-rad, rad + 1) ** 2) / (2 * sig * sig))
    k /= k.sum()
    out = np.apply_along_axis(lambda m: np.convolve(m, k, mode="same"), 0, g)
    return np.apply_along_axis(lambda m: np.convolve(m, k, mode="same"), 1, out)
import numpy as np

FEATURES = ["luma_mean", "luma_std", "p05", "p95", "high_frac", "shadow_frac",
            "sat_mean", "hue_cos", "hue_sin", "hue_cstd", "edge", "edge_sharp",
            "orient_conc", "hf_ratio", "noise_slope", "ms_far", "ms_mid", "ms_near",
            "layer_ratio", "text_tile", "colors", "vignette", "motion", "zoom"]



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

def ffprobe_size(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        w, h = [int(x) for x in (r.stdout or "").strip().split(",")[:2]]
        return w, h
    except Exception:
        return 1920, 1080


def scan_one(args, motion_only=False):
    path, fps, width = args
    name = os.path.basename(path)
    w0, h0 = ffprobe_size(path)
    h = max(2, int(round(width * h0 / w0)))
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-vf",
                             f"fps={fps},scale={width}:{h}", "-f", "rawvideo",
                             "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    n = width * h * 3
    rows = []
    prev_g = None
    while True:
        buf = proc.stdout.read(n)
        if len(buf) < n:
            break
        rgb = np.frombuffer(buf, np.uint8).reshape(h, width, 3)
        g = _rgb2gray(rgb)
        motion = zoom = 0.0
        if prev_g is not None:
            # 在工作分辨率上算（不降采样），单位换算成"每秒移动的帧宽百分比"
            hw, hh = max(64, width // 2), max(36, h // 2)
            if _HAS_CV:
                pv8 = (np.clip(cv2.resize(prev_g, (hw, hh), interpolation=cv2.INTER_AREA), 0, 1) * 255).astype(np.uint8)
                cu8 = (np.clip(cv2.resize(g, (hw, hh), interpolation=cv2.INTER_AREA), 0, 1) * 255).astype(np.uint8)
                fl = cv2.calcOpticalFlowFarneback(pv8, cu8, None, 0.5, 3, 13, 3, 5, 1.2, 0) * 2.0
                fx, fy = fl[..., 0], fl[..., 1]
            else:
                # 无 opencv：用相邻帧差分估计"整体位移"（亮度重心位移），够验收用
                pa = np.clip(prev_g, 0, 1); ca = np.clip(g, 0, 1)
                ys, xs = np.mgrid[0:pa.shape[0], 0:pa.shape[1]]
                w1 = pa / (pa.sum() + 1e-6); w2 = ca / (ca.sum() + 1e-6)
                dxp = float((w2 * xs).sum() - (w1 * xs).sum())
                dyp = float((w2 * ys).sum() - (w1 * ys).sum())
                fx = np.full((hh, hw), dxp, np.float32)
                fy = np.full((hh, hw), dyp, np.float32)
            mag = np.hypot(fx, fy)
            motion = float(np.percentile(mag, 95)) / max(width, 1) * fps * 100.0
            cxx = (np.arange(hw) - hw / 2) / (hw / 2)
            cyy = (np.arange(hh) - hh / 2) / (hh / 2)
            gx2, gy2 = np.meshgrid(cxx, cyy)
            r2 = np.hypot(gx2, gy2) + 1e-6
            radial = fx * gx2 / r2 + fy * gy2 / r2
            zoom = float(np.percentile(np.abs(radial), 95)) / max(width, 1) * fps * 100.0
        prev_g = g
        if motion_only:
            rows.append([motion])
            continue
        hsv = _rgb2hsv(rgb)
        lit = hsv[..., 2] > 25
        sat = float(hsv[..., 1][lit].mean() / 255) if lit.any() else 0.0
        if lit.any():
            hh = hsv[..., 0][lit].astype(np.float32) * (2 * math.pi / 180)
            c, s = float(np.cos(hh).mean()), float(np.sin(hh).mean())
            hue_cstd = float(np.sqrt(max(0.0, -2 * math.log(max(math.hypot(c, s), 1e-6)))))
        else:
            c = s = hue_cstd = 0.0
        gx = _sobel(g, 1, 0)
        gy = _sobel(g, 0, 1)
        mag = np.hypot(gx, gy)
        e = (cv2.Canny((g * 255).astype(np.uint8), 70, 170) if _HAS_CV else (mag > np.percentile(mag, 92)).astype(np.uint8) * 255)
        p99 = float(np.percentile(mag, 99)) + 1e-9
        edge_sharp = p99 / (float(mag.mean()) + 1e-9)
        ang = np.arctan2(gy, gx)
        wgt = mag > np.percentile(mag, 90)
        if wgt.sum() > 100:
            orient = float(math.hypot(np.cos(ang[wgt]).mean(), np.sin(ang[wgt]).mean()))
        else:
            orient = 0.0
        gs = _resize_half(g)
        F = np.abs(np.fft.fftshift(np.fft.fft2(gs)))
        H, W = gs.shape
        yy, xx = np.mgrid[0:H, 0:W]
        rr = np.hypot((yy - H / 2) / (H / 2), (xx - W / 2) / (W / 2)) + 1e-6
        hf = float(F[rr > 0.75].mean() / (F.mean() + 1e-9))
        bands = [(0.1, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.9)]
        ev = [F[(rr >= a) & (rr < b)].mean() for a, b in bands]
        xs = np.log([np.mean([a, b]) for a, b in bands])
        slope = float(np.polyfit(xs, np.log([max(v, 1e-9) for v in ev]), 1)[0])
        ms = []
        for sig in (14.0, 5.0, 1.5):
            gb = _gauss(g, sig)
            ms.append(float(np.hypot(_sobel(gb, 1, 0), _sobel(gb, 0, 1)).mean()))
        layer_ratio = ms[2] / (ms[0] + 1e-6)
        H0, W0 = g.shape
        bh, bw = max(H0 // 8, 1), max(W0 // 8, 1)
        tiles = (e[:bh * 8, :bw * 8] > 0).reshape(bh, 8, bw, 8).mean((1, 3))
        text_tile = float(((tiles > 0.10) & (tiles < 0.55)).mean())
        q = (rgb // 16).astype(np.int32)
        colors = float(len(np.unique((q[..., 0] << 10) | (q[..., 1] << 5) | q[..., 2])))
        corner = float((g[:H0 // 5, :W0 // 5].mean() + g[-H0 // 5:, -W0 // 5:].mean()) / 2)
        center = float(g[H0 // 3:2 * H0 // 3, W0 // 3:2 * W0 // 3].mean())
        vig = corner / (center + 1e-6)
        rows.append([float(np.mean(g)), float(np.std(g)), float(np.percentile(g, 5)),
                     float(np.percentile(g, 95)), float((g > 0.94).mean()),
                     float((g < 0.06).mean()), sat, c, s, hue_cstd, float((e > 0).mean()),
                     edge_sharp, orient, hf, slope, ms[0], ms[1], ms[2], layer_ratio,
                     text_tile, colors, vig, motion, zoom])
    proc.stdout.close()
    proc.wait()
    arr = np.array(rows, np.float32) if rows else np.zeros((0, len(FEATURES)), np.float32)
    return name, arr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", nargs="*", default=[])
    ap.add_argument("--list", default="", help="文本清单：每行一个视频绝对路径")
    ap.add_argument("--out", default="data/frames.npz")
    ap.add_argument("--fps", type=int, default=8)
    ap.add_argument("--w", type=int, default=480)
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    files = []
    if a.list and os.path.exists(a.list):
        files += [ln.strip() for ln in open(a.list, encoding="utf-8-sig") if ln.strip()]
    for d in a.dir:
        for base, _, names in os.walk(d):
            for n in sorted(names):
                if n.lower().endswith((".mp4", ".mov", ".mkv")):
                    files.append(os.path.join(base, n))
    if not files:
        sys.exit("没找到视频")
    print(f"逐帧扫描 {len(files)} 支 · {a.fps} fps · {a.w} 宽 · {a.jobs} 进程", flush=True)
    data = {}
    import time
    t0 = time.time()
    with Pool(a.jobs) as pool:
        for i, (name, arr) in enumerate(pool.imap_unordered(scan_one,
                                                           [(f, a.fps, a.w) for f in files]), 1):
            data[name] = arr
            el = time.time() - t0
            print(f"  [{i}/{len(files)}] {name[:42]:42s} {arr.shape[0]:5d} 帧 "
                  f"({el/i:.1f}s/片, 剩 ~{el/i*(len(files)-i):.0f}s)", flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    np.savez_compressed(a.out, features=np.array(FEATURES), **{k: v for k, v in data.items()})
    total = sum(v.shape[0] for v in data.values())
    print(f"\n总帧数 {total} · 影片 {len(data)} → {a.out}")
    print(f"耗时 {(time.time()-t0)/60:.1f} 分钟")


if __name__ == "__main__":
    main()
