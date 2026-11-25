#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""props.py —— 参数化道具库（纯数据，不依赖渲染器）。

设计原则（来自第一轮“空间与材质”的实测）：
  1. 轮廓与厚度先于细节：每根杆都有直径，每块板都有厚度，不做零厚度面。
  2. 接触关系写在坐标里：落地物的 y 由“自身高度/2”推出来，不手填。
  3. 连接处加节点：栏杆立柱与横杆相接处加套管，招牌与墙之间加支架。
  4. 材质按物理分家：玻璃(低粗糙+透)、金属(高金属度)、漆面(中粗糙)、水泥(高粗糙)。

每个函数都返回一个 object dict（kit_space.html 的场景图节点），可嵌套 group。
单位：米。y 向上。默认正面朝 +z。
"""
from __future__ import annotations
import math

# ---------- 基础 ----------

def box(name, size, pos, mat=None, rot=(0, 0, 0), **kw):
    o = {"kind": "box", "name": name, "size": list(size), "pos": list(pos),
         "rot": list(rot), "mat": mat or {"albedo": "#b9b3a6", "rough": 0.8}}
    o.update(kw)
    return o


def cyl(name, r, h, pos, mat=None, seg=16, rot=(0, 0, 0), **kw):
    o = {"kind": "cyl", "name": name, "r": r, "h": h, "seg": seg,
         "pos": list(pos), "rot": list(rot), "mat": mat or {"albedo": "#8d939c", "metal": 0.5, "rough": 0.5}}
    o.update(kw)
    return o


def group(name, pos=(0, 0, 0), rot=(0, 0, 0), children=None, **kw):
    o = {"kind": "group", "name": name, "pos": list(pos), "rot": list(rot), "children": children or []}
    o.update(kw)
    return o


def instanced(name, base, size, count, area, pos, mat, seed=1, **kw):
    o = {"kind": "instanced", "name": name, "base": base, "size": list(size), "count": int(count),
         "area": list(area), "pos": list(pos), "mat": mat, "seed": seed}
    o.update(kw)
    return o


# ---------- 材质预设 ----------
MAT = {
    "plaster":   {"albedo": "#cfc8bb", "rough": 0.86, "tex": "plaster"},
    "concrete":  {"albedo": "#7c7f85", "rough": 0.9, "tex": "concrete"},
    "brick":     {"albedo": "#7d5a49", "rough": 0.92, "tex": "brick"},
    "asphalt":   {"albedo": "#2a2d33", "rough": 0.95, "tex": "asphalt"},
    "steel":     {"albedo": "#9aa0a8", "rough": 0.38, "metal": 0.85, "tex": "metal"},
    "paint_dark":{"albedo": "#2f343c", "rough": 0.55, "metal": 0.25},
    "paint_red": {"albedo": "#8f3530", "rough": 0.6},
    "paint_blue":{"albedo": "#2f5fa0", "rough": 0.55},
    "wood":      {"albedo": "#6b4c33", "rough": 0.84, "tex": "wood"},
    "tile":      {"albedo": "#b8b2a4", "rough": 0.45, "tex": "tile"},
    "glass_warm":{"albedo": "#ffe7bb", "emissive": "#ffd9a0", "emissiveIntensity": 1.5, "rough": 0.3},
    "glass_cool":{"albedo": "#dcecff", "emissive": "#bcd9ff", "emissiveIntensity": 0.9, "rough": 0.25},
    "lamp":      {"albedo": "#ffe6b8", "emissive": "#ffcf8a", "emissiveIntensity": 3.2},
    "lamp_white":{"albedo": "#f2f7ff", "emissive": "#e8f2ff", "emissiveIntensity": 2.6},
    "leaf":      {"albedo": "#2f4a2c", "rough": 0.9},
    "rubber":    {"albedo": "#17191c", "rough": 0.95},
}


def m(name, **over):
    d = dict(MAT.get(name, MAT["plaster"]))
    d.update(over)
    return d


# ---------- 地面构件 ----------

def curb(x0, x1, z, h=0.16, w=0.34, mat=None):
    """路缘石：一条有厚度的长条，顶面可作为接触面。"""
    cx = (x0 + x1) / 2
    return box("curb", [abs(x1 - x0), h, w], [cx, h / 2, z], mat or m("concrete"))


def sidewalk(x0, x1, z0, z1, h=0.15, mat=None):
    return box("sidewalk", [abs(x1 - x0), h, abs(z1 - z0)],
               [(x0 + x1) / 2, h / 2, (z0 + z1) / 2], mat or m("concrete", rough=0.92))


def storefront(name, w, h, pos, facing=1, frame_mat=None, glass_mat=None, mullions=3, sill=True):
    """店面玻璃：整块玻璃 + 竖梃 + 上沿横梁 + 窗台，避免“贴一张发光图”。"""
    x, y, z = pos
    fm = frame_mat or m("steel", albedo="#b7bcc4")
    gm = glass_mat or m("glass_warm")
    parts = [
        box(name + "_glass", [w - 0.16, h - 0.22, 0.05], [x, y + h / 2, z], gm, shadow=False),
        box(name + "_head", [w, 0.14, 0.16], [x, y + h - 0.07, z + 0.05 * facing], fm),
        box(name + "_tleft", [0.12, h, 0.16], [x - w / 2 + 0.06, y + h / 2, z + 0.05 * facing], fm),
        box(name + "_tright", [0.12, h, 0.16], [x + w / 2 - 0.06, y + h / 2, z + 0.05 * facing], fm),
    ]
    for i in range(1, mullions + 1):
        px = x - w / 2 + w * i / (mullions + 1)
        parts.append(box(f"{name}_mullion{i}", [0.06, h - 0.1, 0.10],
                         [px, y + h / 2, z + 0.045 * facing], fm))
    if sill:
        parts.append(box(name + "_sill", [w + 0.12, 0.12, 0.26], [x, y + 0.06, z + 0.10 * facing], fm))
    return group(name, children=parts)


def awning(name, w, depth, pos, mat=None, stripe=False, drop=0.42):
    """雨棚：斜面 + 前沿挡板 + 两侧封边，提供明确的“遮挡边界”。"""
    x, y, z = pos
    mt = mat or (m("paint_red") if stripe else m("paint_dark"))
    parts = [
        box(name + "_panel", [w, 0.07, depth], [x, y, z + depth / 2], mt, rot=(math.degrees(math.atan2(drop, depth)), 0, 0)),
        box(name + "_fascia", [w, 0.16, 0.06], [x, y - drop + 0.02, z + depth], mt),
    ]
    for sx in (-1, 1):
        parts.append(box(name + f"_rib{sx}", [0.05, 0.12, depth],
                         [x + sx * (w / 2 - 0.04), y - drop / 2, z + depth / 2], m("steel"),
                         rot=(math.degrees(math.atan2(drop, depth)), 0, 0)))
    return group(name, children=parts)


def signboard(name, w, h, pos, text="", bg="#2f5fa0", fg="#f2f6ff", fontSize=64, glow=0.6, depth=0.10):
    """招牌：发光面板 + 背板 + 两条支架。"""
    x, y, z = pos
    parts = [
        box(name + "_back", [w + 0.08, h + 0.08, depth], [x, y, z], m("paint_dark")),
        box(name + "_face", [w, h, 0.03], [x, y, z + depth / 2 + 0.02],
            m("paint_dark", tex="sign", text=text, bg=bg, fg=fg, fontSize=fontSize,
              emissive=bg, emissiveIntensity=glow, rough=0.5), shadow=False),
    ]
    for sx in (-1, 1):
        parts.append(box(name + f"_brk{sx}", [0.05, 0.05, 0.22],
                         [x + sx * w * 0.42, y + h / 2 - 0.05, z - 0.12], m("steel")))
    return group(name, children=parts)


# ---------- 街道构件 ----------

def railing(name, x0, x1, z, y=0.0, h=1.05, posts=7, mat=None):
    """护栏：立柱 + 双横杆 + 立柱套管，接地点明确（接触阴影的锚）。"""
    mt = mat or m("steel", albedo="#8b939e", rough=0.45)
    parts = []
    for i in range(posts):
        px = x0 + (x1 - x0) * i / (posts - 1)
        parts.append(cyl(f"{name}_post{i}", 0.035, h, [px, y + h / 2, z], mt, seg=10))
        parts.append(cyl(f"{name}_foot{i}", 0.055, 0.07, [px, y + 0.035, z], m("paint_dark"), seg=10))
    parts.append(cyl(name + "_rail_top", 0.028, abs(x1 - x0), [(x0 + x1) / 2, y + h - 0.05, z], mt, seg=10,
                     rot=(0, 0, 90)))
    parts.append(cyl(name + "_rail_mid", 0.020, abs(x1 - x0), [(x0 + x1) / 2, y + h * 0.55, z], mt, seg=10,
                     rot=(0, 0, 90)))
    return group(name, children=parts)


def street_lamp(name, pos, h=4.6, arm=0.55, color="#ffd9a0", intensity=26, spread=15):
    """路灯：杆 + 弯臂 + 灯头（发光）+ 光锥用聚光灯模拟。"""
    x, z = pos[0], (pos[2] if len(pos) > 2 else pos[1])
    parts = [
        cyl(name + "_pole", 0.06, h, [x, h / 2, z], m("paint_dark", albedo="#3b4048"), seg=12),
        cyl(name + "_base", 0.13, 0.22, [x, 0.11, z], m("concrete"), seg=12),
        cyl(name + "_arm", 0.045, arm, [x + arm / 2, h - 0.06, z], m("paint_dark"), seg=10, rot=(0, 0, 90)),
        box(name + "_head", [0.42, 0.14, 0.22], [x + arm, h - 0.12, z], m("lamp")),
        box(name + "_hood", [0.48, 0.06, 0.26], [x + arm, h - 0.03, z], m("paint_dark")),
    ]
    return group(name, children=parts), {"kind": "spot", "pos": [x + arm, h - 0.16, z],
                                        "target": [x + arm, 0, z], "color": color,
                                        "intensity": intensity, "angle": spread, "penumbra": 0.75,
                                        "dist": h * 2.4, "shadow": False}


def utility_pole(name, pos, h=7.0, wires=3):
    x, z = pos[0], (pos[2] if len(pos) > 2 else pos[1])
    parts = [cyl(name + "_pole", 0.10, h, [x, h / 2, z], m("concrete", albedo="#6f7176"), seg=12)]
    for i in range(2):
        parts.append(cyl(name + f"_cross{i}", 0.035, 1.5, [x, h - 0.5 - i * 0.55, z], m("wood"),
                         seg=8, rot=(90, 0, 0)))
    return group(name, children=parts)


def hedge(name, x0, x1, z, count=16, h=0.62, mat=None):
    """绿篱：一排压扁的球，避免方块感；用 instanced 控制实例数。"""
    mt = mat or m("leaf")
    return instanced(name, "sphere", [0.62, h, 0.62], count, [abs(x1 - x0), 0.25],
                     [(x0 + x1) / 2, h * 0.52, z], mt, seed=3, r=0.34, sJitter=0.25, rotY=0.9)


def vending(name, pos, rot=0, w=1.05, h=1.85, d=0.72, glow="#ffe9b0"):
    """自动贩卖机：机身 + 发光橱窗 + 出货口 + 顶灯条。近距离能看出厚度。"""
    x, y, z = pos
    return group(name, pos=(x, y, z), rot=(0, rot, 0), children=[
        box(name + "_body", [w, h, d], [0, h / 2, 0], m("paint_dark", albedo="#c9c3b4", rough=0.5)),
        box(name + "_win", [w - 0.16, h * 0.52, 0.04], [0, h * 0.66, d / 2 + 0.01],
            m("glass_warm", emissive=glow, emissiveIntensity=2.0), shadow=False),
        box(name + "_strip", [w - 0.05, 0.07, 0.05], [0, h - 0.06, d / 2 + 0.02], m("lamp_white"), shadow=False),
        box(name + "_slot", [w * 0.55, 0.16, 0.03], [0, h * 0.24, d / 2 + 0.005], m("rubber")),
        box(name + "_base", [w + 0.04, 0.08, d + 0.02], [0, 0.04, 0], m("paint_dark")),
    ])


def crate_stack(name, pos, n=3, rot=0):
    x, y, z = pos
    ch = []
    r = 0.0
    for i in range(n):
        s = 0.52 + (i % 2) * 0.04
        ch.append(box(f"{name}_{i}", [s, s * 0.78, s], [0, y + s * 0.39 + i * s * 0.78, 0],
                      m("wood", albedo=["#7a6448", "#6d5940", "#836b4c"][i % 3]), rot=(0, (i * 13) % 30 - 15, 0)))
    return group(name, pos=(x, 0, z), rot=(0, rot, 0), children=ch)


def bench(name, pos, rot=0, w=1.9):
    x, z = pos[0], (pos[2] if len(pos) > 2 else pos[1])
    return group(name, pos=(x, 0, z), rot=(0, rot, 0), children=[
        box(name + "_seat", [w, 0.08, 0.5], [0, 0.46, 0], m("wood")),
        box(name + "_back", [w, 0.5, 0.06], [0, 0.72, -0.22], m("wood"), rot=(-8, 0, 0)),
        box(name + "_legL", [0.07, 0.46, 0.45], [-w / 2 + 0.14, 0.23, 0], m("paint_dark")),
        box(name + "_legR", [0.07, 0.46, 0.45], [w / 2 - 0.14, 0.23, 0], m("paint_dark")),
    ])


def car(name, pos, rot=0, color="#3a4a63", brake=False):
    """轿车：车身 + 车顶 + 四轮 + 前后灯（有厚度，能落地）。"""
    x, z = pos[0], (pos[2] if len(pos) > 2 else pos[1])
    body, cabin = m("paint_dark", albedo=color, rough=0.35, metal=0.35), m("paint_dark", albedo=color, rough=0.3, metal=0.4)
    ch = [
        box(name + "_body", [1.86, 0.62, 4.3], [0, 0.58, 0], body),
        box(name + "_cabin", [1.62, 0.52, 2.0], [0, 1.12, -0.12], cabin),
        box(name + "_wind", [1.5, 0.34, 0.06], [0, 1.16, 0.92], m("glass_cool", emissiveIntensity=0.25), shadow=False),
        box(name + "_lampL", [0.34, 0.16, 0.08], [-0.66, 0.66, 2.14], m("lamp_white")),
        box(name + "_lampR", [0.34, 0.16, 0.08], [0.66, 0.66, 2.14], m("lamp_white")),
        box(name + "_plate", [0.5, 0.14, 0.04], [0, 0.44, 2.16], m("plaster", albedo="#d8d8d0")),
    ]
    if brake:
        ch.append(box(name + "_brakeL", [0.3, 0.14, 0.06], [-0.66, 0.7, -2.14],
                      m("paint_red", emissive="#ff4a3a", emissiveIntensity=1.6), shadow=False))
        ch.append(box(name + "_brakeR", [0.3, 0.14, 0.06], [0.66, 0.7, -2.14],
                      m("paint_red", emissive="#ff4a3a", emissiveIntensity=1.6), shadow=False))
    for i, (sx, sz) in enumerate([(-0.86, 1.42), (0.86, 1.42), (-0.86, -1.42), (0.86, -1.42)]):
        ch.append(cyl(f"{name}_wheel{i}", 0.33, 0.22, [sx, 0.33, sz], m("rubber"), seg=16, rot=(0, 0, 90)))
        ch.append(cyl(f"{name}_hub{i}", 0.17, 0.24, [sx, 0.33, sz], m("steel"), seg=12, rot=(0, 0, 90)))
    return group(name, pos=(x, 0, z), rot=(0, rot, 0), children=ch)


def bicycle(name, pos, rot=0, frame="#2e3a4a"):
    """自行车：两个轮 + 三角架 + 车把 + 车座，是前景遮挡的好素材。"""
    x, z = pos[0], (pos[2] if len(pos) > 2 else pos[1])
    ch = []
    for i, dz in enumerate([0.52, -0.52]):
        ch.append({"kind": "torus", "name": f"{name}_wheel{i}", "r": 0.33, "tube": 0.022,
                   "seg": 28, "pos": [0, 0.33, dz], "rot": [0, 90, 0], "mat": m("rubber")})
    ch += [
        box(name + "_top", [0.04, 0.04, 0.72], [0, 0.72, 0], m("paint_dark", albedo=frame), rot=(0, 0, 0)),
        box(name + "_down", [0.04, 0.04, 0.70], [0, 0.52, 0.10], m("paint_dark", albedo=frame), rot=(32, 0, 0)),
        box(name + "_seatpost", [0.035, 0.24, 0.035], [0, 0.82, -0.20], m("steel")),
        box(name + "_seat", [0.10, 0.05, 0.24], [0, 0.95, -0.22], m("rubber")),
        box(name + "_bar", [0.46, 0.035, 0.035], [0, 0.96, 0.50], m("steel")),
        box(name + "_fork", [0.035, 0.60, 0.035], [0, 0.56, 0.50], m("steel"), rot=(12, 0, 0)),
    ]
    return group(name, pos=(x, 0, z), rot=(0, rot, 0), children=ch)


def planter(name, pos, w=0.9, h=0.55, bush=True):
    x, z = pos[0], (pos[2] if len(pos) > 2 else pos[1])
    ch = [box(name + "_pot", [w, h, w], [0, h / 2, 0], m("concrete", albedo="#8a8680")),
          box(name + "_rim", [w + 0.06, 0.06, w + 0.06], [0, h - 0.02, 0], m("concrete", albedo="#9a968f"))]
    if bush:
        ch.append({"kind": "sphere", "name": name + "_bush", "r": w * 0.42, "seg": 16,
                   "pos": [0, h + w * 0.22, 0], "mat": m("leaf", albedo="#33502f")})
    return group(name, pos=(x, 0, z), children=ch)


def window_row(name, x0, x1, y0, y1, z, n=4, facing=1, lit=0.5, seed=1):
    """楼上住户窗：亮/暗交替 + 窗框 + 窗台，让窗“嵌”在墙上而不是贴上去。"""
    ch = []
    r = (seed * 2654435761) % 1000
    for i in range(n):
        w = (x1 - x0) / n * 0.62
        cx = x0 + (x1 - x0) * (i + 0.5) / n
        on = ((r + i * 37) % 100) / 100.0 < lit
        mat = (m("glass_warm", albedo="#e8d8b4", emissive="#ffca7a", emissiveIntensity=0.55)
               if on else m("paint_dark", albedo="#1b2434", rough=0.25, metal=0.15))
        cy = (y0 + y1) / 2
        hh = (y1 - y0)
        ch.append(box(f"{name}_glass{i}", [w, hh * 0.70, 0.03], [cx, cy, z], mat, shadow=False))
        fm = m("paint_dark", albedo="#6f6a62", rough=0.7)
        ch.append(box(f"{name}_ftop{i}", [w + 0.12, 0.055, 0.09], [cx, cy + hh * 0.36, z - 0.01 * facing], fm))
        ch.append(box(f"{name}_fbot{i}", [w + 0.12, 0.055, 0.09], [cx, cy - hh * 0.36, z - 0.01 * facing], fm))
        ch.append(box(f"{name}_fl{i}", [0.055, hh * 0.72, 0.09], [cx - w / 2, cy, z - 0.01 * facing], fm))
        ch.append(box(f"{name}_fr{i}", [0.055, hh * 0.72, 0.09], [cx + w / 2, cy, z - 0.01 * facing], fm))
        ch.append(box(f"{name}_sill{i}", [w + 0.20, 0.06, 0.16], [cx, cy - hh * 0.40, z + 0.05 * facing],
                      m("concrete", albedo="#8d887e")))
    return group(name, children=ch)


def roof_parapet(name, w, d, pos, h=0.35, mat=None):
    x, y, z = pos
    mt = mat or m("concrete", albedo="#8f8b83")
    return group(name, children=[
        box(name + "_front", [w, h, 0.12], [x, y + h / 2, z + d / 2 - 0.06], mt),
        box(name + "_back", [w, h, 0.12], [x, y + h / 2, z - d / 2 + 0.06], mt),
        box(name + "_left", [0.12, h, d], [x - w / 2 + 0.06, y + h / 2, z], mt),
        box(name + "_right", [0.12, h, d], [x + w / 2 - 0.06, y + h / 2, z], mt),
    ])


def rooftop_units(name, pos, seed=5):
    """屋顶设备：水箱 + 空调外机 + 管道，打破天际线单调。"""
    x, y, z = pos
    ch = [
        cyl(name + "_tank", 0.42, 0.75, [x - 0.6, y + 0.38, z], m("concrete", albedo="#9aa0a4"), seg=14),
        box(name + "_ac1", [0.7, 0.5, 0.4], [x + 0.55, y + 0.25, z], m("paint_dark", albedo="#b0b4b8")),
        box(name + "_ac2", [0.55, 0.4, 0.36], [x + 0.55, y + 0.7, z + 0.05], m("paint_dark", albedo="#a4a8ac")),
        cyl(name + "_pipe", 0.05, 1.4, [x, y + 0.7, z - 0.5], m("steel"), seg=8, rot=(90, 0, 0)),
    ]
    return group(name, children=ch)


def far_block(name, x0, x1, z, y=0, h=9, mat=None, seed=9):
    """远景楼：不做细节，只给剪影和几排窗，靠雾拉开距离。"""
    mt = mat or m("concrete", albedo="#464c58", rough=0.95)
    w = abs(x1 - x0)
    cx = (x0 + x1) / 2
    ch = [box(name + "_mass", [w, h, 6], [cx, y + h / 2, z], mt),
          window_row(name, x0 + 0.4, x1 - 0.4, y + h * 0.35, y + h * 0.9, z + 3.02, n=max(3, int(w / 2.2)),
                     lit=0.35, seed=seed)]
    return group(name, children=ch)

