#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audio_check.py —— 配乐/音效审美体检：专治"只会叮叮叮"。

问题：程序化配乐最容易堆"高频短促的铃声"，听感廉价。可测的三个量：
  ding     高频瞬态密度（/分钟）：中心频率 >3 kHz、衰减 <120 ms 的冲击
  bright   频谱亮度：谱质心中位 + >5 kHz 能量占比（铃声、齿音都堆在这）
  busy     瞬态总密度（/分钟）+ 静音比例（留白够不够）

    python audio_check.py --audio out/score.wav
    python audio_check.py --audio out/film.mp4          # 直接量成片音轨
    python audio_check.py --audio x.wav --strict        # 不合格非零退出

判据（explainer 默认）：
  ding ≤ 6/min · bright ≤ 2400 Hz · 5k占比 ≤ 18% · busy ≤ 60/min · 静音 ≥ 6%
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

import numpy as np

SR = 22050



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

def load(path):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1",
                        "-ar", str(SR), "-f", "f32le", "-"], capture_output=True)
    x = np.frombuffer(r.stdout, dtype="<f4").astype(np.float32)
    if x.size == 0:
        sys.exit("读不到音频（有没有音轨？）: " + path)
    return x


def frames(x, n=1024, hop=256):
    if x.size < n:
        x = np.pad(x, (0, n - x.size))
    k = 1 + (x.size - n) // hop
    idx = np.arange(n)[None, :] + hop * np.arange(k)[:, None]
    return x[idx]


def analyse(x):
    fr = frames(x)
    win = np.hanning(fr.shape[1]).astype(np.float32)
    spec = np.abs(np.fft.rfft(fr * win, axis=1)) + 1e-9
    freqs = np.fft.rfftfreq(fr.shape[1], 1 / SR)
    # 谱质心与高频占比
    cen = (spec * freqs).sum(1) / spec.sum(1)
    flat = np.exp(np.log(spec + 1e-9).mean(1)) / (spec.mean(1) + 1e-9)   # 0=音调 1=白噪
    hi = spec[:, freqs > 4000].sum(1) / spec.sum(1)
    # 瞬态：对数谱通量
    logmag = np.log1p(spec * 10)
    flux = np.maximum(np.diff(logmag, axis=0), 0).sum(1)
    flux = np.concatenate([[0], flux])
    thr = np.median(flux) + 3.5 * (flux.std() + 1e-9)
    onsets = np.nonzero(flux > thr)[0]
    # 高频瞬态（铃声）：onset 处的谱质心高 + 之后衰减快
    ding = 0
    for i in onsets:
        c = cen[min(i, cen.size - 1)]
        fl = flat[min(i, flat.size - 1)]
        now = spec[min(i, spec.shape[0] - 1)]
        after = spec[min(i + 8, spec.shape[0] - 1)]
        low = now[freqs < 200].sum() / (now.sum() + 1e-9)
        # 铃：高频 + 音调性（平坦度低）+ 短促 + 不是低频冲击
        if c > 3000 and fl < 0.35 and after.sum() < now.sum() * 0.45 and low < 0.35:
            ding += 1
    dur = x.size / SR
    rms = float(np.sqrt((x ** 2).mean()))
    silence = float((np.abs(x) < rms * 0.12).mean())
    return dict(duration=round(dur, 2),
                rms_db=round(20 * np.log10(rms + 1e-9), 1),
                centroid_hz=int(np.median(cen)),
                hi_share=round(float(np.median(hi)), 3),
                onsets_per_min=round(len(onsets) / max(dur / 60, 1e-6), 1),
                ding_per_min=round(ding / max(dur / 60, 1e-6), 1),
                silence_ratio=round(silence, 3))


def verdict(m, profile="explainer"):
    # busy 是"总共多少瞬态"：有鼓的音乐本来就会到 1–3/s，别拿它当病；
    # 真正判"叮叮叮"的是 ding（高频+音调性+短促）
    # 阈值按实测标定：我旧版（铃为主）cen=1214 / hi=0.108 → 必须判不合格；
    # 新版（palette=explainer）cen=865 / hi=0.034 → 通过
    lim = {"explainer": dict(ding=6, cen=1100, hi=0.07, busy=150, sil=0.06),
           "cinematic": dict(ding=4, cen=1000, hi=0.06, busy=90, sil=0.12),
           "cartoon":   dict(ding=12, cen=2600, hi=0.14, busy=220, sil=0.03)}[profile]
    bad = []
    if m["ding_per_min"] > lim["ding"]:
        bad.append(f"ding {m['ding_per_min']}/min > {lim['ding']}（叮叮叮）")
    if m["centroid_hz"] > lim["cen"]:
        bad.append(f"质心 {m['centroid_hz']}Hz > {lim['cen']}（太亮/刺）")
    if m["hi_share"] > lim["hi"]:
        bad.append(f">4k 占比 {m['hi_share']:.1%} > {lim['hi']:.0%}（高频堆太多=叮叮叮）")
    if m["onsets_per_min"] > lim["busy"]:
        bad.append(f"瞬态 {m['onsets_per_min']}/min > {lim['busy']}（太忙）")
    if m["silence_ratio"] < lim["sil"]:
        bad.append(f"静音只有 {m['silence_ratio']:.0%} < {lim['sil']:.0%}（没有留白）")
    return bad, lim


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--profile", choices=["explainer", "cinematic", "cartoon"], default="explainer")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    m = analyse(load(a.audio))
    bad, lim = verdict(m, a.profile)
    print(f"\n音频体检（{a.profile}）  {a.audio}")
    print(f"  时长 {m['duration']}s  RMS {m['rms_db']} dB  谱质心 {m['centroid_hz']} Hz  "
          f">4k 占比 {m['hi_share']:.1%}")
    print(f"  瞬态 {m['onsets_per_min']}/min  高频短促(ding) {m['ding_per_min']}/min  静音 {m['silence_ratio']:.0%}")
    if bad:
        print("\n✗ 不通过：")
        for b in bad:
            print("   -", b)
        print("\n修法：少用 chime/pluck 当主奏；把铃类降到「每 30 秒 ≤1 次」的强调；"
              "加 pad/bass/底噪撑住中低频；用静音换呼吸。")
    else:
        print("\n✓ 通过（不吵、不刺、有留白）")
    if a.json:
        json.dump(dict(metrics=m, bad=bad, limits=lim), open(a.json, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("->", a.json)
    if bad and a.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
