#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_blender_spec.py —— 用 Blender 渲染 **与 three.js 同一份 spec**。

设计原则（写进规则）：
  · 一条 spec，两条通道：`scene3d.html`（快、可交互）与 Blender（真 GI、体积、折射）
  · **情感曲线与镜头计划对两条通道同等生效**：Blender 里也按 emotion.intensity 打关键帧，
    按 shot_plan 切机位/内容层；不允许"Blender 只做静态图"
  · 意象骨架一一对应：figure / window / rain / horizon / branches / smoke

用法：
    python scripts/render_blender_spec.py --spec out/spec.json --out out/f.mp4 [--frames N]
        [--engine CYCLES|EEVEE] [--samples 64] [--res 1920x1080] [--still t]

约定：Blender 由 ensure_blender.py 发现（BLENDER 环境变量或系统安装）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def find_blender():
    env = os.environ.get("BLENDER")
    if env and os.path.exists(env):
        return env
    import shutil
    w = shutil.which("blender")
    if w:
        return w
    # 常见安装位置：用环境变量拼，不写死任何盘符
    cands = []
    if sys.platform.startswith("win"):
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if not base:
                continue
            for ver in ("Blender 5.3", "Blender 5.2", "Blender 5.1", "Blender 4.5", "Blender"):
                cands.append(os.path.join(base, "Blender Foundation", ver, "blender.exe"))
    elif sys.platform == "darwin":
        cands.append("/Applications/Blender.app/Contents/MacOS/Blender")
    else:
        cands += ["/usr/bin/blender", "/usr/local/bin/blender", "/snap/bin/blender"]
    for p in cands:
        if os.path.exists(p):
            return p
    return None


