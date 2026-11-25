#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""music_score.py —— 按"画面事件"配乐（替代 music_v2.py）。

为什么要重写（实测结论，见 knowledge/rules/配乐.md）：
  · 旧 ks_pluck 的 damp=0.996 → T60 15.7s、谐波等幅、无 ADSR → 听起来是铃不是拨弦，
    且占 A 计权响度的 88% —— 这就是"叮叮当当"的本体
  · 全曲零留白、逐小节 RMS 只差 1.9 dB、单声道、无混响
  · 73.6% 的能量在 80–200Hz（手机听不见），200–500Hz 只有 3.5%（没有"肉"）

本引擎按猫和老鼠式配乐的可复用规律设计：
  1) 编制 2–4 个声部，硬上限 6；每句留 25–40% 休止
  2) 能量重心放在 150Hz–2kHz；低频 60–200Hz；高频只做 ≤2s 的点缀
  3) 不用铃/钢片琴/亮合成器；用贝斯躯体 + pad + 中音区 lead + 短拨弦
  4) 动机 3–7 个音；变形只改音色/音区/速度
  5) 撞击点强制全停 ≥0.3s（让画面呼吸）
  6) 动态跟画面强度走（段间 ≥6dB），不靠推增益

用法：
  python scripts/music_score.py --story out/story.json --out out/score.wav
  python scripts/music_score.py --seconds 8 --bpm 84 --out out/score.wav
  python scripts/music_score.py --emotion out/emotion.json --out out/score.wav
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys

import numpy as np

SR = 44100
rng = np.random.default_rng(20261121)

# 小调五声：C 自然小调取 1 2 b3 5 6（避免大调"欢快铃"感）
SCALE = [0, 2, 3, 7, 9]


def mtof(m):
    return 440.0 * (2 ** ((m - 69) / 12.0))


def env(n, a, d, s, r, sr=SR):
    a, d, r = int(a * sr), int(d * sr), int(r * sr)
    sus = max(0, n - a - d - r)
    e = np.concatenate([
        np.linspace(0, 1, max(1, a), endpoint=False),
        np.linspace(1, s, max(1, d), endpoint=False) if d else np.array([], np.float32),
        np.full(sus, s, np.float32),
        np.linspace(s, 0, max(1, r)) if r else np.array([], np.float32),
    ]).astype(np.float32)
    if len(e) < n:
        e = np.pad(e, (0, n - len(e)))
    return e[:n]


def lp_fft(x, cutoff):
    """零相位低通（FFT 掩蔽，离线够用且比逐样本循环快两个数量级）。"""
    n = len(x)
    if n < 8:
        return x
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    mask = 1.0 / (1.0 + (f / max(cutoff, 20.0)) ** 4)
    return np.fft.irfft(X * mask, n).astype(np.float32)


def hp_fft(x, cutoff):
    n = len(x)
    if n < 8:
        return x
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    mask = 1.0 - 1.0 / (1.0 + (f / max(cutoff, 20.0)) ** 4)
    return np.fft.irfft(X * mask, n).astype(np.float32)


def bass_note(freq, dur, gain):
    """贝斯躯体：基频 + 二三次谐波（手机外放靠 2 次谐波听到）。"""
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = np.sin(2 * np.pi * freq * t)
    s += 0.34 * np.sin(2 * np.pi * 2 * freq * t)
    s += 0.12 * np.sin(2 * np.pi * 3 * freq * t)
    s *= env(n, 0.015, 0.09, 0.72, min(0.22, dur * 0.35))
    return (gain * 0.55 * s).astype(np.float32)


def pad_chord(freqs, dur, gain):
    """三声部 pad：每音两条微失谐锯齿 → 低通 1.4k；高通了 90Hz 保留躯体。"""
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n, np.float32)
    for i, f in enumerate(freqs):
        for det in (-0.004, 0.004):
            ph = 2 * np.pi * f * (1 + det) * t + i * 0.7
            saw = 2 * (ph / (2 * np.pi) % 1.0) - 1
            out += saw.astype(np.float32) * (0.18 / len(freqs))
    out = lp_fft(out, 2400)
    out = hp_fft(out, 120)
    out *= env(n, 0.45, 0.25, 0.78, min(0.5, dur * 0.4))
    return (gain * out).astype(np.float32)


def lead_note(freq, dur, gain, vib=0.0035):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = freq * (1 + vib * np.sin(2 * np.pi * 5.2 * t))
    tri = 2 * np.abs(2 * (f * t % 1.0) - 1) - 1
    s = lp_fft(tri.astype(np.float32), 2600)
    s *= env(n, 0.012, 0.08, 0.62, min(0.18, dur * 0.4))
    return (gain * 0.42 * s).astype(np.float32)


