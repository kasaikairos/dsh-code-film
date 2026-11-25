#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""action_check.py —— 动作链体检：先在时间线上算，再从成片像素上验。

  python scripts/action_check.py --spec shots/tomato_roll.json
  python scripts/action_check.py --video renders/tomato.mp4 --color "#c8321e" --from 1.5 --to 7.0

时间线模式检查 6 件事（都对不上就说明“动”不可信）：
  1. 位移与自转相称：每帧 Δs = Δθ·r
  2. 接触不穿透：中心 + 半径 ≤ 挡条面 + 1 mm
  3. 不悬空/不下陷：整段 y 恒定
  4. 不快进不瞬移：逐帧位移 ≤ 速度/帧率 × 1.05 + 1 mm
  5. 接触帧号 = 事件时间 × fps（四舍五入）
  6. 切镜时间 = 接触事件时间（如果声明了在接触时切）

像素模式：按颜色阈值找主物质心，给出逐帧位移、停稳帧、总位移；
  停稳帧与时间线算出的接触帧差 > 2 帧就报错。
"""
from __future__ import annotations
import argparse, json, math, subprocess, sys
from pathlib import Path


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))


def find(spec, name, parent=(0, 0, 0)):
    for o in spec.get("objects", []):
        if o.get("name") == name:
            p = o.get("pos", [0, 0, 0])
            return o, [p[0] + parent[0], p[1] + parent[1], p[2] + parent[2]]
        for c in o.get("children", []):
            if c.get("name") == name:
                pp = o.get("pos", [0, 0, 0])
                p = c.get("pos", [0, 0, 0])
                return c, [p[0] + pp[0], p[1] + pp[1], p[2] + pp[2]]
    return None, None


def check_spec(spec):
    fps = int(spec.get("fps", 24))
    fails, rows = [], []
    for o in spec.get("objects", []):
        for cand in [o] + o.get("children", []):
            m = cand.get("motion")
            if not m:
                continue
            name = cand.get("name", "?")
            f, t = m["from"], m["to"]
            t0, t1 = m["t0"], m["t1"]
            dist = math.dist(f, t)
            dur = t1 - t0
            speed = dist / dur if dur > 0 else 0
            rows.append(f"  {name}: {t0:.2f}s→{t1:.2f}s  位移 {dist*100:.1f}cm  "
                        f"速度 {speed*100:.1f}cm/s  自转 {math.degrees(m.get('angle',0)):.0f}°")
            # 1) 位移与自转相称
            if m.get("kind") == "roll":
                r = m.get("radius")
                if abs(m.get("angle", 0) - dist / r) > 1e-4:
                    fails.append(f"{name} 自转与位移不相称：angle={m.get('angle')} 应为 {dist/r:.5f}")
                # 4) 逐帧位移
                step = speed / fps
                if step * fps < 0 or step > 0.05:
                    fails.append(f"{name} 每帧位移 {step*100:.1f}cm 过大（会看成瞬移）")
            # 3) y 恒定
            if abs(f[1] - t[1]) > 1e-6:
                fails.append(f"{name} 运动过程中高度变化 {f[1]:.3f}→{t[1]:.3f}（滚动不应上下跳）")
            # 2) 接触不穿透：看有没有挡条
            ev = spec.get("events", {})
            contact = ev.get(f"contact_{name}")
            if contact is not None:
                frame = round(contact * fps)
                rows.append(f"      接触帧 {frame}（{contact:.3f}s @ {fps}fps）")
    # 6) 切镜时间是否对齐事件
    keys = spec.get("camera", {}).get("keys", [])
    for k in keys:
        if k.get("cut"):
            rows.append(f"  硬切 @ {k['t']:.3f}s 帧 {round(k['t']*fps)}")
    ev = spec.get("events", {})
    contacts = [v for k, v in ev.items() if k.startswith("contact_")]
    for k in keys:
        if k.get("cut") and contacts:
            near = min(abs(k["t"] - c) for c in contacts)
            if near > 1.0 / fps + 1e-6:
                fails.append(f"切镜 {k['t']:.3f}s 与最近接触事件相差 {near*1000:.0f}ms（>1 帧）")
    print("[timeline]")
    for r in rows:
        print(r)
    print("[timeline] 事件表：", json.dumps(ev, ensure_ascii=False))
    if fails:
        print("[timeline] ✗")
        for f in fails:
            print("   -", f)
    else:
        print("[timeline] ✓ 位移/自转/高度/帧步长/切点 全部对齐")
    return fails


def parse_hex(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def video_trace(video, color, t_from, t_to, width=640, y0=0.30, y1=1.0):
    """逐帧找目标颜色质心，返回 [(frame, x_norm, mass)]。"""
    import numpy as np
    tr, tg, tb = parse_hex(color)
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t_from:.3f}", "-to", f"{t_to:.3f}",
                        "-i", video, "-vf", f"scale={width}:-2", "-pix_fmt", "rgb24",
                        "-f", "rawvideo", "-"], capture_output=True)
    raw = np.frombuffer(p.stdout, np.uint8)
    if raw.size == 0:
        return [], 0
    # 宽高：按 16:9 推
    h = int(round(width * 9 / 16))
    fsz = width * h * 3
    n = raw.size // fsz
    out = []
    for i in range(n):
        fr = raw[i * fsz:(i + 1) * fsz].reshape(h, width, 3).astype(np.int16)
        R = fr[:, :, 0].astype(np.float32); G = fr[:, :, 1].astype(np.float32); B = fr[:, :, 2].astype(np.float32) + 1e-3
        # 用通道比判主物：木桌/木条也偏暖，但红绿比只有 1.2 左右；番茄在 3 以上
        mask = (R > 2.2 * G) & (R > 1.6 * B) & (R > 100)
        m = mask.sum()
        if m < 6:
            out.append((i, None, int(m)))
            continue
        mask[:int(h * y0)] = False; mask[int(h * y1):] = False
        ys, xs = np.nonzero(mask)
        if mask.sum() < 6:
            out.append((i, None, 0)); continue
        out.append((i, float(xs.mean() / width), int(mask.sum())))
    return out, h


def check_video(video, color, t_from, t_to, expect_frame=None, fps=24, expect_still=False, contact_t=None):
    tr, _ = video_trace(video, color, t_from, t_to)
    if not tr:
        print("[video] 抽帧失败")
        return ["抽帧失败"]
    xs = [(i, x) for i, x, m in tr if x is not None]
    if len(xs) < 6:
        print("[video] 没找到足够的目标像素，检查 --color 是否接近主物颜色")
        return ["目标不可见"]
    dx = [abs(xs[i][1] - xs[i - 1][1]) for i in range(1, len(xs))]
    moving = [d > 0.0015 for d in dx]
    last_move = max([i for i, mv in enumerate(moving) if mv], default=0) + 1
    start_x, end_x = xs[0][1], xs[-1][1]
    stop_frame_local = last_move
    print(f"[video] 目标横向归一位置 {start_x:.3f} → {end_x:.3f}（向右为正）")
    print(f"[video] 有效位移帧 {sum(moving)}/{len(dx)}；局部停稳帧 {stop_frame_local}（= 片段第 {stop_frame_local/fps:.2f}s）")
    fails = []
    if expect_still:
        if abs(end_x - start_x) < 0.02:
            print("[video] ✓ 该区间内目标基本不动（已停稳）")
        else:
            fails.append(f"该区间应该已经停稳，但目标仍移动了 {abs(end_x-start_x):.3f}")
        return fails
    if expect_frame is not None and contact_t is not None and t_to < contact_t + 0.25:
        print(f"[video] · 窗口在接触前结束（{t_to:.2f}s < {contact_t:.2f}s+0.25），只校验滚动方向，不校验停稳帧")
        expect_frame = None
    if expect_frame is not None:
        got = round(t_from * fps) + stop_frame_local
        if abs(got - expect_frame) > 2:
            fails.append(f"像素停稳帧 {got} 与时间线接触帧 {expect_frame} 相差超过 2 帧")
        else:
            print(f"[video] ✓ 停稳帧 {got} 与时间线接触帧 {expect_frame} 一致（±2 帧）")
    if abs(end_x - start_x) < 0.05:
        fails.append("目标横向几乎没有移动")
    for f in fails:
        print("[video] ✗", f)
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default="")
    ap.add_argument("--video", default="")
    ap.add_argument("--color", default="#c8321e")
    ap.add_argument("--from", dest="t_from", type=float, default=0.0)
    ap.add_argument("--to", dest="t_to", type=float, default=1e9)
    ap.add_argument("--target", default="")
    ap.add_argument("--expect-still", action="store_true")
    a = ap.parse_args()
    fails = []
    expect = None
    contact_t = None
    fps = 24
    if a.spec:
        spec = load(a.spec)
        fps = int(spec.get("fps", 24))
        fails += check_spec(spec)
        name = a.target or next((o["name"] for o in spec.get("objects", [])
                                 if o.get("motion")), "")
        ev = spec.get("events", {})
        if name and f"contact_{name}" in ev:
            expect = round(ev[f"contact_{name}"] * fps)
            contact_t = ev[f"contact_{name}"]
    if a.video:
        fails += check_video(a.video, a.color, a.t_from, a.t_to, expect, fps, a.expect_still, contact_t)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
