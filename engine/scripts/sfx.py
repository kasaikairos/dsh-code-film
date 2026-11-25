#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sfx.py —— 环境声与动作音效（本地合成，不用素材）。

配乐负责“意图”，这里负责“现场”：房间底噪、脚步、笔尖、门。
三者分开生成再混，才能回答“这是环境、音效还是音乐”。

  python scripts/sfx.py --spec sfx.json --seconds 12 --out sfx.wav

sfx.json:
  {"room": {"level": 0.05, "hum": 0.02},
   "steps": [{"t": 3.2, "level": 0.5, "surface": "wood"}, ...],
   "pens":  [{"t0": 1.0, "t1": 2.4, "level": 0.25}],
   "stop":  [{"t": 2.45, "level": 0.3}],
   "door":  [{"t": 7.9, "level": 0.25}]}
"""
from __future__ import annotations
import argparse, json, math
import numpy as np

SR = 44100


def _t(n):
    return np.arange(n) / SR


def room(seconds, level=0.05, hum=0.02, seed=3):
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    x = rng.standard_normal(n).astype(np.float32)
    # 一阶低通，做出“房间”的闷响
    a = 0.02
    y = np.empty_like(x)
    acc = 0.0
    for i in range(0, n, 4096):
        seg = x[i:i + 4096]
        out = np.empty_like(seg)
        for j, v in enumerate(seg):
            acc += a * (v - acc)
            out[j] = acc
        y[i:i + 4096] = out
    y /= max(1e-6, np.max(np.abs(y)))
    h = 0.5 * np.sin(2 * np.pi * 50 * _t(n)) + 0.3 * np.sin(2 * np.pi * 100 * _t(n))
    return (level * y + hum * h).astype(np.float32)


def step(seconds, t, level=0.5, surface="wood", seed=1):
    """一步：低频“咚”+ 一层窄带噪声的鞋底摩擦。"""
    rng = np.random.default_rng(seed)
    n = int(0.16 * SR)
    tt = _t(n)
    f0 = {"wood": 92.0, "stone": 120.0, "carpet": 70.0}.get(surface, 92.0)
    thump = np.sin(2 * np.pi * f0 * tt) * np.exp(-tt * 26)
    noise = rng.standard_normal(n) * np.exp(-tt * 45)
    # 简易带通：一阶差分 + 平滑
    noise = np.convolve(noise, [1, -0.7], mode="same")
    out = (0.8 * thump + 0.35 * noise) * level
    return out.astype(np.float32), t


def pen(seconds, t0, t1, level=0.25, seed=5):
    """笔尖：一串短促的高频摩擦，句尾带一小段拖尾。"""
    rng = np.random.default_rng(seed)
    dur = max(0.05, t1 - t0)
    n = int(dur * SR)
    tt = _t(n)
    base = rng.standard_normal(n)
    base = np.convolve(base, [1, -0.95], mode="same")        # 高通，纸面质感
    # 写字的一顿一顿：用 6–9 Hz 的幅度调制
    am = 0.55 + 0.45 * np.sin(2 * np.pi * (6 + 3 * rng.random()) * tt)
    env = np.minimum(1, tt / 0.02) * np.minimum(1, (dur - tt) / 0.08)
    return (level * base * am * env).astype(np.float32), t0


def stop(seconds, t, level=0.3, seed=7):
    """笔停下：一次短刮擦 + 尾音收干。"""
    rng = np.random.default_rng(seed)
    n = int(0.22 * SR)
    tt = _t(n)
    scrape = rng.standard_normal(n) * np.exp(-tt * 30)
    scrape = np.convolve(scrape, [1, -0.85], mode="same")
    tap = np.sin(2 * np.pi * 210 * tt) * np.exp(-tt * 40)
    return ((0.6 * scrape + 0.25 * tap) * level).astype(np.float32), t


def door(seconds, t, level=0.25, seed=9):
    rng = np.random.default_rng(seed)
    n = int(0.35 * SR)
    tt = _t(n)
    body = np.sin(2 * np.pi * 68 * tt) * np.exp(-tt * 12)
    creak = np.convolve(rng.standard_normal(n), [1, -0.6], mode="same") * np.exp(-tt * 18)
    return ((0.7 * body + 0.18 * creak) * level).astype(np.float32), t



def hum(seconds, level=0.10, hz=58.0, wobble=0.6):
    """电机/传送带底噪：低频基频 + 齿形谐波 + 极慢的起伏（不是音乐，是机器）。"""
    n = int(seconds * SR); t = _t(n)
    base = np.sin(2*np.pi*hz*t) + 0.45*np.sin(2*np.pi*hz*2*t) + 0.22*np.sin(2*np.pi*hz*3*t)
    mod = 1 + 0.12*np.sin(2*np.pi*wobble*t) + 0.06*np.sin(2*np.pi*0.17*t+1.3)
    return (level*base*mod).astype(np.float32)


def slide(seconds, t, dur=0.55, level=0.18, seed=11):
    """纸箱在皮带上摩擦：带通噪声，随速度线性起落。"""
    rng = np.random.default_rng(seed)
    n = int(dur*SR); tt = _t(n)
    x = rng.standard_normal(n)
    x = np.convolve(x, [1, -0.55], mode="same")          # 去掉最低频
    x = np.convolve(x, np.ones(6)/6, mode="same")         # 去掉最刺的高频
    env = np.minimum(1, tt/0.08) * np.minimum(1, (dur-tt)/0.12)
    return (level*x*env).astype(np.float32), t


def servo(seconds, t, dur=0.42, level=0.16, seed=13):
    """挡板抬起：小电机，音高缓慢上行 + 一点点齿轮。"""
    n = int(dur*SR); tt = _t(n)
    f = 180 + 90*(tt/dur)
    ph = 2*np.pi*np.cumsum(f)/SR
    tone = 0.6*np.sin(ph) + 0.25*np.sin(2*ph) + 0.12*np.sin(3*ph)
    grit = np.random.default_rng(seed).standard_normal(n)
    grit = np.convolve(grit, [1, -0.8], mode="same")*0.12
    env = np.minimum(1, tt/0.03) * np.minimum(1, (dur-tt)/0.06)
    return (level*(tone+grit)*env).astype(np.float32), t


def clack(seconds, t, level=0.20, seed=17):
    """挡板到位的机械止挡：短促、干。"""
    n = int(0.09*SR); tt = _t(n)
    body = np.sin(2*np.pi*320*tt)*np.exp(-tt*60)
    tick = np.random.default_rng(seed).standard_normal(n)*np.exp(-tt*120)
    return (level*(0.7*body+0.4*tick)).astype(np.float32), t


def rustle(seconds, t, dur=0.5, level=0.10, seed=19):
    """纸板/胶带被带动的一点簌声。"""
    rng = np.random.default_rng(seed)
    n = int(dur*SR); tt = _t(n)
    x = rng.standard_normal(n)
    x = np.convolve(x, [1, -0.92], mode="same")
    env = np.minimum(1, tt/0.05) * np.exp(-tt*4.5)
    return (level*x*env).astype(np.float32), t

def build(spec, seconds):
    n = int(seconds * SR)
    bed = np.zeros(n, np.float32)
    r = spec.get("room")
    if r:
        bed += room(seconds, r.get("level", 0.05), r.get("hum", 0.02))
    h = spec.get("hum")
    if h:
        bed += hum(seconds, h.get("level", 0.10), h.get("hz", 58.0), h.get("wobble", 0.6))
    def put(buf, at):
        i = max(0, int(at * SR))
        m = min(len(buf), n - i)
        if m > 0:
            bed[i:i + m] += buf[:m]
    for s in spec.get("steps", []):
        buf, at = step(seconds, s["t"], s.get("level", 0.5), s.get("surface", "wood"))
        put(buf, at)
    for p in spec.get("pens", []):
        buf, at = pen(seconds, p["t0"], p["t1"], p.get("level", 0.25))
        put(buf, at)
    for s in spec.get("stop", []):
        buf, at = stop(seconds, s["t"], s.get("level", 0.3))
        put(buf, at)
    for d in spec.get("door", []):
        buf, at = door(seconds, d["t"], d.get("level", 0.25))
        put(buf, at)
    for s in spec.get("slides", []):
        buf, at = slide(seconds, s["t"], s.get("dur", 0.55), s.get("level", 0.18))
        put(buf, at)
    for s in spec.get("servos", []):
        buf, at = servo(seconds, s["t"], s.get("dur", 0.42), s.get("level", 0.16))
        put(buf, at)
    for s in spec.get("clacks", []):
        buf, at = clack(seconds, s["t"], s.get("level", 0.20))
        put(buf, at)
    for s in spec.get("rustles", []):
        buf, at = rustle(seconds, s["t"], s.get("dur", 0.5), s.get("level", 0.10))
        put(buf, at)
    peak = float(np.max(np.abs(bed))) or 1.0
    return 0.9 * bed / max(peak, 0.42)


def write_wav(path, mono):
    import wave
    x = np.clip(mono, -1, 1)
    # 单声道复制成立体声，留一点点宽度（右声道迟 8 个采样）
    right = np.concatenate([np.zeros(8, np.float32), x[:-8]])
    st = np.stack([x, right], axis=1)
    pcm = (st * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--seconds", type=float, required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    spec = json.loads(open(a.spec, encoding="utf-8-sig").read())
    mix = build(spec, a.seconds)
    write_wav(a.out, mix)
    print(f"sfx -> {a.out}  {a.seconds:.2f}s  steps={len(spec.get('steps', []))} "
          f"pens={len(spec.get('pens', []))} stop={len(spec.get('stop', []))}")


if __name__ == "__main__":
    main()