def pluck_note(freq, dur, gain, t60=0.5):
    """真拨弦：Karplus-Strong，按 T60 反算每圈衰减（旧版 damp=0.996 是错的）。"""
    n = int(dur * SR)
    N = max(2, int(SR / freq))
    damp = 10 ** (-3.0 / (freq * t60))
    buf = rng.uniform(-1, 1, N).astype(np.float32)
    buf = lp_fft(buf, 3200)
    out = np.zeros(n, np.float32)
    for i in range(n):
        out[i] = buf[i % N]
        buf[i % N] = damp * 0.5 * (buf[i % N] + buf[(i + 1) % N])
    fade = min(int(0.04 * SR), n)
    if fade:
        out[-fade:] *= np.linspace(1, 0, fade)
    out *= env(n, 0.004, 0.05, 0.55, min(0.1, dur * 0.3))
    return (gain * 0.5 * out).astype(np.float32)


def kick(dur=0.16, gain=0.5):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 62 * np.exp(-t * 16) + 42
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 18)
    return (gain * s).astype(np.float32)


def wood(dur=0.07, gain=0.22):
    n = int(dur * SR)
    t = np.arange(n) / SR
    body = np.sin(2 * np.pi * 196 * t) * np.exp(-t * 55)
    click = rng.normal(0, 1, n) * np.exp(-t * 160) * 0.25
    return (gain * (body + click)).astype(np.float32)


def reverb(x, wet=0.22):
    """Schroeder：4 comb + 2 allpass，纯 numpy。"""
    def comb(sig, delay_ms, fb):
        d = int(delay_ms * SR / 1000)
        y = np.zeros_like(sig)
        y[:d] = sig[:d]
        for i in range(d,len(sig),d):
            count = min(d,len(sig)-i)
            y[i:i+count] = sig[i:i+count] + fb*y[i-d:i-d+count]
        return y

    def allpass(sig, delay_ms, g=0.5):
        d = int(delay_ms * SR / 1000)
        y = np.zeros_like(sig)
        y[:d] = -g*sig[:d]
        for i in range(d,len(sig),d):
            count = min(d,len(sig)-i)
            y[i:i+count] = -g*sig[i:i+count] + sig[i-d:i-d+count] + g*y[i-d:i-d+count]
        return y

    w = np.zeros_like(x)
    for dms, fb in ((29.7, 0.78), (37.1, 0.76), (41.1, 0.74), (43.7, 0.72)):
        w += comb(x, dms, fb)
    w /= 4
    w = allpass(w, 5.0)
    w = allpass(w, 1.7)
    w = hp_fft(w, 140)
    return x + wet * w


# ── 编曲 ────────────────────────────────────────────────────────────
def plan_sections(total, bpm, emotion=None):
    """四段：静 → 起 → 顶 → 收。强度跟情绪曲线走，段间至少差 6dB。"""
    bars = max(4, int(round(total / (4 * 60 / bpm))))
    secs = []
    for b in range(bars):
        u = (b + 0.5) / bars
        if bars <= 6:
            u = [0.12, 0.38, 0.72, 0.86, 0.5, 0.7][b % 6]
        if u < 0.25:
            inten, name = 0.28, "calm"
        elif u < 0.5:
            inten, name = 0.52, "build"
        elif u < 0.8:
            inten, name = 0.86, "peak"
        else:
            inten, name = 0.48, "resolve"
        if emotion and isinstance(emotion.get("curve"), list) and emotion["curve"]:
            c = emotion["curve"]
            inten = float(c[min(len(c) - 1, int(u * len(c)))])
        secs.append({"bar": b, "inten": inten, "name": name,
                     "rest": name in ("calm",) and b % 2 == 1,
                     "full_rest": name == "calm" and b % 2 == 1})
    return secs, bars