# ───────────────────────── Blender 端脚本（在 blender -b -P 里执行）
BL_SCRIPT = r'''
import bpy, bmesh, json, math, os, sys, random
from mathutils import Vector, Euler

argv = sys.argv[sys.argv.index("--") + 1:]
spec_path, out_path = argv[0], argv[1]
engine = argv[2] if len(argv) > 2 else "CYCLES"
gpu_mode = (os.environ.get("RENDER_GPU") or (argv[6] if len(argv) > 6 else "auto")).lower()
samples = int(argv[3]) if len(argv) > 3 else 64
res_x, res_y = (int(x) for x in (argv[4] if len(argv) > 4 else "1920x1080").split("x"))
still = float(argv[5]) if len(argv) > 5 and argv[5] != "-" else None

S = json.load(open(spec_path, encoding="utf-8-sig"))
CP = S.get("compose") or {}
_emo_curves = S.get("emotion_curves") or {}
_emo_I = None
try:
    if _emo_curves.get("intensity"):
        _c = _emo_curves["intensity"]
        _f = float(still) / max(0.1, float(S.get("duration") or 6.0)) if still is not None else 0.6
        _emo_I = _c[max(0, min(len(_c) - 1, int(round(_f * (len(_c) - 1)))))]
except Exception:
    _emo_I = None
S["_emo_intensity"] = float(_emo_I) if _emo_I is not None else 0.75
POST_GAIN = float((S.get("post") or {}).get("gain", 1.0))
DETAIL = float((S.get("render") or {}).get("detail") or S.get("detail") or 0.55)
pal = [tuple(int(h[i:i+2], 16) / 255 for i in (1, 3, 5)) for h in S.get("palette", ["#c9d3d9"])]
def col(i, alpha=1.0):
    r, g, b = pal[i % len(pal)]
    return (r ** 2.2, g ** 2.2, b ** 2.2, alpha)      # sRGB → linear 近似

# 清空
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = "CYCLES" if engine.upper() == "CYCLES" else "BLENDER_EEVEE_NEXT"
if scene.render.engine == "CYCLES":
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.cycles.device = "CPU"
    # GPU：优先 OptiX / CUDA，其次 HIP / Metal / oneAPI；失败回退 CPU
    if gpu_mode != "off":
        try:
            prefs = bpy.context.preferences.addons["cycles"].preferences
            chosen = None
            for dt in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
                try:
                    prefs.compute_device_type = dt
                    prefs.get_devices()
                    devs = [d for d in prefs.devices if d.type == dt]
                    if devs:
                        for d in prefs.devices:
                            d.use = (d.type == dt)
                        chosen = (dt, [d.name for d in devs])
                        break
                except Exception:
                    continue
            if chosen:
                scene.cycles.device = "GPU"
                print(f"CYCLES_GPU {chosen[0]} {chosen[1]}")
            else:
                print("CYCLES_GPU none (回退 CPU)")
        except Exception as e:
            print("CYCLES_GPU fail", e)
    # ── 提速设置（体积场景关键）──
    scene.cycles.use_denoising = True
    try:
        scene.cycles.denoiser = "OPENIMAGEDENOISE"
    except Exception:
        pass
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = 0.02
    scene.cycles.max_bounces = 4
    scene.cycles.diffuse_bounces = 2
    scene.cycles.glossy_bounces = 2
    scene.cycles.transmission_bounces = 2
    scene.cycles.volume_bounces = 1
    scene.cycles.transparent_max_bounces = 4
    try:
        scene.cycles.volume_max_steps = 64
        scene.cycles.volume_step_rate = float(os.environ.get("BL_VOL_STEP", 6.0))
    except Exception:
        pass
    scene.render.use_persistent_data = True
else:
    scene.eevee.taa_render_samples = max(16, samples)
scene.render.resolution_x, scene.render.resolution_y = res_x, res_y
scene.render.resolution_percentage = 100
scene.render.film_transparent = False
scene.view_settings.view_transform = "AgX"

# 世界：渐变（纸色 → 深）
world = bpy.data.worlds.new("W"); scene.world = world
world.use_nodes = True
nt = world.node_tree; nt.nodes.clear()
wout = nt.nodes.new("ShaderNodeOutputWorld")
bg = nt.nodes.new("ShaderNodeBackground")
grad = nt.nodes.new("ShaderNodeTexGradient")
tex = nt.nodes.new("ShaderNodeTexCoord")
mapn = nt.nodes.new("ShaderNodeMapping")
ramp = nt.nodes.new("ShaderNodeValToRGB")
ramp.color_ramp.elements[0].color = col(4)
ramp.color_ramp.elements[1].color = col(0)
bg.inputs[0].default_value = col(0)
bg.inputs[1].default_value = 0.55
nt.links.new(tex.outputs["Generated"], mapn.inputs["Vector"])
nt.links.new(mapn.outputs["Vector"], grad.inputs["Vector"])
nt.links.new(grad.outputs["Color"], ramp.inputs["Fac"])
nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
if S.get("world") == "nishita":
    # 纯物理天空：不做渐变混合，避免被调色板染成棕色
    try:
        sky = nt.nodes.new("ShaderNodeTexSky")
        # Blender 5.x 之后没有 NISHITA 了（改名 MULTIPLE_SCATTERING），逐档尝试
        for _st in ("MULTIPLE_SCATTERING", "SINGLE_SCATTERING", "NISHITA", "HOSEK_WILKIE", "PREETHAM"):
            try:
                sky.sky_type = _st
                print("SKY type", _st)
                break
            except Exception:
                continue
        sky.sun_elevation = float((S.get("sun") or {}).get("elev_deg", 10.0)) * math.pi / 180.0
        sky.sun_rotation = -float((S.get("sun") or {}).get("azim_deg", 200.0)) * math.pi / 180.0
        sr = S.get("sky") or {}
        # 各版本属性名不一致：有就设，没有就跳过（不要因此整段失败）
        for attr, key, dflt in (
            ("sun_intensity", "sun_intensity", 0.5),
            ("altitude", "altitude", 500.0),
            ("air_density", "air", 1.0),
            ("dust_density", "dust", 0.6),
            ("ozone_density", "ozone", 1.0),
            ("aerosol_density", "dust", 0.6),
        ):
            if hasattr(sky, attr):
                try:
                    setattr(sky, attr, float(sr.get(key, dflt)))
                except Exception:
                    pass
        nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = float((S.get("sky") or {}).get("strength", 0.45))
        print("WORLD nishita")
    except Exception as e:
        import sys as _sys
        print("WORLD nishita fail", e, file=_sys.stderr)
try:
    if S.get("world") != "nishita":
        sky = nt.nodes.new("ShaderNodeTexSky")
    sky.sky_type = "NISHITA"
    sky.sun_elevation = 0.35
    mixw = nt.nodes.new("ShaderNodeMixRGB")
    mixw.blend_type = "MIX"
    mixw.inputs["Fac"].default_value = 0.45
    nt.links.new(ramp.outputs["Color"], mixw.inputs[1])
    nt.links.new(sky.outputs["Color"], mixw.inputs[2])
    nt.links.new(mixw.outputs["Color"], bg.inputs["Color"])
except Exception:
    pass
nt.links.new(bg.outputs["Background"], wout.inputs["Surface"])

def srgb_socket(node, name, rgba):
    node.inputs[name].default_value = rgba[:3] + (1.0,) if len(node.inputs[name].default_value) == 4 else rgba[:3]

def material(name, color, rough=0.5, metal=0.0, emit=None, emit_strength=0.0, transmission=0.0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    if "Transmission Weight" in bsdf.inputs:
        bsdf.inputs["Transmission Weight"].default_value = transmission
    if emit is not None:
        bsdf.inputs["Emission Color"].default_value = emit
        bsdf.inputs["Emission Strength"].default_value = emit_strength
    return m

def detail_mat(m, scale=90.0, bump=0.05, rough_var=0.12):
    """给材质加程序化细节：噪声→Bump，噪声→粗糙度变化（去塑料感）。"""
    try:
        nt = m.node_tree
        bsdf = nt.nodes.get("Principled BSDF")
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = scale
        noise.inputs["Detail"].default_value = 6.0
        bmp = nt.nodes.new("ShaderNodeBump")
        bmp.inputs["Strength"].default_value = bump
        nt.links.new(noise.outputs["Fac"], bmp.inputs["Height"])
        nt.links.new(bmp.outputs["Normal"], bsdf.inputs["Normal"])
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].color = (max(0.0, rough_var),) * 3 + (1,)
        ramp.color_ramp.elements[1].color = (min(1.0, 0.5 + rough_var),) * 3 + (1,)
        nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], bsdf.inputs["Roughness"])
    except Exception:
        pass
    return m


GROUND_Y = -1.75
# three.js (x,y,z) → Blender (x, -z, y)：Y 轴互换、Z 取反
def conv(x, y, z):
    return (float(x), -float(z), float(y))

def aim_camera(cam, pos, target):
    cam.location = pos
    d = Vector(target) - Vector(pos)
    cam.rotation_mode = "QUATERNION"
    cam.rotation_quaternion = d.to_track_quat("-Z", "Y")

# 地面
bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, GROUND_Y))
ground = bpy.context.object
ground.data.materials.append(material("ground", col(4), rough=0.92))
gm = ground.data.materials[0]
if gm and gm.use_nodes:
    nt0 = gm.node_tree
    noise = nt0.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 60.0 + 120.0 * DETAIL
    bump = nt0.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.06 + 0.12 * DETAIL
    nt0.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt0.links.new(bump.outputs["Normal"], nt0.nodes["Principled BSDF"].inputs["Normal"])

def add_mesh_prim(kind, **kw):
    if kind == "sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(radius=kw.get("r", 0.3), location=kw["loc"])
    elif kind == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(radius=kw.get("r", 0.1), depth=kw.get("depth", 1.0), location=kw["loc"])
    elif kind == "cube":
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=kw["loc"])
    elif kind == "torus":
        bpy.ops.mesh.primitive_torus_add(location=kw["loc"], major_radius=kw.get("R", 1.0), minor_radius=kw.get("r", 0.02))
    elif kind == "cone":
        bpy.ops.mesh.primitive_cone_add(radius1=kw.get("r", 0.2), depth=kw.get("depth", 1.0), location=kw["loc"])
    ob = bpy.context.object
    return ob

# ── 主体：hero（有 imagery 场景时默认不放主体，避免多余物件）──
hero = S.get("hero") or {}
if (S.get("imagery") and not hero.get("keep")):
    hero = {}
hkind = (hero.get("kind") or "lathe") if hero else None
hm = detail_mat(material("hero", col(hero.get("color", 4)), rough=hero.get("rough", 0.34), metal=hero.get("metal", 0.45)), 120, 0.02, 0.10)
if hkind:
    if hkind == "knot":
        bpy.ops.mesh.primitive_torus_knot_add(location=conv(hero.get("x", 0.8), GROUND_Y + 1.15, 0))
        ob = bpy.context.object
        ob.scale = (hero.get("scale", 1.0),) * 3
    elif hkind == "spheres":
        ob = add_mesh_prim("sphere", loc=conv(hero.get("x", 0.8), GROUND_Y + 0.55, 0), r=hero.get("scale", 0.55) * 0.55)
    else:  # lathe：用旋转体近似（圆柱 + 圆角）
        prof = hero.get("profile") or [[0, -0.46], [0.30, -0.42], [0.36, 0.02], [0.27, 0.38], [0.14, 0.45], [0, 0.47]]
        mesh = bpy.data.meshes.new("hero"); obj = bpy.data.objects.new("hero", mesh)
        bpy.context.collection.objects.link(obj)
        bm = bmesh.new()
        verts = [bm.verts.new((r, 0, y)) for r, y in prof]
        bm.verts.ensure_lookup_table()
        for i in range(len(verts) - 1):
            bm.edges.new((verts[i], verts[i + 1]))
        bmesh.ops.spin(bm, geom=list(bm.verts) + list(bm.edges), cent=(0, 0, 0), axis=(0, 0, 1), angle=math.pi * 2, steps=96)
        bm.to_mesh(mesh); bm.free()
        bpy.context.view_layer.objects.active = obj
        ob = obj
        ob.scale = (hero.get("scale", 1.15),) * 3
        ob.location = conv(hero.get("x", 0.8), GROUND_Y, 0)
    ob.data.materials.append(hm)
    bpy.ops.object.shade_smooth() if ob.type == "MESH" else None
    ob.select_set(True); bpy.context.view_layer.objects.active = ob
    try:
        bpy.ops.object.modifier_add(type="BEVEL")
        bpy.context.object.modifiers[-1].width = 0.006 + 0.014 * DETAIL
        bpy.ops.object.modifier_add(type="SUBSURF")
        bpy.context.object.modifiers[-1].levels = 1 if DETAIL < 0.6 else 2
    except Exception:
        pass

# ── 意象骨架 ──
imgs = S.get("imagery") or []
for it in imgs:
    k = it.get("kind")
    if k == "figure":
        pose = it.get("pose", "stand")
        scale = it.get("scale", 1.0)
        base = conv(it.get("x", 0.6), GROUND_Y + 0.02, it.get("z", 0.4))
        parts = []
        body = add_mesh_prim("cylinder", r=0.155 * scale, depth=0.50 * scale, loc=(base[0], base[1], base[2] + 0.60 * scale))
        # 肩
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.165 * scale, location=(base[0], base[1], base[2] + 0.84 * scale))
        shoulders = bpy.context.object
        shoulders.scale = (1.0, 0.42, 0.30)
        # 颈
        neck = add_mesh_prim("cylinder", r=0.045 * scale, depth=0.10 * scale, loc=(base[0], base[1], base[2] + 0.95 * scale))
        head = add_mesh_prim("sphere", r=0.112 * scale, loc=(base[0], base[1], base[2] + 1.05 * scale))
        parts += [body, shoulders, neck, head]
        for sx in (-1, 1):
            leg = add_mesh_prim("cylinder", r=0.055 * scale, depth=0.52 * scale,
                                loc=(base[0] + sx * 0.09 * scale, base[1], base[2] + 0.28 * scale))
            if pose == "walk":
                leg.rotation_euler = (sx * 0.22, 0, 0)
            if pose == "sit":
                leg.rotation_euler = (-1.15, 0, 0)
                leg.location.z = base[2] + 0.30 * scale
            arm = add_mesh_prim("cylinder", r=0.040 * scale, depth=0.42 * scale,
                                loc=(base[0] + sx * 0.205 * scale, base[1], base[2] + 0.70 * scale))
            arm.rotation_euler = (0, sx * 0.17, 0)
            bpy.ops.mesh.primitive_uv_sphere_add(radius=0.032 * scale,
                location=(base[0] + sx * 0.235 * scale, base[1], base[2] + 0.47 * scale))
            hand = bpy.context.object
            parts += [leg, arm, hand]
        fm = detail_mat(material("figure", col(it.get("color", 1)), rough=0.6), 260, 0.012, 0.16)
        for p in parts:
            p.data.materials.append(fm)
            try:
                for poly in p.data.polygons:
                    poly.use_smooth = True
                p.modifiers.new("sub", "SUBSURF").levels = 2 if DETAIL > 0.6 else 1
            except Exception:
                pass
    elif k == "window":
        w, h = it.get("w", 2.4), it.get("h", 2.8)
        cx, cz = it.get("x", 0.5), it.get("z", -1.7)
        wm = material("frame", col(it.get("color", 1)), rough=0.5)
        # 窗台
        sill = add_mesh_prim("cube", loc=conv(cx, GROUND_Y + 0.03, cz + 0.06))
        sill.scale = ((w + 0.16) / 2, 0.11, 0.03)
        sill.data.materials.append(wm)
        for dx, dy, sx, sy in [(0, h / 2, w, 0.06), (0, -h / 2, w, 0.06), (-w / 2, 0, 0.06, h), (w / 2, 0, 0.06, h)]:
            bx, by, bz = conv(cx + dx, GROUND_Y + h / 2 + dy, cz)
            bar = add_mesh_prim("cube", loc=(bx, by, bz))
            bar.scale = (sx / 2, 0.035, sy / 2)
            bar.data.materials.append(wm)
        # 背后光
        bpy.ops.mesh.primitive_plane_add(size=1, location=conv(cx, GROUND_Y + h / 2, cz - 0.03))
        lp = bpy.context.object
        lp.scale = (w * 0.47, h * 0.46, 1)
        lp.rotation_euler = (math.radians(90), 0, 0)
        lp.data.materials.append(material("winlight", col(0), rough=1.0, emit=col(0), emit_strength=2.2))
    elif k == "rain":
        n = int(it.get("count", 800) * 0.35)      # Blender 里用几何雨，数量打折
        rm = material("rain", col(0), rough=0.35, emit=col(0), emit_strength=0.35)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.0018, depth=0.20, location=(0, 0, -100))
        proto = bpy.context.object
        proto.data.materials.append(rm)
        for i in range(n):
            inst = proto.copy()
            bpy.context.collection.objects.link(inst)
            inst.location = ((random.random() - 0.5) * 12, (random.random() - 0.5) * 4 - 2.0, -1.0 + random.random() * 5)
        proto.hide_render = True
    elif k == "horizon":
        # 远雾：一块半透明面片（不是发光方块，否则像一堵白墙）
        m2 = bpy.data.materials.new("haze")
        m2.use_nodes = True
        bs = m2.node_tree.nodes.get("Principled BSDF")
        bs.inputs["Base Color"].default_value = (0.86, 0.88, 0.94, 1.0)
        bs.inputs["Roughness"].default_value = 1.0
        bs.inputs["Alpha"].default_value = float(it.get("haze", 0.30))
        m2.blend_method = "BLEND"
        bpy.ops.mesh.primitive_plane_add(size=1, location=conv(0, GROUND_Y + 1.4, it.get("z", -6.5)))
        hz = bpy.context.object
        hz.scale = (14, 2.6, 1)
        hz.rotation_euler = (math.radians(90), 0, 0)
        hz.data.materials.append(m2)
    elif k == "branches":
        bm2 = material("wood", col(it.get("color", 1)), rough=0.85)
        def branch(pos, direction, length, radius, depth):
            end = pos + direction.normalized() * length
            mid = (pos + end) / 2
            seg = add_mesh_prim("cylinder", r=radius, depth=length, loc=tuple(mid))
            seg.rotation_mode = "QUATERNION"
            seg.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(direction.normalized())
            seg.data.materials.append(bm2)
            if depth <= 0:
                return
            for ang in (-0.5, 0.45, 0.95):
                nd = direction.copy(); nd.rotate(Euler((0, ang, 0)))
                branch(end, nd, length * 0.72, radius * 0.62, depth - 1)
        bx, by, bz = conv(it.get("x", -1.6), GROUND_Y, it.get("z", -1.0))
        branch(Vector((bx, by, bz)), Vector((0.12, 0, 1)), 1.1, 0.055, int(it.get("depth", 3)))
    elif k == "ring_set":
        cnt = int(it.get("count", 3)); r0 = float(it.get("r0", 1.0)); dr = float(it.get("dr", 0.55))
        rm = material("ring", col(it.get("color", 1)), rough=0.25, metal=0.8)
        cx, cz = it.get("x", 0.6), it.get("z", 0.0)
        for i in range(cnt):
            bpy.ops.mesh.primitive_torus_add(location=conv(cx, GROUND_Y + 0.02, cz),
                                             major_radius=r0 + i * dr, minor_radius=float(it.get("tube", 0.012)),
                                             major_segments=96, minor_segments=12)
            bpy.context.object.data.materials.append(rm)
    elif k == "ribbon":
        # 纸带：贝塞尔曲线 + bevel
        cu = bpy.data.curves.new("ribbon", "CURVE")
        cu.dimensions = "3D"; cu.bevel_depth = float(it.get("width", 0.02)); cu.bevel_resolution = 4
        sp = cu.splines.new("BEZIER"); sp.bezier_points.add(3)
        for i, (px, py) in enumerate([(-4, -1), (-1.4, 0.8), (1.6, -0.6), (4.2, 0.6)]):
            bp = sp.bezier_points[i]
            bp.co = (px, 0.0, GROUND_Y + 1.1 + py)
            bp.handle_left_type = bp.handle_right_type = "AUTO"
        ob = bpy.data.objects.new("ribbon", cu)
        bpy.context.collection.objects.link(ob)
        ob.location = conv(it.get("x", 0), 0, 0)
        ob.data.materials.append(material("rib", col(it.get("color", 3)), rough=0.45))
    elif k == "linework":
        n = int(it.get("count", 60))
        lm = material("line", col(it.get("color", 1)), rough=0.6)
        for i in range(n):
            w = 0.02 + random.random() * 0.05
            ln = 1.0 + random.random() * 3.0
            bpy.ops.mesh.primitive_cube_add(size=1, location=conv(
                (random.random() - 0.5) * 7, GROUND_Y + random.random() * 3.4, (random.random() - 0.5) * 3))
            ob = bpy.context.object
            ob.scale = (ln if random.random() < 0.5 else w, w, 0.006)
            ob.rotation_euler = (0, 0, (random.random() - 0.5) * 0.3)
            ob.data.materials.append(lm)
    elif k == "halftone":
        cols = int(it.get("cols", 16)); rows = int(it.get("rows", 9))
        hm3 = material("dot", col(it.get("color", 1)), rough=0.5)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=float(it.get("r", 0.02)),
                                             location=conv(-1.6, GROUND_Y + 1.6, 0))
        proto = bpy.context.object
        proto.data.materials.append(hm3)
        for a in range(cols):
            for b in range(rows):
                inst = proto.copy(); bpy.context.collection.objects.link(inst)
                inst.location = conv(-2.2 + a * 0.12, GROUND_Y + 0.9 + b * 0.12, -0.6)
        proto.hide_render = True
    elif k == "bars":
        n = int(it.get("n", 4))
        bm3 = material("bars", col(it.get("color", 3)), rough=0.5, metal=0.2)
        for i in range(n):
            hgt = 0.3 + random.random() * 1.0
            bpy.ops.mesh.primitive_cube_add(size=1, location=conv(
                (it.get("x", 0.6)) + 0.9 + i * float(it.get("gap", 0.24)), GROUND_Y + hgt / 2, it.get("z", 0)))
            ob = bpy.context.object
            ob.scale = (0.06, 0.06, hgt / 2)
            ob.data.materials.append(bm3)
    elif k == "terrain":
        bpy.ops.mesh.primitive_plane_add(size=float(it.get("size", 40)),
                                         location=conv(0, GROUND_Y - 0.02, it.get("z", -6)))
        ob = bpy.context.object
        ob.name = "terrain"
        tex = bpy.data.textures.new("terr", type="CLOUDS")
        tex.noise_scale = float(it.get("noise", 3.0))
        tex.noise_depth = 3
        mod = ob.modifiers.new("disp", "DISPLACE")
        mod.texture = tex
        mod.strength = float(it.get("amp", 0.35))
        mod.mid_level = 0.5
        try:
            ob.modifiers.new("sub", "SUBSURF").levels = 2
        except Exception:
            pass
        tm = material("terrain", col(it.get("color", 4)), rough=0.95)
        detail_mat(tm, 6.0, 0.35, 0.10)
        ob.data.materials.append(tm)
    elif k == "grass":
        # 一根草 = 3 顶点三角面；复制 N 份共享同一 mesh（内存友好）
        import random as _r
        me = bpy.data.meshes.new("blade")
        _bh = float(it.get("h", 0.32))
        me.from_pydata([(-0.007, 0, 0), (0.007, 0, 0), (0.0, 0, _bh)], [], [(0, 1, 2)])
        me.update()
        gm = material("grass", col(it.get("color", 3)), rough=0.85)
        me.materials.append(gm)
        n = int(it.get("count", 600))
        rmin, rmax = float(it.get("rMin", 1.0)), float(it.get("rMax", 8.0))
        zc = float(it.get("z", 2.0))
        for i in range(n):
            ob = bpy.data.objects.new(f"g{i}", me)
            bpy.context.collection.objects.link(ob)
            ang = _r.random() * 6.283
            rad = rmin + (rmax - rmin) * (_r.random() ** 0.7)
            ob.location = conv(_r.uniform(-1, 1) * rad, GROUND_Y + 0.02, zc + _r.uniform(-1, 1) * rad * 0.4)
            ob.rotation_euler = (_r.uniform(-0.25, 0.25), _r.uniform(-0.25, 0.25), ang)
            ob.scale = (_r.uniform(0.8, 1.6),) * 3
    elif k == "clouds":
        # 真体积云：立方体域 + 双尺度噪声 × 高度梯度
        bpy.ops.mesh.primitive_cube_add(size=1, location=conv(it.get("x", 0), it.get("y", 6.0), it.get("z", -30)))
        vol = bpy.context.object
        vol.name = "clouds"
        vol.scale = (float(it.get("w", 90)), float(it.get("d", 60)), float(it.get("h", 22)))
        base_density = float(it.get("density", 0.05)) * float(S.get("_emo_intensity", 1.0))
        vm = bpy.data.materials.new("cloudvol")
        vm.use_nodes = True
        nt = vm.node_tree
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        pv = nt.nodes.new("ShaderNodeVolumePrincipled")
        pv.inputs["Color"].default_value = col(it.get("color", 0))
        pv.inputs["Anisotropy"].default_value = 0.45
        pv.inputs["Density"].default_value = 0.0

        # 两个尺度的噪声相加
        n1 = nt.nodes.new("ShaderNodeTexNoise")
        n1.inputs["Scale"].default_value = float(it.get("noise_scale", 0.18))
        n1.inputs["Detail"].default_value = 8.0
        n1.inputs["Roughness"].default_value = 0.62
        n2 = nt.nodes.new("ShaderNodeTexNoise")
        n2.inputs["Scale"].default_value = float(it.get("noise_scale", 0.18)) * 3.7
        n2.inputs["Detail"].default_value = 5.0
        addn = nt.nodes.new("ShaderNodeMath")
        addn.operation = "ADD"
        nt.links.new(n1.outputs["Fac"], addn.inputs[0])
        nt.links.new(n2.outputs["Fac"], addn.inputs[1])
        half = nt.nodes.new("ShaderNodeMath")
        half.operation = "MULTIPLY"
        half.inputs[1].default_value = 0.5
        nt.links.new(addn.outputs["Value"], half.inputs[0])

        # 高度梯度：靠下的更浓
        texc = nt.nodes.new("ShaderNodeTexCoord")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(texc.outputs["Object"], sep.inputs["Vector"])
        grad = nt.nodes.new("ShaderNodeMapRange")
        grad.inputs["From Min"].default_value = -0.5
        grad.inputs["From Max"].default_value = 0.5
        grad.inputs["To Min"].default_value = float(it.get("grad_lo", 1.0))
        grad.inputs["To Max"].default_value = float(it.get("grad_hi", 0.15))
        nt.links.new(sep.outputs["Z"], grad.inputs["Value"])

        mul = nt.nodes.new("ShaderNodeMath")
        mul.operation = "MULTIPLY"
        mul.inputs[1].default_value = base_density
        nt.links.new(half.outputs["Value"], mul.inputs[0])
        mul2 = nt.nodes.new("ShaderNodeMath")
        mul2.operation = "MULTIPLY"
        nt.links.new(mul.outputs["Value"], mul2.inputs[0])
        nt.links.new(grad.outputs["Result"], mul2.inputs[1])
        nt.links.new(mul2.outputs["Value"], pv.inputs["Density"])
        nt.links.new(pv.outputs["Volume"], out.inputs["Volume"])
        vol.data.materials.append(vm)
    elif k == "sunset_window":
        # 发光窗：一个高亮面片 + 窗棂（逆光光源）
        w = float(it.get("w", 3.2)); h = float(it.get("h", 2.2))
        cx, cy = float(it.get("x", 0.0)), float(it.get("y", 1.35))
        bpy.ops.mesh.primitive_plane_add(size=1, location=conv(cx, cy, it.get("z", -3.0)))
        win = bpy.context.object
        win.scale = (w, h, 1)
        win.rotation_euler = (math.radians(90), 0, 0)
        wm2 = material("sunsetwin", (1.0, 0.62, 0.34, 1.0), rough=1.0,
                       emit=(1.0, 0.55, 0.28, 1.0), emit_strength=float(it.get("emit", 12.0)))
        win.data.materials.append(wm2)
        # 窗框（暗色）
        fm2 = material("winframe", col(2), rough=0.7)
        for dx, dy, sx, sy in [(0, h / 2, w, 0.05), (0, -h / 2, w, 0.05),
                               (-w / 2, 0, 0.05, h), (w / 2, 0, 0.05, h),
                               (-w / 6, 0, 0.03, h), (w / 6, 0, 0.03, h)]:
            x2, y2, z2 = conv(cx + dx, cy + dy, it.get("z", -3.0) + 0.03)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(x2, y2, z2))
            bar = bpy.context.object
            bar.scale = (sx, 0.03, sy)
            bar.data.materials.append(fm2)
    elif k == "curtain":
        # 纱帘：细分平面 + 波浪位移 + 半透明发光（逆光时"透亮"）
        w = float(it.get("w", 2.6)); h = float(it.get("h", 2.8))
        bpy.ops.mesh.primitive_plane_add(size=1, location=conv(it.get("x", 0.0), it.get("y", 1.4), it.get("z", -2.6)))
        cur = bpy.context.object
        cur.scale = (w, h, 1)
        cur.rotation_euler = (math.radians(90), 0, 0)
        try:
            cur.modifiers.new("sub", "SUBSURF").levels = 4
            tex = bpy.data.textures.new("folds", type="WOOD")
            tex.noise_scale = float(it.get("fold", 0.35))
            dm = cur.modifiers.new("folds", "DISPLACE")
            dm.texture = tex
            dm.strength = float(it.get("fold_amp", 0.12))
        except Exception:
            pass
        cm = bpy.data.materials.new("curtain")
        cm.use_nodes = True
        bs = cm.node_tree.nodes.get("Principled BSDF")
        bs.inputs["Base Color"].default_value = (0.86, 0.88, 0.94, 1.0)
        bs.inputs["Roughness"].default_value = 0.85
        bs.inputs["Alpha"].default_value = float(it.get("alpha", 0.45))
        try:
            bs.inputs["Transmission Weight"].default_value = 0.35
        except Exception:
            pass
        cm.blend_method = "BLEND"
        cur.data.materials.append(cm)
    elif k == "silhouette_piano":
        # 钢琴剪影：箱体 + 腿 + 顶盖（暗色高粗糙）
        pm = material("piano", col(1), rough=0.35, metal=0.25)
        cx, cy, cz = float(it.get("x", 0.4)), float(it.get("y", 0.0)), float(it.get("z", 0.0))
        bpy.ops.mesh.primitive_cube_add(size=1, location=conv(cx, 0.85, cz))
        body = bpy.context.object
        body.scale = (1.45, 0.55, 0.32)
        body.data.materials.append(pm)
        bpy.ops.mesh.primitive_cube_add(size=1, location=conv(cx, 1.22, cz))
        lid = bpy.context.object
        lid.scale = (1.45, 0.55, 0.03)
        lid.rotation_euler = (0, math.radians(-16), 0)
        lid.data.materials.append(pm)
        for sx in (-1, 1):
            for sy in (-1, 1):
                bpy.ops.mesh.primitive_cube_add(size=1, location=conv(cx + sx * 1.1, 0.36, cz + sy * 0.36))
                leg = bpy.context.object
                leg.scale = (0.05, 0.42, 0.05)
                leg.data.materials.append(pm)
    elif k == "ocean":
        bpy.ops.mesh.primitive_plane_add(size=float(it.get("size", 60)),
                                         location=conv(0, float(it.get("y", 0.35)), it.get("z", -8)))
        oc = bpy.context.object
        om = material("ocean", col(3), rough=0.15, metal=0.0)
        oc.data.materials.append(om)
    elif k == "atmosphere":
        # 薄雾域：太阳光穿过云缝时产生体积光束
        bpy.ops.mesh.primitive_cube_add(size=1, location=conv(0, 2.0, -14))
        atm = bpy.context.object
        atm.name = "atmosphere"
        atm.scale = (80, 60, 14)
        am = bpy.data.materials.new("atmvol")
        am.use_nodes = True
        ant = am.node_tree
        ant.nodes.clear()
        aout = ant.nodes.new("ShaderNodeOutputMaterial")
        apv = ant.nodes.new("ShaderNodeVolumePrincipled")
        apv.inputs["Color"].default_value = col(0)
        apv.inputs["Density"].default_value = float(it.get("density", 0.0022))
        apv.inputs["Anisotropy"].default_value = 0.6
        ant.links.new(apv.outputs["Volume"], aout.inputs["Volume"])
        atm.data.materials.append(am)
    elif k == "aurora":
        bpy.ops.mesh.primitive_plane_add(size=1, location=conv(0, float(it.get("y", 4.0)), it.get("z", -20)))
        ob = bpy.context.object
        ob.scale = (float(it.get("w", 24)), float(it.get("h", 3.0)), 1)
        ob.rotation_euler = (math.radians(90), 0, 0)
        am = material("aurora", col(it.get("color", 2)), rough=1.0,
                      emit=col(it.get("color", 2)), emit_strength=float(it.get("emit", 3.0)))
        ob.data.materials.append(am)
    elif k == "smoke":
        sm = material("smoke", col(it.get("color", 4)), rough=1.0)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, GROUND_Y + 1.4))
        vol = bpy.context.object
        vol.scale = (2.4, 1.2, 1.2)
        m = vol.data.materials.get("Vol") or bpy.data.materials.new("Vol")
        m.use_nodes = True
        nt2 = m.node_tree; nt2.nodes.clear()
        out = nt2.nodes.new("ShaderNodeOutputMaterial")
        pv = nt2.nodes.new("ShaderNodeVolumePrincipled")
        pv.inputs["Density"].default_value = 0.12
        pv.inputs["Color"].default_value = col(it.get("color", 4))
        nt2.links.new(pv.outputs["Volume"], out.inputs["Volume"])
        vol.data.materials.append(m)

# ── 灯光（三点）──
def light(kind, loc, energy, size=3.0, color=(1, 1, 1)):
    bpy.ops.object.light_add(type=kind, location=loc)
    L = bpy.context.object
    L.data.energy = energy
    L.data.color = color
    if kind == "AREA":
        L.data.size = size
    return L

key = light("AREA", (-3.4, -4.2, 3.6), 900.0, 4.0)
fill = light("AREA", (4.2, -3.0, 1.6), 240.0, 5.0, (0.75, 0.82, 1.0))
rim = light("AREA", (0.8, 4.6, 2.4), 420.0, 3.0, (1.0, 0.72, 0.5))
_sun_e = float((S.get("sun") or {}).get("energy", 4.0)) * (0.55 + 0.9 * float(S.get("_emo_intensity", 1.0)))
_sun_a = float((S.get("sun") or {}).get("angle_deg", 1.2))
_sun_el = float((S.get("sun") or {}).get("elev_deg", 8.0))
_sun_az = float((S.get("sun") or {}).get("azim_deg", 200.0))
_el, _az = math.radians(_sun_el), math.radians(_sun_az)
_sd = (math.cos(_el) * math.cos(_az), math.cos(_el) * math.sin(_az), math.sin(_el))
bpy.ops.object.light_add(type="SUN", location=(0, 0, 10))
sun = bpy.context.object
sun.data.energy = _sun_e
sun.data.angle = math.radians(_sun_a)
sun.data.color = (1.0, 0.92, 0.78)
sun.rotation_mode = "QUATERNION"
sun.rotation_quaternion = Vector((0, 0, -1)).rotation_difference(Vector(_sd))

# ── 相机 + 情感/镜头曲线 ──
cam_data = bpy.data.cameras.new("cam"); cam = bpy.data.objects.new("cam", cam_data)
bpy.context.collection.objects.link(cam); scene.camera = cam
# 焦距 = 传感器(36mm) / (2*tan(fov/2))
import math as _m
_fov = float(CP.get("fov", 40.0))
cam_data.lens = max(14.0, 36.0 / (2.0 * _m.tan(_m.radians(_fov) / 2.0)))
cam_data.sensor_width = 36.0
cam_data.dof.use_dof = True
cam_data.dof.focus_distance = 7.4
cam_data.dof.aperture_fstop = max(1.2, 8.0 - 7.0 * float(CP.get("negative_space", 0.4)))

emo = S.get("emotion") and None
shots = S.get("shot_plan") or []
duration = float(S.get("duration") or 6.0)
fps = 30
total_frames = int(round(duration * fps))
_limit = int(os.environ.get("BL_FRAMES", 0)) or int(S.get("render_frames") or 0)
scene.frame_start, scene.frame_end = 1, max(1, total_frames)

# 每镜机位关键帧
if shots:
    for sh in shots:
        f0 = int(round(sh["t0"] * fps)) + 1
        f1 = int(round(sh["t1"] * fps))
        cam_map = {"push": 7.8, "drift": 7.4, "still": 7.2}
        z = cam_map.get(sh.get("camera", "still"), 7.4)
        _win = next((x for x in (S.get("imagery") or []) if x.get("kind") == "sunset_window"), None)
        if _win:
            tgt = conv(float(_win.get("x", 0.0)), float(_win.get("y", 1.4)), float(_win.get("z", -3.0)))
        else:
            tgt = conv(float(CP.get("look_x", 0.4)), float(CP.get("look_y", -0.35)), 0)
        for f, zz in ((f0, z), (max(f0 + 1, f1), z - (0.55 if sh.get("camera") == "push" else 0.18))):
            aim_camera(cam, conv(0.6 + (CP.get("hero_x") or 0) * 1.6, 0.55 + 0.5 * (CP.get("cam_height") or 0.4), zz), tgt)
            cam.keyframe_insert("location", frame=min(max(f, 1), total_frames))
            cam.keyframe_insert("rotation_quaternion", frame=min(max(f, 1), total_frames))
else:
    _win2 = next((x for x in (S.get("imagery") or []) if x.get("kind") == "sunset_window"), None)
    _tgt2 = (conv(float(_win2.get("x", 0.0)), float(_win2.get("y", 1.4)), float(_win2.get("z", -3.0)))
             if _win2 else conv(float(CP.get("look_x", 0.4)), float(CP.get("look_y", -0.35)), 0))
    aim_camera(cam, conv(0.6, 0.55, 7.4), _tgt2)

# 曝光随情感曲线（把 intensity 打到 film exposure）
cur = ((S.get("emotion_curves") or {}).get("intensity")) if isinstance(S.get("emotion_curves"), dict) else None
_base_exp = math.log2(max(0.05, POST_GAIN))
if cur:
    for i, v in enumerate(cur):
        f = int(round(i / max(1, len(cur) - 1) * total_frames)) + 1
        scene.view_settings.exposure = _base_exp - 1.1 + 1.5 * float(v)
        scene.keyframe_insert("view_settings.exposure", frame=f)

_fmt = os.environ.get("BL_FMT", "PNG").upper()
scene.render.image_settings.file_format = _fmt
if _fmt == "JPEG":
    scene.render.image_settings.quality = int(os.environ.get("BL_JPEG_Q", 94))
scene.render.filepath = out_path
if still is not None:
    scene.frame_set(int(round(still * fps)) + 1)
    scene.render.filepath = out_path
    bpy.ops.render.render(write_still=True)
else:
    bpy.ops.render.render(animation=True)
print("BLENDER_OK", out_path)
'''


