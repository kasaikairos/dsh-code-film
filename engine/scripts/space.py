#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""space.py —— 空间与材质镜头：声明式场景 → 静帧 / 视频。

场景 JSON 只描述“有什么”：物体（形状/尺寸/材质/层）、灯、湿地参数、大气、机位。
不需要写任何 HTML。

  python scripts/space.py --scene shots/corner.json --still 2.4 --out review/a.png
  python scripts/space.py --scene shots/corner.json --stills 0,1.2,2.4 --outdir review/
  python scripts/space.py --scene shots/corner.json --out out/corner.mp4 --preset hd --fps 24
  python scripts/space.py --scene shots/corner.json --audit          # 只跑构图体检，不出片

构图体检（--audit）在 Python 里复用同一套机位数学，把每个物体的包围盒投到画面上，
报告：主体覆盖率、是否出框、画面重心、地平线高度。渲染前先看这一行结论。
"""
from __future__ import annotations
import argparse, json, math, os, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TOOLS = ROOT / "tools"

DEFAULTS = {
    "duration": 6, "fps": 24, "seed": 7,
    "camera": {"mode": "orbit", "az": 38, "el": 17, "dist": 15, "fov": 34,
               "target": [0, 1.1, 0], "azDrift": 7, "distDrift": 0.0, "rise": 0.0,
               "focus": 15, "aperture": 0.55},
    "ground": {"y": 0, "size": 46, "kind": "wet_asphalt", "tint": "#0b0e14",
               "rough": 0.34, "reflectivity": 0.62, "puddle": 0.45, "ripple": 0.5},
    "atmosphere": {"fog": {"color": "#101724", "density": 0.032},
                   "rain": {"count": 0}},
    "post": {"exposure": 1.12, "bloom": 0.30, "grain": 0, "vignette": 0.34, "dof": 0.55},
}


def deep(base, over):
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = deep(base.get(k), v)
        return out
    return over if over is not None else base


def cam_at(spec, t):
    c = deep(DEFAULTS["camera"], spec.get("camera", {}))
    d = float(spec.get("duration", 6)) or 1.0
    k = t / d
    az = math.radians(c["az"] + c.get("azDrift", 0) * k)
    el = math.radians(c["el"] + c.get("elDrift", 0) * k)
    dist = c["dist"] + c.get("distDrift", 0) * k
    tgt = list(c["target"])
    tgt[1] += c.get("rise", 0) * k
    pos = [tgt[0] + math.sin(az) * math.cos(el) * dist,
           tgt[1] + math.sin(el) * dist,
           tgt[2] + math.cos(az) * math.cos(el) * dist]
    if c.get("mode") == "dolly":
        s = 0.92 + 0.10 * k
        pos = [tgt[i] + (pos[i] - tgt[i]) * s for i in range(3)]
    return pos, tgt, c


def bbox_of(o):
    """粗略包围盒：只按 size/pos/rot 的 y 轴旋转估计（够用于构图体检）。"""
    if o.get("kind") == "group":
        boxes = [bbox_of(c) for c in o.get("children", [])]
        boxes = [b for b in boxes if b]
        if not boxes:
            return None
        gx, gy, gz = o.get("pos", [0, 0, 0])
        return (min(b[0] for b in boxes) + gx, min(b[1] for b in boxes) + gy, min(b[2] for b in boxes) + gz,
                max(b[3] for b in boxes) + gx, max(b[4] for b in boxes) + gy, max(b[5] for b in boxes) + gz)
    p = o.get("pos", [0, 0, 0])
    if o.get("kind") == "instanced":
        if "transforms" in o:
            bounds = []
            for pose in o["transforms"]:
                origin = pose.get("pos", [0, 0, 0])
                # Leaves are rooted at the origin and lie within 1.2 units before scaling.
                r = 1.2 * max(map(abs, pose.get("scale", [1, 1, 1])))
                bounds.append([*(v-r for v in origin), *(v+r for v in origin)])
            if not bounds:
                return None
            return (*(min(b[i] for b in bounds) for i in range(3)),
                    *(max(b[i] for b in bounds) for i in range(3,6)))
        a = o.get("area", [2, 2])
        s = o.get("size", [1, 1, 1])
        r = o.get("r", 0.5)
        return (p[0] - a[0] / 2, p[1] - r, p[2] - a[1] / 2,
                p[0] + a[0] / 2, p[1] + r, p[2] + a[1] / 2)
    s = o.get("size", [o.get("r", 0.5) * 2, o.get("h", o.get("r", 0.5) * 2), o.get("r", 0.5) * 2])
    if o.get("kind") in ("cyl", "lathe", "sphere"):
        s = [max(o.get("r", .5), o.get("rBot", .5), o.get("rTop", .5)) * 2, o.get("h", (o.get("r", .5) * 2)), 0]
        s[2] = s[0]
    return (p[0] - s[0] / 2, p[1] - s[1] / 2, p[2] - s[2] / 2,
            p[0] + s[0] / 2, p[1] + s[1] / 2, p[2] + s[2] / 2)


def audit(spec):
    """构图体检：把物体投到画面，报告覆盖率/出框/重心。"""
    W, H = 1920, 1080
    pos, tgt, c = cam_at(spec, 0.0)
    fov = math.radians(c["fov"])
    # 相机基
    fwd = [tgt[i] - pos[i] for i in range(3)]
    n = math.sqrt(sum(v * v for v in fwd)); fwd = [v / n for v in fwd]
    up0 = [0, 1, 0]
    right = [fwd[1] * up0[2] - fwd[2] * up0[1], fwd[2] * up0[0] - fwd[0] * up0[2], fwd[0] * up0[1] - fwd[1] * up0[0]]
    rn = math.sqrt(sum(v * v for v in right)) or 1; right = [v / rn for v in right]
    up = [right[1] * fwd[2] - right[2] * fwd[1], right[2] * fwd[0] - right[0] * fwd[2], right[0] * fwd[1] - right[1] * fwd[0]]
    tanv = math.tan(fov / 2); tanh = tanv * W / H

    def project(p):
        d = [p[i] - pos[i] for i in range(3)]
        z = sum(d[i] * fwd[i] for i in range(3))
        if z <= 0.05:
            return None
        x = sum(d[i] * right[i] for i in range(3)) / (z * tanh)
        y = sum(d[i] * up[i] for i in range(3)) / (z * tanv)
        return ((x + 1) / 2, (1 - y) / 2, z)   # 0..1 画面坐标

    objs = spec.get("objects", [])
    rows, clipped, total_cov = [], 0, 0.0
    big = None
    for o in objs:
        b = bbox_of(o)
        if not b:
            continue
        corners = [(b[i], b[j], b[k]) for i in (0, 3) for j in (1, 4) for k in (2, 5)]
        pts = [project(p) for p in corners]
        pts = [p for p in pts if p]
        if not pts:
            continue
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        cov = max(0, min(1, max(xs)) - max(0, min(xs))) * max(0, min(1, max(ys)) - max(0, min(ys)))
        out = max(xs) < 0 or min(xs) > 1 or max(ys) < 0 or min(ys) > 1
        if not out and (max(xs) > 1.02 or min(xs) < -0.02 or max(ys) > 1.02 or min(ys) < -0.02):
            clipped += 1
        total_cov += cov
        name = o.get("name") or o.get("kind")
        rows.append((name, cov, out, (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))
        if big is None or cov > big[1]:
            big = (name, cov)
    rows.sort(key=lambda r: -r[1])
    cov = min(1.0, total_cov)
    out_rows = [r for r in rows if r[2]]
    print(f"[audit] 机位 {c['mode']} az={c['az']} el={c['el']} dist={c['dist']} fov={c['fov']} "
          f"→ 相机 ({pos[0]:.1f},{pos[1]:.1f},{pos[2]:.1f})")
    print(f"[audit] 物体 {len(rows)} 个；画面被占约 {cov*100:.0f}%；出框 {len(out_rows)} 个；压边 {clipped} 个")
    print(f"[audit] 最大主体：{big[0] if big else '无'}  覆盖 {big[1]*100:.0f}%" if big else "[audit] 没有可见物体")
    for name, cc, out, cx, cy in rows[:8]:
        flag = "  ←出框" if out else ("  ←压边" if (cx < 0.03 or cx > 0.97 or cy < 0.03 or cy > 0.97) else "")
        print(f"    {name:22s} cov={cc*100:5.1f}%  center=({cx:.2f},{cy:.2f}){flag}")
    warns = []
    if cov < 0.18:
        warns.append("画面太空（物体总覆盖 <18%）：加近景/放大主体")
    if out_rows:
        warns.append(f"{len(out_rows)} 个物体完全出框：确认是有意为之还是机位算错")
    if cov > 0.95:
        warns.append("物体几乎铺满全画面：可能没有留呼吸空间")
    for w in warns:
        print("[audit] △", w)
    return warns


def inject(scene_path: Path, spec: dict, size=(1920,1080)):
    kit = (ROOT / "kit_space.html").read_text(encoding="utf-8")
    data = json.dumps(spec, ensure_ascii=False).replace("<", r"\u003c")
    marker = "<head>"
    if marker not in kit:
        sys.exit("kit_space.html 缺少 <head> 注入点")
    page = kit.replace(marker, marker + "<script>Object.assign(window,{SPACE_RENDER_SIZE:" + json.dumps(size) + ",SPACE_SPEC:" + data + "})</script>", 1)
    fd, tmp = tempfile.mkstemp(suffix=".html", dir=ROOT)
    os.close(fd)
    Path(tmp).write_text(page, encoding="utf-8")
    return Path(tmp)


def validate(spec):
    errs = []
    if not spec.get("objects"):
        errs.append("场景没有 objects")
    if not Path(ROOT / "kit_space.html").exists():
        errs.append("缺少 kit_space.html")
    g = spec.get("ground", {})
    size = g.get("size", 46)
    cam = spec.get("camera", {})
    dist = cam.get("dist", 15)
    if size < dist * 1.6:
        errs.append(f"地面 size={size} 太小（机位 dist={dist}），会看到地面边缘")
    for i, o in enumerate(spec.get("objects", [])):
        if o.get("kind") == "box" and "size" not in o:
            errs.append(f"objects[{i}] box 缺 size")
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--still", type=float, default=None)
    ap.add_argument("--stills", default="")
    ap.add_argument("--outdir", default="")
    ap.add_argument("--fps", type=int, default=0)
    ap.add_argument("--frames", type=int, default=0)
    ap.add_argument("--preset", default="draft", choices=["draft", "hd", "qhd", "uhd"])
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--gpu", default="auto")
    ap.add_argument("--size", default=None)
    a = ap.parse_args()

    scene_path = Path(a.scene)
    spec = json.loads(scene_path.read_text(encoding="utf-8-sig"))
    errs = validate(spec)
    if errs:
        for e in errs:
            print("[space] ✗", e)
        sys.exit(1)
    if a.audit or (not a.out and a.still is None and not a.stills):
        audit(spec)
        if not a.out and a.still is None and not a.stills:
            return
    sizes = {"draft":"1280x720","hd":"1920x1080","qhd":"2560x1440","uhd":"3840x2160"}
    a.size = a.size or sizes[a.preset]
    try:
        width, height = map(int, a.size.lower().split("x"))
        if min(width,height)<2 or width%2 or height%2: raise ValueError
    except ValueError:
        ap.error("--size requires even WIDTHxHEIGHT")
    tmp = inject(scene_path, spec, (width,height))
    try:
        if a.still is not None or a.stills:
            node = os.environ.get("NODE", "node")
            cmd = [node, str(TOOLS / "still.mjs"), str(tmp), "--size", a.size]
            if a.stills:
                cmd += ["--times", a.stills, "--outdir", a.outdir or (scene_path.parent / "stills").as_posix()]
            else:
                cmd += ["--time", str(a.still), "--out", a.out or (scene_path.parent / "still.png").as_posix()]
            rc = subprocess.call(cmd)
            sys.exit(rc)
        fps = a.fps or int(spec.get("fps", 24))
        frames = a.frames or round(float(spec.get("duration", 6)) * fps)
        out = a.out or (scene_path.parent / (scene_path.stem + ".mp4")).as_posix()
        cmd = [os.environ.get("NODE", "node"), str(HERE / "render_html.mjs"), str(tmp),
               "--out", out, "--frames", str(frames), "--fps", str(fps),
               "--preset", a.preset, "--viewport", a.size, "--dpr", "1", "--gpu", a.gpu]
        rc = subprocess.call(cmd)
        sys.exit(rc)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()
