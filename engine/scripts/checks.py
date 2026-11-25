#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""checks.py —— 一条命令跑完"交付前必须过的检查"（对齐参考工程的 12 项审计里的可测部分）。

跑什么：
  1) 规格：分辨率/帧率/帧数是否符合要求（不符直接失败）
  2) 精细度：sharp / edge_width / alias / grain / banding（precision_probe）
  3) 运动：相机速度、世界速度、纵深、停顿比（motion_probe）
  4) 卡点：切点是否落在音频击点 ±120ms（beat_sync，需要音频）
  5) 音频：spectral centroid / >4k 占比 / ding 密度（audio_check）

    python scripts/checks.py --video out/f.mp4 --expect 3840x2160 --fps 30 --audio out/score.wav
    python scripts/checks.py --video out/f.mp4 --strict        # 任一项不过则非零退出
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable



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

def run_json(args):
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        out = r.stdout
        return json.loads(out[out.index("{"):out.rindex("}") + 1])
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--expect", default="", help="如 3840x2160；给了就硬校验")
    ap.add_argument("--fps", type=float, default=0)
    ap.add_argument("--audio", default="", help="成片音轨或独立配乐")
    ap.add_argument("--require-all", action="store_true", help="有未测项就不算通过")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    video = a.video
    fails, notes = [], []
    tested = {}

    # 1) 规格
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height,r_frame_rate,nb_frames",
                        "-of", "json", video], capture_output=True, text=True)
    try:
        st = json.loads(p.stdout)["streams"][0]
        w, h = st["width"], st["height"]
        num, _, den = st["r_frame_rate"].partition("/")
        fps = float(num) / max(float(den or 1), 1e-6)
        notes.append(f"规格 {w}×{h} @ {fps:.2f}fps · {st.get('nb_frames')} 帧")
        if a.expect:
            ew, eh = [int(x) for x in a.expect.lower().split("x")]
            if (w, h) != (ew, eh):
                fails.append(f"分辨率不符：{w}×{h}，要求 {ew}×{eh}")
        if a.fps and abs(fps - a.fps) > 0.01:
            fails.append(f"帧率不符：{fps:.2f}，要求 {a.fps}")
    except Exception as e:
        fails.append(f"ffprobe 解析失败：{e}")

    # 2) 精细度：分别测全画面与"去掉底部字幕带"的画面（旧版只测全画面，字幕会抬锐度）
    measured = run_json([PY, os.path.join(HERE, "precision_probe.py"), "--video", video,
                         "--frames", "20", "--pair"]) or {}
    pr = measured.get("full")
    pr_nt = measured.get("masked")
    tested["精细度"] = bool(pr and "sharp" in pr)
    tested["画面锐度（去字幕）"] = bool(pr_nt and "sharp" in pr_nt)
    if not pr or "sharp" not in pr:
        fails.append("无法测精细度（precision_probe 没输出）：装 opencv-python 或 numpy/Pillow")
    if pr:
        notes.append(f"精细度（全画面）sharp {pr['sharp']} · alias {pr['alias']} · "
                     f"grain {pr['grain']} · 色阶 {pr['banding']}")
        if pr["alias"] > 0.20:
            fails.append(f"alias {pr['alias']} > 0.20（锯齿/噪点，加超采样）")
        if pr["grain"] > 0.004:
            fails.append(f"grain {pr['grain']} > 0.004（颗粒过量）")
    if pr_nt:
        st = pr_nt.get("sharp") or 0
        notes.append(f"精细度（去底部 22%）sharp {st} · alias {pr_nt['alias']}")
        if pr and pr.get("sharp") and st and pr["sharp"] / max(st, 1e-6) > 1.6:
            fails.append(f"锐度主要来自字幕/文字（全画面 {pr['sharp']} vs 去字幕 {st}）："
                         "画面本身不够锐，这个分数不能当清晰度")
        elif st < 2.6:
            fails.append(f"画面本身偏软（去字幕 sharp {st} < 2.6）：加超采样或补细节")
        if pr_nt.get("banding") is not None and pr_nt["banding"] < 0.10:
            notes.append(f"（色阶偏少 {pr_nt['banding']:.3f}，可能出现色带）")

    # 3) 运动（motion_probe 已移出：改用 frame_scan 的 motion 分位）
    mo = None
    try:
        import frame_scan as _FS
        _, _arr = _FS.scan_one((a.video, min(a.fps or 8, 8), 320), motion_only=True)
        if _arr is not None and len(_arr):
            import numpy as _np
            mi = 0
            mv = _arr[:, mi]
            mo = {"world_speed": float(_np.percentile(mv, 95)),
                  "still_ratio": float((mv < _np.percentile(mv, 20)).mean()),
                  "cam_speed": 0.0, "layer_depth": 0.0}
    except Exception:
        mo = None
    tested["运动（世界）"] = bool(mo)
    tested["运动（相机/纵深）"] = False
    if mo:
        notes.append(f"运动 世界 {mo['world_speed']} · 停顿 {mo['still_ratio']} · 相机/纵深：未测")
        if mo["cam_speed"] + mo["world_speed"] < 0.5:
            fails.append("整片几乎不动（相机+世界速度 <0.5），观感会像 PPT")

    if a.audio:
        tested["卡点"] = False

    # 5) 音频
    if a.audio and os.path.exists(a.audio):
        ac = run_json([PY, os.path.join(HERE, "audio_check.py"), "--audio", a.audio])
        if ac:
            m = ac.get("metrics", {})
            notes.append(f"音频 质心 {m.get('centroid_hz')}Hz · >4k {m.get('hi_share')} · "
                         f"ding {m.get('ding_per_min')}/min")
            if ac.get("bad"):
                fails.append("音频体检：" + "；".join(ac["bad"])[:120])

    print(f"\n检查：{os.path.basename(video)}")
    for n in notes:
        print("  ·", n)
    if fails:
        print("\n✗ 不通过：")
        for f in fails:
            print("  -", f)
    else:
        untested = [k for k, v in tested.items() if not v]
        if untested:
            print(f"\n△ 通过，但有 {len(untested)} 项未测：" + "、".join(untested))
            print("  （未测 ≠ 合格。要说“全部通过”，这几项必须有数据）")
            if getattr(a, "require_all", False):
                return 1
        else:
            print("\n✓ 全部通过（各项均已测）")
    if fails and (a.strict or a.require_all):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