def post_process_png(path, bloom=0.28, vig=0.55, grain=0, ca=0.0016, sat=1.06):
    """把 Blender 直出的 PNG 过一遍后处理，靠近 three.js 的观感。"""
    try:
        import numpy as np
        from PIL import Image, ImageFilter
    except Exception:
        return
    img = Image.open(path).convert("RGB")
    a = np.asarray(img, dtype=np.float32) / 255.0
    h, w, _ = a.shape
    # bloom：亮部提取 → 模糊 → 叠加
    lum = a @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    mask = np.clip((lum - 0.72) / 0.28, 0, 1)[..., None]
    bright = Image.fromarray((a * mask * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(radius=max(2, w // 260)))
    a = a + (np.asarray(bright, dtype=np.float32) / 255.0) * bloom
    # 色散：按半径做通道偏移
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w / 2.0, h / 2.0
    r = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2)
    off = (ca * r * w).astype(np.int32)
    rr = np.take_along_axis(a[..., 0], np.clip(xx + off, 0, w - 1).astype(np.int64), axis=1)
    bb = np.take_along_axis(a[..., 2], np.clip(xx - off, 0, w - 1).astype(np.int64), axis=1)
    a[..., 0] = rr
    a[..., 2] = bb
    # 暗角
    a *= (1.0 - vig * np.clip(r - 0.35, 0, 1) ** 1.6)[..., None]
    # 颗粒
    if grain:
        rng = np.random.default_rng(7)
        a += rng.standard_normal((h, w, 1)).astype(np.float32) * grain
    # 饱和度 + 轻 S 曲线
    g = a @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    a = g[..., None] + (a - g[..., None]) * sat
    a = np.clip(a, 0, 1)
    a = a * a * (3 - 2 * a) * 0.35 + a * 0.65
    Image.fromarray((np.clip(a, 0, 1) * 255).astype("uint8")).save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True, help="输出 .mp4 或帧目录前缀")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--engine", default="CYCLES")
    ap.add_argument("--samples", type=int, default=48)
    ap.add_argument("--res", default="1920x1080")
    ap.add_argument("--upscale", default="", help="输出分辨率，如 1920x1080（低分辨率渲染后上采样）")
    ap.add_argument("--still", type=float, default=None, help="只渲某一时刻（秒）")
    ap.add_argument("--frames", type=int, default=0, help="只渲前 N 帧（0=按 spec 时长）")
    ap.add_argument("--gpu", default="auto", choices=["auto", "on", "off"], help="GPU 渲染（默认 auto）")
    a = ap.parse_args()

    bl = find_blender()
    if not bl:
        sys.exit("找不到 Blender：先 python scripts/ensure_blender.py --install，或设 BLENDER 环境变量")

    spec = json.load(open(a.spec, encoding="utf-8-sig"))
    # 把情感曲线塞进 spec 供 Blender 端使用
    esrc = (spec.get("emotion") or {}).get("src")
    if esrc:
        for c in (esrc, os.path.join(os.path.dirname(os.path.abspath(a.spec)), esrc), os.path.join(ROOT, esrc)):
            if os.path.exists(c):
                spec["emotion_curves"] = json.load(open(c, encoding="utf-8-sig")).get("curves", {})
                break

    if a.frames:
        spec["render_frames"] = int(a.frames)
    tmp = tempfile.mkdtemp(prefix="bl_")
    sp = os.path.join(tmp, "spec.json")
    json.dump(spec, open(sp, "w", encoding="utf-8"), ensure_ascii=False)
    py = os.path.join(tmp, "build.py")
    open(py, "w", encoding="utf-8").write(BL_SCRIPT)

    out_abs = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out_abs), exist_ok=True)
    frames_dir = os.path.join(tmp, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    target = frames_dir + os.sep if a.still is None else out_abs

    cmd = [bl, "-b", "--factory-startup", "-P", py, "--", sp, target,
           a.engine, str(a.samples), a.res, str(a.still) if a.still is not None else "-",
           a.gpu]
    print("[blender]", " ".join(cmd[:6]), "…")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    for line in (r.stdout or "").splitlines():
        if line.startswith(("CYCLES_GPU", "GPU:")):
            print("[blender]", line)
    if a.still is None:
        if "BLENDER_OK" not in (r.stdout or ""):
            print((r.stdout or "")[-1200:]); print((r.stderr or "")[-1200:])
            sys.exit("Blender 渲染失败")
        exts = (".png", ".jpg", ".jpeg")
        _fmt_in = os.environ.get("BL_FMT", "PNG").upper()
        pngs = sorted(f for f in os.listdir(frames_dir) if f.lower().endswith(exts))
        _post = spec.get("post", {})
        _do_post = os.environ.get("BL_POST", "1") != "0"
        for f in pngs:
            if not _do_post:
                break
            post_process_png(os.path.join(frames_dir, f),
                             bloom=float(_post.get("bloom", 0.28)),
                             vig=float(_post.get("vig", 0.55)),
                             grain=float(_post.get("grain", 0)),
                             sat=float(_post.get("sat", 1.06)))
        if not pngs:
            sys.exit("Blender 没有输出帧")
        up = []
        if a.upscale:
            _uw, _uh = a.upscale.lower().split("x")
            up = ["-vf", f"scale={_uw}:{_uh}:flags=lanczos,unsharp=5:5:0.6:5:5:0.0"]
        cmd2 = ["ffmpeg", "-y", "-v", "error", "-framerate", str(a.fps),
                "-i", os.path.join(frames_dir, "%04d" + (".jpg" if _fmt_in == "JPEG" else ".png")),
                *up,
                "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", out_abs]
        # Blender 输出形如 0001.png，可能需要重命名成 %04d
        first = pngs[0]
        if not first[:4].isdigit():
            for i, f in enumerate(pngs, 1):
                os.replace(os.path.join(frames_dir, f), os.path.join(frames_dir, f"{i:04d}.png"))
        subprocess.run(cmd2, check=True)
        print(f"[blender] -> {out_abs}  ({len(pngs)} 帧)")
    else:
        if "BLENDER_OK" not in (r.stdout or ""):
            print((r.stdout or "")[-1500:]); print((r.stderr or "")[-1500:])
            sys.exit("Blender 静帧渲染失败")
        try:
            post_process_png(out_abs,
                             bloom=float(spec.get("post", {}).get("bloom", 0.28)),
                             vig=float(spec.get("post", {}).get("vig", 0.55)),
                             grain=float(spec.get("post", {}).get("grain", 0)),
                             sat=float(spec.get("post", {}).get("sat", 1.06)))
        except Exception as e:
            print("[post] 跳过后处理：", e)
        print(f"[blender] still -> {out_abs}")


if __name__ == "__main__":
    main()
