#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""music_check.py —— 配乐体检：把"叮叮当当"变成可量化的错误。

判据（阈值来自对"廉价配乐"的普遍共识与实测校准，可在 --print 查看）：
  H1 高频刺耳：4kHz 以上能量占比 > 12%          → 铃/钢片琴/亮合成器的典型症状
  H2 没有低频：120Hz 以下能量占比 < 8%           → 只有中高频 = 玩具感
  H3 太满：有声帧占比 > 92%（静音 < 8%）          → 每拍都响，没有呼吸
  H4 事件太密：每秒起音数 > 6                     → 音符密度过高
  H5 没有动态：段落响度标准差 < 2.5 dB             → 从头到尾一个音量
  H6 削波/过载：峰值 ≥ 0.99 且削波样本 > 0.01%    → 混音没留余量
  H7 频谱重心过高：谱心 > 3.2 kHz                 → 整体偏"脆"

用法：
  python scripts/music_check.py --wav out/score.wav [--strict] [--print]
退出码：0 通过 / 1 不通过 / 2 读不到音频
"""
from __future__ import annotations

import argparse
import json
import sys
import wave

import numpy as np

TH = {
    "hf_ratio_max": 0.12,
    "lf_ratio_min": 0.08,
    "lf_ratio_max": 0.22,
    "voiced_max": 0.90,
    "onsets_per_sec_max": 6.0,
    "dyn_std_min_db": 2.5,
    "clip_max": 0.0001,
    "centroid_max_hz": 3200.0,
}


def read_wav(path):
    with wave.open(path, "rb") as w:
        ch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if sw == 2:
        x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    elif sw == 4:
        x = np.frombuffer(raw, np.int32).astype(np.float32) / 2147483648.0
    elif sw == 1:
        x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128.0
    else:
        raise ValueError(f"不支持的位深 {sw}")
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


def analyze(x, sr):
    n = len(x)
    dur = n / sr
    # 分帧
    win = int(0.023 * sr)
    hop = int(0.010 * sr)
    if n < win:
        raise ValueError("音频太短")
    frames = np.lib.stride_tricks.sliding_window_view(x, win)[::hop]
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms + 1e-9)
    # 有声帧：比峰值低 40dB 以内
    thr = max(db.max() - 40, -100)
    voiced = db > thr

    # 频谱
    spec = np.abs(np.fft.rfft(frames * np.hanning(win), axis=1))
    freqs = np.fft.rfftfreq(win, 1 / sr)
    p = spec.sum(axis=0)
    total = max(float(p.sum()), 1e-12)
    hf = p[freqs >= 4000].sum() / total
    lf = p[freqs <= 120].sum() / total
    centroid = float((freqs * p).sum() / total)

    # 起音：能量上升沿
    d = np.diff(db)
    onset = (d > 6.0) & (db[1:] > thr)
    onsets_per_sec = float(onset.sum() / max(dur, 1e-6))

    # 动态：每 0.5s 的 RMS 标准差
    seg = int(0.5 * sr / hop)
    segs = [db[i:i + seg].mean() for i in range(0, len(db) - seg, seg)] if len(db) > seg else [db.mean()]
    dyn = float(np.std(segs)) if segs else 0.0

    peak = float(np.abs(x).max())
    clip = float((np.abs(x) >= 0.999).mean())

    return {
        "dur_s": round(dur, 2),
        "sr": sr,
        "hf_ratio": round(float(hf), 4),
        "lf_ratio": round(float(lf), 4),
        "voiced_ratio": round(float(voiced.mean()), 4),
        "silence_ratio": round(1 - float(voiced.mean()), 4),
        "onsets_per_sec": round(onsets_per_sec, 2),
        "dyn_std_db": round(dyn, 2),
        "peak": round(peak, 3),
        "clip_ratio": round(clip, 6),
        "centroid_hz": round(centroid, 0),
    }


def judge(m):
    fails = []
    if m["silence_ratio"] == 1 and m["peak"] == 0:
        return ["全轨静音：检查作曲或混音输出"]
    if m["hf_ratio"] > TH["hf_ratio_max"]:
        fails.append(f"H1 高频太多：4kHz 以上占 {m['hf_ratio']:.1%}（上限 {TH['hf_ratio_max']:.0%}）→ 换成低音区/弱音音色")
    if m["lf_ratio"] > TH["lf_ratio_max"]:
        fails.append(f"H2b 低频过量：120Hz 以下占 {m['lf_ratio']:.1%}（上限 {TH['lf_ratio_max']:.0%}）→ 手机外放会糊")
    if m["lf_ratio"] < TH["lf_ratio_min"]:
        fails.append(f"H2 没有低频：120Hz 以下只占 {m['lf_ratio']:.1%}（下限 {TH['lf_ratio_min']:.0%}）→ 加贝斯/底鼓")
    if m["voiced_ratio"] > TH["voiced_max"]:
        fails.append(f"H3 太满：有声帧 {m['voiced_ratio']:.0%}（静音只有 {m['silence_ratio']:.0%}）→ 留呼吸")
    if m["onsets_per_sec"] > TH["onsets_per_sec_max"]:
        fails.append(f"H4 起音太密：{m['onsets_per_sec']}/秒（上限 {TH['onsets_per_sec_max']}）→ 减音符")
    if m["dyn_std_db"] < TH["dyn_std_min_db"]:
        fails.append(f"H5 没有动态：响度标准差 {m['dyn_std_db']} dB（下限 {TH['dyn_std_min_db']}）→ 强弱要拉开")
    if m["peak"] >= 0.99 and m["clip_ratio"] > TH["clip_max"]:
        fails.append(f"H6 削波：峰值 {m['peak']}，削波 {m['clip_ratio']:.3%} → 降增益")
    if m["centroid_hz"] > TH["centroid_max_hz"]:
        fails.append(f"H7 谱心太高：{m['centroid_hz']:.0f}Hz（上限 {TH['centroid_max_hz']:.0f}）→ 整体偏脆")
    return fails


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", required=False)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--print", action="store_true", dest="show")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.show or not a.wav:
        print(json.dumps(TH, ensure_ascii=False, indent=1))
        if not a.wav:
            print("用法：python scripts/music_check.py --wav out/score.wav [--strict]")
        return 0

    try:
        x, sr = read_wav(a.wav)
        m = analyze(x, sr)
    except Exception as e:
        print(f"读不到音频：{e}", file=sys.stderr)
        return 2

    if a.json:
        print(json.dumps(m, ensure_ascii=False, indent=1))
    else:
        print(f"配乐体检：{a.wav}")
        print(f"  · 时长 {m['dur_s']}s · 采样 {m['sr']}Hz")
        print(f"  · 高频(≥4k) {m['hf_ratio']:.1%} · 低频(≤120) {m['lf_ratio']:.1%} · 谱心 {m['centroid_hz']:.0f}Hz")
        print(f"  · 有声 {m['voiced_ratio']:.0%} · 静音 {m['silence_ratio']:.0%} · 起音 {m['onsets_per_sec']}/s")
        print(f"  · 动态 {m['dyn_std_db']}dB · 峰值 {m['peak']} · 削波 {m['clip_ratio']:.3%}")
    fails = judge(m)
    for f in fails:
        print("  ✗", f)
    if fails:
        print(f"\n不通过：{len(fails)} 项（叮叮当当的量化症状）")
        return 1
    print("\n✓ 配乐体检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