def beat_hits(story):
    """从 story.beats 取打点：段首轻击、收束前留呼吸、峰值重击。"""
    hits = []
    if not isinstance(story, dict):
        return hits
    beats = sorted([b for b in (story.get("beats") or []) if isinstance(b, dict)],
                   key=lambda b: b.get("t0") or 0)
    if not beats:
        return hits
    n = len(beats)
    for i, b in enumerate(beats):
        t0 = float(b.get("t0") or 0)
        if i == 0:
            hits.append((t0, "soft"))          # 开场：只给一个轻点
        elif i == n - 1:
            hits.append((t0, "breath"))        # 收束前：留呼吸
        elif i == max(1, n // 2):
            hits.append((t0, "impact"))        # 中段峰值：重击
        else:
            hits.append((t0, "tick"))
    return hits


def compose(total, bpm, seed=7, emotion=None, story=None, style="classic", cues=()):
    rng2 = np.random.default_rng(seed)
    spb = 60.0 / bpm
    bar_len = 4 * spb
    n = int(total * SR) + int(0.3 * SR)
    bus = {k: np.zeros(n, np.float32) for k in ("bass", "pad", "mid", "lead", "pluck", "perc")}

    def add(name, sig, t0, gain=1.0):
        i = int(round(t0 * SR))
        if i < 0:                      # 负起点：裁掉超出部分（旧版这里崩）
            sig, i = sig[-i:], 0
        if i >= n:
            return
        j = min(i + len(sig), n)
        seg = sig[: j - i]
        bus[name][i:j] += gain * seg

    secs, bars = plan_sections(total, bpm, emotion)
    # 和声：i–VI–III–VII（A 小调味道，避免大调儿歌）
    prog = [[0, 3, 7], [-4, 0, 3], [-9, -5, -1], [-2, 2, 5]]
    if style == "tide":
        prog = [[0,4,7,11],[-5,0,4,7],[-3,0,4,7],[-7,-2,2,5]]
    elif style == "pulse":
        prog = [[0,3,7],[-2,2,5],[-5,0,5],[2,5,9]]
    motif_root = {"classic":69,"tide":65,"pulse":62}[style]  # A4

    for s in secs:
        b = s["bar"]
        t_bar = b * bar_len
        if s.get("full_rest"):
            continue
        inten = s["inten"]
        chord = prog[b % len(prog)]
        root = motif_root - 12

        if style == "pulse":
            for k in (0,.75,1.5,2.75):
                add("pluck",pluck_note(mtof(root+12+chord[int(k*2)%len(chord)]),spb*.55,.7,t60=.24),
                    t_bar+k*spb,.22+.12*inten)
        elif style == "tide":
            for k in (0,1.5,3):
                add("lead",lead_note(mtof(root+12+chord[int(k)%len(chord)]),spb*1.4,.6),
                    t_bar+k*spb,.18)
        # pad：整小节，rest 小节缩短
        dur = bar_len * (0.72 if s["rest"] else 1.02)
        add("pad", pad_chord([mtof(root + i) for i in chord], dur, 1.0),
            t_bar, gain=0.36 + 0.30 * inten)

        # 中频"肉"：根音中音区短和弦（补 200–500Hz，旧版这里只有 3.5%）
        if s["name"] in ("build", "peak", "resolve"):
            add("mid", pad_chord([mtof(root + i) for i in chord], bar_len * 0.5, 1.0),
                t_bar, gain=0.17 + 0.14 * inten)

        # bass：每小节两下（1、3 拍），rest 小节只留一声
        for k, at in enumerate((0.0, 2.0) if not s["rest"] else (0.0,)):
            add("bass", bass_note(mtof(root - 12 + chord[0]), bar_len * 0.42, 1.0),
                t_bar + at * spb, gain=0.34 + 0.30 * inten)

        # lead：动机 3–7 音，只在 build/peak，且每 2 小节一次
        if s["name"] in ("build", "peak", "resolve") and b % 2 == 0:
            notes = [SCALE[(b + i) % len(SCALE)] for i in range(5)]
            step = spb * (0.5 if inten > 0.7 else 1.0)
            for i, deg in enumerate(notes):
                if rng2.random() < 0.18:               # 留白：动机里也漏音
                    continue
                add("lead", lead_note(mtof(root + 24 + deg), step * 0.9, 1.0),
                    t_bar + i * step + rng2.uniform(-0.012, 0.012),
                    gain=(0.34 + 0.26 * inten) * rng2.uniform(0.88, 1.08))

        # pluck：只在峰值段，8 分音符三连（不齐发、不每拍填满）
        if s["name"] == "peak" and b % 2 == 1:
            for i, (beat, g) in enumerate(((0.5, 0.18), (1.5, 0.14), (2.5, 0.20), (3.5, 0.12))):
                add("pluck", pluck_note(mtof(root + 24 + SCALE[i % len(SCALE)]),
                                        bar_len * 0.30, 1.0, t60=0.42),
                    t_bar + beat * spb + rng2.uniform(-0.010, 0.010), gain=g)

        # 打击：峰值段每两小节一次底鼓 + 偶发木块
        if s["name"] == "peak" and style != "tide":
            add("perc", kick(gain=0.55), t_bar, gain=0.9)
            if b % 2 == 0:
                add("perc", wood(gain=0.2), t_bar + 3.5 * spb, gain=0.8)

    # ── 按 story.beats 打点（Mickey-mousing 的简化版：点要少、位置要准）──
    for t0, kind in [*beat_hits(story), *((float(c["time"]), c["kind"]) for c in cues)]:
        if not (0 <= t0 < total - 0.05):
            continue
        if kind == "impact":
            add("perc", kick(dur=0.22, gain=0.5), t0, gain=0.85)
            add("bass", bass_note(mtof(45), bar_len * 0.5, 1.0), t0, gain=0.30)
        elif kind == "tick":
            add("perc", wood(dur=0.06, gain=0.16), t0, gain=0.7)
        elif kind == "soft":
            add("perc", wood(dur=0.05, gain=0.10), t0, gain=0.5)
        # breath：只挖静音，不加音
        if kind == "breath":
            i0, i1 = int(max(0, t0 - 0.28) * SR), int(min(n, t0 + 0.02) * SR)
            if i1 > i0:
                e = np.ones(i1 - i0, np.float32)
                f = min(int(0.08 * SR), len(e))
                e[:f] *= np.linspace(1, 0, f)
                e[f:] = 0.0
                for b in bus:
                    bus[b][i0:i1] *= e

    # ── 混音：pad/lead 送混响；无 1.5–7k 全局提亮（旧版 +0.38 是病因）──
    wet_src = bus["pad"] * 0.8 + bus["lead"] * 0.5
    bus["pad"] = bus["pad"] + reverb(wet_src, 0.16) * 0.45
    mix = (bus["bass"] * (0.6 if total < 6.0 else 0.9) + bus["pad"] * 1.0 + bus["mid"] * 1.1 +
           bus["lead"] * 0.9 + bus["pluck"] * 0.85 + bus["perc"] * 0.7)

    # 动态：整段慢速自动化（段间拉开 ≥6dB）
    t = np.arange(n) / SR
    auto = np.ones(n, np.float32)
    for s in secs:
        i0, i1 = int(s["bar"] * bar_len * SR), min(n, int((s["bar"] + 1) * bar_len * SR))
        if i1 > i0:
            g = 0.55 + 0.55 * s["inten"]
            auto[i0:i1] = np.linspace(auto[max(0, i0 - 1)], g, i1 - i0)
    mix = mix * auto

    # 真停顿：固定两个"呼吸点"，再按段落补（保证留白预算 ≥10%）
    stop_win = [total * 0.30, total * 0.64] if style == "classic" else []
    every = 2 if bars <= 6 else 4
    for s2 in secs:
        if (s2["bar"] + 1) % every == 0 and s2["bar"] < bars - 1:
            t0s = (s2["bar"] + 1) * bar_len - 0.55
            if 0 < t0s < total - 0.4:
                stop_win.append(t0s)
    for t0s in stop_win:
        i0, i1 = int(t0s * SR), min(n, int((t0s + 0.55) * SR))
        if i1 > i0:
            env_stop = np.ones(i1 - i0, np.float32)
            f_in = min(int(0.06 * SR), len(env_stop))
            env_stop[:f_in] *= np.linspace(1, 0, f_in)
            env_stop[f_in:] = 0.0
            mix[i0:i1] *= env_stop
            f_out = min(int(0.10 * SR), n - i1)
            if f_out > 0:
                mix[i1:i1 + f_out] *= np.linspace(0, 1, f_out)

    # 短片里中频事件少，低频占比会偏高：把低切抬高一点、贝斯收一点
    SHORT = total < 6.0
    mix = hp_fft(mix, 90 if SHORT else 70)
    mix = lp_fft(mix, 9000)
    peak = float(np.abs(mix).max()) + 1e-9
    mix = np.tanh(mix / peak * 1.15) / np.tanh(1.15) * 0.90

    # 首尾 0.25s 淡入淡出（旧版片头比全曲还响）
    f = int(0.25 * SR)
    mix[:f] *= np.linspace(0, 1, f)
    mix[-int(0.30 * SR):] *= np.linspace(1, 0, int(0.30 * SR))
    return mix.astype(np.float32)


def widen(x):
    """单声道 → 立体声：右声道 8ms 延迟 + 轻微去相关。"""
    d = int(0.008 * SR)
    r = np.concatenate([np.zeros(d, np.float32), x[:-d]])
    return np.stack([x * 0.62 + r * 0.10, r * 0.62 + x * 0.10], axis=1)


def write_wav(path, data):
    import wave
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    st = widen(data) if data.ndim == 1 else data
    st = np.clip(st, -1, 1)
    pcm = (st * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", default="", help="story.json（按 beats 定长度与事件）")
    ap.add_argument("--emotion", default="", help="emotion.json（用它的 curve 做动态）")
    ap.add_argument("--seconds", type=float, default=0)
    ap.add_argument("--style",choices=["classic","tide","pulse","ensemble"],default="classic")
    ap.add_argument("--mood", choices=["lyric","playful","suspense"], default="lyric")
    ap.add_argument("--arrangement", choices=["chamber","mechanical","light","motifA","motifB","phrases","voicelead","legato","chamber_live"], default="chamber_live")
    ap.add_argument("--no-pedal", action="store_true")
    cue_source=ap.add_mutually_exclusive_group()
    cue_source.add_argument("--cues", default="[]", help="JSON array of music cues")
    cue_source.add_argument("--cues-file", type=Path, help="JSON score or cue array on disk")
    ap.add_argument("--bpm", type=float, default=84)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    story = None
    if a.story:
        try:
            story = json.load(open(a.story, encoding="utf-8-sig"))
        except Exception as e:
            print(f"读不到 story：{e}", file=sys.stderr)
            return 2
    emo = None
    if a.emotion:
        try:
            emo = json.load(open(a.emotion, encoding="utf-8-sig"))
        except Exception:
            emo = None

    total = a.seconds
    if not total and story:
        total = float(story.get("seconds") or 0)
    if not total and emo:
        total = float(emo.get("seconds") or emo.get("duration") or 0)
    if not total:
        total = 8.0

    if total<=0 or not 20<=a.bpm<=300:
        ap.error("需要正时长与 20–300 BPM")
    cue_data=json.loads(a.cues_file.read_text(encoding="utf-8-sig") if a.cues_file else a.cues)
    cues=cue_data["cues"] if isinstance(cue_data,dict) else cue_data
    explicit_score=isinstance(cue_data,dict) and cue_data.get("explicit_score",False)
    if a.style=="ensemble" and a.arrangement=="chamber_live":
        import chamber_live
        if not explicit_score and not any(c.get("kind")=="phrase" for c in cues):
            cues=chamber_live.original_score(total,a.bpm,a.seed,a.mood)
        mix=chamber_live.compose(total,a.bpm,cues)
    elif a.style=="ensemble" and a.arrangement=="legato":
        import legato
        if not any(c.get("kind")=="phrase" for c in cues):
            cues=legato.phrase_score(total,a.bpm,a.seed,a.mood)
        mix=legato.compose(total,a.bpm,cues)
    elif a.style=="ensemble" and a.arrangement=="voicelead":
        from harmony import harmonize
        import motif
        mix=motif.compose_phrases(total,a.bpm,harmonize(cues))
    elif a.style=="ensemble" and a.arrangement=="phrases":
        import motif
        mix=motif.compose_phrases(total,a.bpm,cues)
    elif a.style=="ensemble" and a.arrangement in ("motifA","motifB"):
        import motif
        anchor = dict(next((c for c in cues if c.get("kind")=="anchor"), {"time":1.7}))
        start = float(anchor["time"])
        if "pull" not in anchor:
            responses = [float(c["time"]) for c in cues if c.get("kind")=="pull" and float(c["time"])>=start]
            anchor["pull"] = min(responses, default=start+2.2)
        anchors = [anchor]
        mix = (motif.compose_A if a.arrangement=="motifA" else motif.compose_B)(total,a.bpm,a.seed,anchors)
    elif a.style=="ensemble" and a.arrangement=="light":
        import ensemble
        mix=ensemble.compose_light(total,a.bpm,a.seed,cues)
    elif a.style=="ensemble":
        import ensemble
        if not cues:
            cues=[{"time":t,"kind":k} for t,k in beat_hits(story)]
        mix=ensemble.compose(total,a.bpm,a.seed,a.mood,cues,a.arrangement,not a.no_pedal)
    else:
        mix=compose(total,a.bpm,a.seed,emo,story,a.style,cues)
    write_wav(a.out, mix)
    print(f"配乐 → {a.out}（{total:.1f}s · {a.bpm:.0f}BPM · 立体声 · {SR}Hz）")
    print("体检：python scripts/music_check.py --wav " + a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
