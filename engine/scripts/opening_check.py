#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""opening_check.py —— 只针对“物体穿过开口”这一已知运动的轻量几何检查（不逐帧进渲染器）。

  python scripts/opening_check.py --spec shots/mail.json --object letter \
      --aperture 0.19,0.022,0.975 --wall 0.071,0.079 --half 0.080,0.001,0.110

做三件事：
  1. 按 motion.segs 逐帧求信封中心，检查“截面在门槛内”的每一帧都落在开口矩形内；
  2. 报出前缘越过门槛、尾缘离开门槛的帧号（几何算，不靠事件声明）；
  3. 若信封比开口宽，应报“无法通过”，并给出停在哪一帧、停在哪一面。
"""
from __future__ import annotations
import argparse, json, math
from pathlib import Path


def ease(k, kind):
    if kind == "inout": return k * k * (3 - 2 * k)
    if kind == "out": return 1 - (1 - k) * (1 - k)
    if kind == "in": return k * k
    return k


def pos_at(m, t):
    segs = m.get("segs") or []
    if not segs:
        k = ease(min(1, max(0, (t - m["t0"]) / max(1e-6, m["t1"] - m["t0"]))), m.get("ease", "linear"))
        f, q = m["from"], m["to"]
        return [f[i] + (q[i] - f[i]) * k for i in range(3)]
    seg = segs[-1]
    for s in segs:
        if t < s["t1"]:
            seg = s
            break
    k = ease(min(1, max(0, (t - seg["t0"]) / max(1e-6, seg["t1"] - seg["t0"]))), seg.get("ease", "inout"))
    f, q = seg["from"], seg["to"]
    return [f[i] + (q[i] - f[i]) * k for i in range(3)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--object", default="letter")
    ap.add_argument("--aperture", required=True, help="宽,高,中心y")
    ap.add_argument("--wall", required=True, help="门槛内表面z,外表面z")
    ap.add_argument("--half", required=True, help="信封半宽,半厚,半长")
    a = ap.parse_args()
    spec = json.loads(Path(a.spec).read_text(encoding="utf-8-sig"))
    fps = int(spec.get("fps", 24))
    obj = next(o for o in spec["objects"] if o.get("name") == a.object)
    m = obj["motion"]
    w, h, cy = [float(v) for v in a.aperture.split(",")]
    z_in, z_out = [float(v) for v in a.wall.split(",")]
    hw, ht, hd = [float(v) for v in a.half.split(",")]
    frames = round(spec["duration"] * fps)
    enter = full = None
    viol = []
    for f in range(frames):
        t = f / fps
        c = pos_at(m, t)
        # 信封在门槛厚度区间内（截面正在穿过）
        overlap = (c[2] - hd < z_out) and (c[2] + hd > z_in)
        if (c[2] - hd) < z_out and enter is None:
            enter = f
        if (c[2] + hd) <= z_in and full is None:
            full = f
        if overlap and enter is not None and full is None:
            if abs(c[0]) + hw > w / 2 + 1e-6 or abs(c[1] - cy) + ht > h / 2 + 1e-6:
                viol.append(f)
    rest = pos_at(m, spec["duration"])
    print(json.dumps({
        "spec": a.spec, "object": a.object,
        "front_enters_frame": enter, "fully_inside_frame": full,
        "violating_frames": viol[:12], "violations": len(viol),
        "rest_pos": [round(v, 4) for v in rest],
        "rest_front_z": round(rest[2] - hd, 4),
        "verdict": ("通过" if full is not None and not viol else
                    ("被挡住（开口过窄）" if full is None else "穿模/超界")),
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
