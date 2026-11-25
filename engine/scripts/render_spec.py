#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_spec.py —— 把 scene_spec.py 产出的规格交给 SceneKit 渲染成片。

流程：读 spec.json → 生成临时页面（把 window.SCENE_SPEC 注入 scenekit.html）
      → node render_html.mjs 逐帧截图 → ffmpeg 编码。

    python scripts/render_spec.py --spec out/spec.json --out out/film.mp4 --preset hd --frames 90
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import math
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)



def ensure_node_deps():
    if (Path(ROOT) / "node_modules/puppeteer/package.json").is_file():
        return True
    print("渲染组件不完整，请从完整技能包重新初始化本地 runtime。")
    return False


def scene_page(spec, source_path, width, height):
    tpl = spec.get('template')
    use3d = (tpl == '3d') or (spec.get('post', {}) or {}).get('register3d')
    if tpl in {'eclipse', 'raymarch', 'paint'}:
        sys.exit(f"template={tpl} 已从技能包移出。请用项目自己的绘制代码，通过 timeline 导出。")
    if tpl == 'poster':
        kit = os.path.join(ROOT, 'scene_poster.html')
    elif tpl == 'space':
        # 空间与材质：声明式场景（物体/灯/湿地/相机）由 kit_space.html 解释
        kit = os.path.join(ROOT, 'kit_space.html')
    else:
        kit = os.path.join(ROOT, 'scene3d.html' if use3d else 'scenekit.html')
    if not os.path.exists(kit):
        sys.exit("缺少 scenekit.html")
    html = open(kit, encoding="utf-8").read()
    # 模板各自约定注入的全局名：kit_space 读 SPACE_SPEC，其余读 SCENE_SPEC
    payload = {"SPACE_SPEC" if tpl == "space" else "SCENE_SPEC": spec}
    viewport = "1920x1080"
    if tpl == "space":
        payload["SPACE_RENDER_SIZE"] = [width, height]
        viewport = f"{width}x{height}"
    source = (spec.get("emotion") or {}).get("src")
    if source:
        paths = [Path(source_path).resolve().parent / source, Path(source), Path(ROOT) / source]
        match = next((p for p in paths if p.is_file()), None)
        if not match:
            sys.exit(f"找不到情感曲线 {source}")
        payload["EMOTION"] = json.loads(match.read_text(encoding="utf-8-sig"))
    marker = "<head>"
    if marker not in html:
        sys.exit(f"模板没有 <head> 注入点：{kit}")
    data = json.dumps(payload, ensure_ascii=False).replace("<", r"\u003c")
    page = html.replace(marker, marker + "<script>Object.assign(window," + data + ")</script>", 1)
    return page, viewport


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", type=int, default=0, help="分段渲染起始帧（配合 --end）")
    ap.add_argument("--end", type=int, default=0, help="分段渲染结束帧（不含）")
    ap.add_argument("--quiet", action="store_true", help="只打一行摘要")
    ap.add_argument("--frames", type=int, default=None, help="默认按 spec.duration × fps 渲完整镜头")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--preset", choices=["draft", "hd", "qhd", "uhd"], default="hd")
    ap.add_argument("--audit", action="store_true", help="渲前跑版式审计（出画/安全边距/重叠）")
    ap.add_argument("--dpr", type=float, default=None, help="逻辑画布像素倍率，默认由输出档位决定")
    ap.add_argument("--outres", default="", help="覆盖输出尺寸，例如 1280:720")
    ap.add_argument("--samples", type=int, default=int(os.environ.get("BL_SAMPLES", 96)),
                    help="Blender 采样数（GPU 下 96–256 足够）")
    ap.add_argument("--gpu", default="auto", choices=["auto", "on", "off"])
    ap.add_argument("--blender", action="store_true", help="用 Blender 真 GI 通道渲染")
    ap.add_argument("--story", default="", help="story.json；给了就先过叙事契约，不过不渲")
    ap.add_argument("--force", action="store_true", help="跳过叙事契约（不建议）")
    a = ap.parse_args()

    spec = json.loads(Path(a.spec).read_text(encoding="utf-8-sig"))
    sizes = {"draft": (1280, 720), "hd": (1920, 1080), "qhd": (2560, 1440), "uhd": (3840, 2160)}
    try:
        width, height = map(int, a.outres.split(":")) if a.outres else sizes[a.preset]
    except ValueError:
        ap.error("--outres 需要 宽:高")
    if min(width, height) < 2 or width % 2 or height % 2:
        ap.error("输出宽高应为正偶数")
    frames = a.frames if a.frames is not None else round(float(spec.get("duration", 3)) * a.fps)
    dpr = a.dpr if a.dpr is not None else max(width / 1920, height / 1080)
    if frames < 1 or a.fps < 1 or not math.isfinite(dpr) or dpr <= 0:
        ap.error("帧数、帧率和像素倍率必须为正")
    Path(a.out).resolve().parent.mkdir(parents=True, exist_ok=True)
    if getattr(a, "story", "") and not a.force:
        import story as _story
        _st = json.load(open(a.story, encoding="utf-8"))
        _fails, _warns, _notes = _story.check(_st)
        for _n in _notes:
            print("·", _n)
        for _w in _warns:
            print("△", _w)
        for _f in _fails:
            print("✗", _f)
        if _fails:
            sys.exit(f"\n叙事契约不通过（{len(_fails)} 项）：先改 {a.story}，或用 --force 强行渲")
        print("✓ 叙事契约通过")

    if a.blender:
        cmd = [sys.executable, os.path.join(HERE, "render_blender_spec.py"),
               "--spec", a.spec, "--out", a.out, "--fps", str(a.fps), "--frames", str(frames),
               "--res", f"{width}x{height}", "--samples", str(a.samples), "--gpu", a.gpu]
        sys.exit(subprocess.call(cmd))
    if not ensure_node_deps():
        sys.exit(2)
    tpl = spec.get("template")
    page, viewport = scene_page(spec, a.spec, width, height)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".html", dir=ROOT, delete=False) as f:
        f.write(page)
        tmp = f.name
    try:
        if a.audit:
            subprocess.run(["node", os.path.join(HERE, "layout_audit.mjs"), tmp, "--safe", "0.06"], check=True)
        cmd = ["node", os.path.join(HERE, "render_html.mjs"), tmp, "--out", os.path.abspath(a.out),
               "--frames", str(frames), "--fps", str(a.fps), "--preset", a.preset,
               "--start", str(getattr(a, "start", 0)), "--end", str(getattr(a, "end", 0) or 0), "--viewport", viewport, "--dpr", str(1.0 if tpl == "space" else dpr), "--gpu", a.gpu]
        if a.quiet:
            cmd.append("--quiet")
        # space 模板固定 1:1 像素比（小数 devicePixelRatio 会让 WebGL 截图丢 sRGB），改用 ffmpeg 下采样
        eff_dpr = 1.0 if tpl == "space" else dpr
        if tpl != "space" and (round(1920 * eff_dpr), round(1080 * eff_dpr)) != (width, height):
            cmd += ["--scale", f"{width}:{height}"]
        sys.exit(subprocess.call(cmd))
    finally:
        os.unlink(tmp)


if __name__ == "__main__":
    main()
