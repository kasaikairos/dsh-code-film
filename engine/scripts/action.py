#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""action.py —— 把“谁在动、相对谁、发生哪个事件、镜头关注谁”解算成可渲染的时间线。

设计原则（第二轮）：
  1. 事件时间由几何算出来，不由人填死。挡条挪远，接触帧自己变；镜头切点跟着事件走。
  2. 位移与自转绑定：滚动角 = 位移 / 半径。不是两套独立动画。
  3. 停稳要停在接触位置：中心 = 挡条面 - 半径 - 间隙。不留穿透、不悬空。
  4. 事件表同时喂给三处：物体运动、机位切换、配乐重音。共用同一个时间。

用法（在场景脚本里）：

    from action import Scene
    S = Scene(spec)
    S.roll("tomato", t0=1.8, speed=0.14, stop_at="bar")      # 从当前坐标沿 +x 滚，停到挡条
    S.bump("lemon", target="tomato", t0=1.0, dur=0.75)        # 柠檬滚进来撞上番茄
    S.camera_hold(key={...})
    S.camera_cut(at="contact", key={...})
    S.finish()          # 写回 spec：objects[].motion / camera.keys / events / music.cues
"""
from __future__ import annotations
import math, copy

UP = (0.0, 1.0, 0.0)


def _find(spec, name, node=None):
    node = node or spec
    for o in node.get("objects", []):
        if o.get("name") == name:
            return o
        if o.get("children"):
            hit = _find({"objects": o["children"]}, name)
            if hit:
                return hit
    return None


def _world_pos(o, parent=(0, 0, 0)):
    """只支持一层 group 的平移叠加（够用，且避免引入完整场景图求值）。"""
    p = o.get("pos", [0, 0, 0])
    return [p[0] + parent[0], p[1] + parent[1], p[2] + parent[2]]


def _find_with_parent(spec, name):
    for o in spec.get("objects", []):
        if o.get("name") == name:
            return o, [0, 0, 0]
        for c in o.get("children", []):
            if c.get("name") == name:
                return c, o.get("pos", [0, 0, 0])
    return None, None


def _radius(o):
    if o.get("r") is not None:
        return float(o["r"])
    if o.get("kind") == "group" or o.get("children"):
        rs = [_radius(c) for c in o.get("children", [])]
        return max(rs) if rs else 0.5
    s = o.get("size", [1, 1, 1])
    return min(s) / 2.0


class Scene:
    def __init__(self, spec, fps=24):
        self.spec = spec
        self.fps = int(spec.get("fps", fps))
        self.events = {}          # name -> t
        self.event_order = []
        self.motions = {}         # name -> motion dict
        self.cam_keys = []
        self.cues = []
        self.notes = []

    # ---------- 事件 ----------
    def event(self, name, t, note=""):
        if name in self.events:
            raise ValueError(f"事件重名：{name}")
        self.events[name] = round(float(t), 4)
        self.event_order.append((self.events[name], name, note))
        return self.events[name]

    def t(self, name):
        if name not in self.events:
            raise KeyError(f"没有事件 {name}（现有：{list(self.events)}）")
        return self.events[name]

    # ---------- 物体运动 ----------
    def roll(self, name, t0, speed, stop_at=None, direction=(1, 0, 0), gap=0.0,
             radius=None, start=None, allow_overrun=0.0, distance=None):
        """滚动：从 start（默认用物体当前坐标）沿 direction 走，撞到 stop_at 那个物体的面为止。

        返回 dict：{t0, t1, distance, angle, stop_center, contact_face}
        """
        o, parent = _find_with_parent(self.spec, name)
        if o is None:
            raise KeyError(f"场景里没有物体 {name}")
        r = float(radius if radius is not None else _radius(o))
        p0 = list(start) if start else _world_pos(o, parent)
        d = _norm(direction)
        dist = None
        contact_face = None
        if stop_at:
            bar, bar_parent = _find_with_parent(self.spec, stop_at)
            if bar is None:
                raise KeyError(f"没有挡条物体 {stop_at}")
            bp = _world_pos(bar, bar_parent)
            bsz = bar.get("size", [1, 1, 1])
            if abs(d[0]) > 0.5:      # 沿 x 滚：用挡条靠近来向的那一面
                side = -1 if d[0] > 0 else 1
                contact_face = bp[0] + side * bsz[0] / 2.0
                stop_center = contact_face + side * (r + gap)
                dist = abs(stop_center - p0[0])
            elif abs(d[2]) > 0.5:
                side = -1 if d[2] > 0 else 1
                contact_face = bp[2] + side * bsz[2] / 2.0
                stop_center = contact_face + side * (r + gap)
                dist = abs(stop_center - p0[2])
            else:
                raise ValueError("挡条只在水平方向上有意义")
        else:
            dist = float(distance) if distance is not None else (float(allow_overrun) if allow_overrun else 0.0)
        dur = dist / speed
        t1 = t0 + dur
        stop_center = [p0[0] + d[0] * dist, p0[1], p0[2] + d[2] * dist]
        angle = dist / r
        mot = {"kind": "roll", "from": p0, "to": stop_center, "t0": round(t0, 4),
               "t1": round(t1, 4), "axis": list(_cross(UP, d)), "radius": r,
               "angle": round(angle, 5), "speed": speed, "ease": "linear"}
        self.motions[name] = mot
        self.event("roll_start_" + name, t0)
        self.event("contact_" + name, t1, f"撞上 {stop_at}" if stop_at else "到达终点")
        return {"t0": t0, "t1": t1, "distance": dist, "angle": angle,
                "stop_center": stop_center, "contact_face": contact_face}

    def slide(self, name, t0, dur, to=None, by=None, ease="inout", radius=None, tag=None):
        """平移（不做自转）。tag 用于同一物体分段运动：事件名会带上后缀，避免重名。"""
        o, parent = _find_with_parent(self.spec, name)
        if o is None:
            raise KeyError(f"场景里没有物体 {name}")
        p0 = _world_pos(o, parent)
        if to is not None:
            p1 = list(to)
        else:
            p1 = [p0[i] + (by[i] if by else 0.0) for i in range(3)]
        mot = {"kind": "slide", "from": p0, "to": p1, "t0": round(t0, 4),
               "t1": round(t0 + dur, 4), "ease": ease}
        suffix = f"_{tag}" if tag else ""
        self._motions_set = getattr(self, "_motions_set", set())
        key = name + suffix
        if key in self.motions:
            raise ValueError(f"同一物体同一 tag 只能有一段运动：{key}")
        self.motions[name] = mot
        self.event("move_start_" + name + suffix, t0)
        self.event("move_end_" + name + suffix, t0 + dur)
        return mot



    def path(self, name, segs):
        """多段直线运动：对正 → 穿过开口 → 停住。segs=[{t0,t1,from,to,ease}]。
        渲染端按段求值，事件名由调用方用 S.event() 显式声明（几何算出）。"""
        o, _ = _find_with_parent(self.spec, name)
        if o is None:
            raise KeyError(f"场景里没有物体 {name}")
        mot = {"kind": "path", "segs": segs, "from": segs[0]["from"],
               "to": segs[-1]["to"], "t0": segs[0]["t0"], "t1": segs[-1]["t1"],
               "radius": _radius(o), "ease": "linear"}
        self.motions[name] = mot
        return mot

    def touch(self, name, target, t0, dur=0.6, gap=0.0):
        """物体 A 滚到刚好贴住 B（用来做“被碰了一下”的来因）。"""
        a, ap = _find_with_parent(self.spec, name)
        b, bp = _find_with_parent(self.spec, target)
        if a is None or b is None:
            raise KeyError("touch 需要两个都在场景里的物体")
        ra, rb = _radius(a), _radius(b)
        pa, pb = _world_pos(a, ap), _world_pos(b, bp)
        d = _norm((pb[0] - pa[0], 0.0, pb[2] - pa[2]))
        target_dist = math.hypot(pb[0] - pa[0], pb[2] - pa[2]) - (ra + rb + gap)
        speed = target_dist / dur
        res = self.roll(name, t0=t0, speed=speed, direction=d, gap=gap, distance=target_dist)
        self.event("bump", self.events["contact_" + name], f"{name} 碰到 {target}")
        return res

    # ---------- 镜头 ----------
    def camera_hold(self, key):
        k = dict(key)
        # key.target_ref = {"name":"paper_stack","local":[x,y,z]} → 镜头对到物体上的局部点
        k.setdefault("t", 0.0)
        k["cut"] = bool(k.get("cut", False))
        self.cam_keys.append(k)
        return k

    def camera_cut(self, at, key, lead=0.0):
        """在事件发生的同一帧切机位（lead>0 表示提前一点，默认同帧）。"""
        t = self.t(at) + lead
        k = dict(key)
        k["t"] = round(t, 4)
        k["cut"] = True
        self.cam_keys.append(k)
        return k

    def camera_move(self, at, key, dur):
        t = self.t(at)
        k = dict(key)
        k["t"] = round(t + dur, 4)
        k["cut"] = False
        self.cam_keys.append(k)
        return k

    # ---------- 写回 ----------
    def finish(self, cue_kinds=None):
        cue_kinds = cue_kinds or {}
        for name, m in self.motions.items():
            o, _ = _find_with_parent(self.spec, name)
            if o is None:
                raise KeyError(name)
            o["motion"] = m
            o["contact"] = False          # 运动物体的接触阴影改成实时投影，不再烘焙
        if self.cam_keys:
            self.cam_keys.sort(key=lambda k: k["t"])
            base = copy.deepcopy(self.spec.get("camera", {}))
            self.spec["camera"] = {**base, "keys": self.cam_keys, "mode": "keys"}
        self.spec["events"] = {n: self.events[n] for _, n, _ in sorted(self.event_order)}
        for name, kind in cue_kinds.items():
            if name in self.events:
                self.cues.append({"time": self.events[name], "kind": kind})
        if self.cues:
            music = dict(self.spec.get("music", {}))
            music["cues"] = sorted(self.cues, key=lambda c: c["time"])
            self.spec["music"] = music
        return self.spec

    def summary(self):
        rows = []
        for t, n, note in sorted(self.event_order):
            rows.append(f"  {t:6.2f}s  {n:22s} {note}")
        return "\n".join(rows)


def _norm(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return (v[0] / n, v[1] / n, v[2] / n)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
