#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""brief_check.py —— 偏题检查：先查计划，再把“实际输出”的帧摆出来给人判。

用法：
  python scripts/brief_check.py --plan proj/x/plan.json
  python scripts/brief_check.py --plan proj/x/plan.json --video renders/x.mp4 --sheet review/x_sheet.png
  python scripts/brief_check.py --plan proj/x/plan.json --self-test        # 跑内置的反例

三件事：
  1) 每镜的 based_on 必须逐字来自 brief（不是同义词、不是改写）。
  2) brief 里的每个动作片段都要被某一镜认领，否则就是漏拍。
  3) 每镜的 visible 只能写“画面里能核验的东西”；出现 brief 里没有的情节词（离别/回忆/眼泪…）直接判偏题。
第 4 步必须做：--video 会把每镜的 40%、70% 两帧拼成印样。计划合格 ≠ 成片合格，印样要人/视觉模型再看一遍。
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys
from pathlib import Path

DRIFT = ["回忆", "往事", "离别", "告别", "眼泪", "哭泣", "人生", "低谷", "童年", "母亲", "父亲",
         "故乡", "逝去", "死亡", "思念", "独白", "命运", "救赎", "遗憾", "青春"]
VERBS = ["看", "扫", "照", "走", "停", "站", "坐", "推", "拉", "开", "关", "合", "亮", "灭",
         "拿", "放", "检", "查", "转身", "低头", "停下", "经过", "映", "落", "晃", "掠过"]


def split_actions(brief: str):
    parts = re.split(r"[，,。；;、\s]+", brief)
    return [p for p in parts if len(p) >= 3]


def check_plan(plan: dict):
    brief = plan.get("brief", "")
    shots = plan.get("shots", [])
    fails, warns, notes = [], [], []
    if not brief.strip():
        fails.append("brief 为空：没有用户原话就没有可核对的标准")
    covered = set()
    drift_hits = []
    for i, s in enumerate(shots):
        tag = f"镜{i+1}"
        b = (s.get("based_on") or "").strip()
        v = (s.get("visible") or "").strip()
        if not b:
            fails.append(f"{tag} 缺 based_on")
        elif b not in brief:
            fails.append(f"{tag} based_on「{b}」不是 brief 原文（必须逐字引用）")
        else:
            covered.add(b)
        if len(v) < 8:
            fails.append(f"{tag} visible 太短，无法核验")
        if not any(x in v for x in VERBS):
            warns.append(f"{tag} visible 里没有可拍的动作词，读起来像形容词")
        for w in DRIFT:
            if w in v and w not in brief:
                drift_hits.append(f"{tag} visible 出现「{w}」，brief 里没有")
        if float(s.get("seconds", 0)) <= 0:
            fails.append(f"{tag} seconds 必须为正")
    for a in split_actions(brief):
        if not any(a in (s.get("based_on") or "") or a in (s.get("visible") or "") for s in shots):
            warns.append(f"brief 里的「{a}」没有任何一镜认领")
    if drift_hits:
        fails += drift_hits
    if len(shots) == 0:
        fails.append("没有镜头")
    return fails, warns, notes


def make_sheet(plan_path: Path, video: Path, out: Path):
    from PIL import Image, ImageDraw, ImageFont
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    try:
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                    "-of", "csv=p=0", str(video)], capture_output=True, text=True).stdout.strip())
    except Exception:
        dur = 0.0
    total = sum(float(s.get("seconds", 0)) for s in plan["shots"]) or dur or 1
    shots = plan["shots"]
    times, labels = [], []
    acc = 0.0
    for s in shots:
        sec = float(s.get("seconds", 0))
        times += [acc + sec * 0.4, acc + sec * 0.7]
        labels += [f"{s.get('based_on','')[:14]} ·40%", f"{s.get('based_on','')[:14]} ·70%"]
        acc += sec
    ims = []
    for t in times:
        p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video),
                            "-frames:v", "1", "-vf", "scale=460:-2", "-f", "image2pipe",
                            "-vcodec", "png", "-"], capture_output=True)
        if p.stdout:
            import io
            ims.append((t, Image.open(io.BytesIO(p.stdout)).convert("RGB")))
    if not ims:
        print("[sheet] 抽帧失败")
        return None
    tw, th = ims[0][1].size
    cols = 4
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * (th + 18)), (10, 10, 10))
    d = ImageDraw.Draw(sheet)
    try:
        f = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 13)
    except Exception:
        f = ImageFont.load_default()
    for i, (t, im) in enumerate(ims):
        x, y = (i % cols) * tw, (i // cols) * (th + 18)
        sheet.paste(im, (x, y))
        d.text((x + 4, y + th + 2), f"{t:.2f}s  {labels[i]}", fill=(230, 230, 230), font=f)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def self_test():
    good = {"brief": "展示司机收车后检查车厢的过程", "shots": [
        {"seconds": 5, "based_on": "收车后", "visible": "车厢只留应急灯，手电从车头亮起"},
        {"seconds": 5, "based_on": "检查车厢", "visible": "手电扫过右侧座椅，照到安全带扣"}]}
    bad = {"brief": "展示司机收车后检查车厢的过程", "shots": [
        {"seconds": 5, "based_on": "收车后", "visible": "他望向窗外，回忆涌上来"},
        {"seconds": 5, "based_on": "检查车厢", "visible": "座椅空着，像一段离别"}]}
    for name, p in (("好例子", good), ("坏例子", bad)):
        fails, warns, _ = check_plan(p)
        print(f"{name}: {'通过' if not fails else '不通过'} | 失败 {len(fails)} | 警告 {len(warns)}")
        for f in fails:
            print("   ✗", f)
        for w in warns:
            print("   △", w)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default="")
    ap.add_argument("--video", default="")
    ap.add_argument("--sheet", default="")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        self_test()
        return
    if not a.plan:
        sys.exit(__doc__)
    plan_path = Path(a.plan)
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    fails, warns, _ = check_plan(plan)
    print(f"题：《{plan.get('title','')}》  brief：{plan.get('brief','')}")
    for i, s in enumerate(plan["shots"]):
        print(f"  镜{i+1} {s.get('seconds')}s | 依据「{s.get('based_on','')}」 | 看见：{s.get('visible','')}")
    for w in warns:
        print("  △", w)
    for f in fails:
        print("  ✗", f)
    print(("  ✗ 计划层面已偏题" if fails else "  · 计划层面通过（不代表成片合格）"))
    if a.video:
        out = Path(a.sheet) if a.sheet else plan_path.parent / "review_sheet.png"
        r = make_sheet(plan_path, Path(a.video), out)
        if r:
            print(f"  · 印样 {r}（每镜 40%/70% 两帧）→ 打开看：每帧是否只服务「{plan.get('brief','')}」")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
