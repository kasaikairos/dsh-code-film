#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""intent.py —— 意图契约：把"用户一句话"拆成"他到底想表达什么"，并在渲染前卡住。

为什么需要它：弱模型最常见的失败不是画得差，是**理解错**——
把调侃当严肃、把反讽当字面、把圈层梗当普通词、把"想要的效果"当"想要的内容"。
这些错误在渲染前就能查出来，代价几乎为零；渲完再改就是重做。

用法：
  python scripts/intent.py --ask "老板让我做个视频，说要有那味儿" --out out/intent.json
  python scripts/intent.py --check out/intent.json
  python scripts/intent.py --brief out/intent.json      # 给模型看的一屏摘要

退出码：0 通过 / 1 契约不过 / 2 输入错误
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

MEME_MARK = r"梗|yyds|栓Q|芭比Q|破防|绝绝子|凡尔赛|内卷|躺平|emo|雪王|那味儿|抽象|杀疯了|赢麻|典|乐|蚌埠|牛马|city不city|已老实"

TEMPLATE = {
    "ask": "",                       # 用户原话（一字不改）
    "literal": "",                   # 字面意思：照字面拍会是什么
    "real_intent": "",               # 他真正想要的（一句话，6–24 字）
    "meme": [],                      # [{"term","layer":"literal|extended|community","keep":true,"note"}]
    "audience": "",                  # 谁看、他们在意什么
    "emotion": "",                   # 看完的单一情绪（≤4 字）
    "one_thing": "",                 # 这 8 秒只说这一件事（≤18 字，不许"和"）
    "avoid": ["", ""],               # 最容易的两种误读
    "success": "",                   # 怎样算拍对（可观察）
    "visual_proof": "",              # 哪个画面能证明这一点（具体到人和动作）
}


def _t(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    return json.dumps(v, ensure_ascii=False)


def _strip(s):
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", _t(s))


def _bg(s):
    t = _strip(s).lower()
    return {t[i:i + 2] for i in range(len(t) - 1)}


def check(d):
    fails, warns, notes = [], [], []
    ask = _t(d.get("ask"))
    lit = _t(d.get("literal"))
    real = _t(d.get("real_intent"))
    one = _t(d.get("one_thing"))
    emo = _t(d.get("emotion"))
    aud = _t(d.get("audience"))
    suc = _t(d.get("success"))
    vis = _t(d.get("visual_proof"))
    avoid = d.get("avoid") if isinstance(d.get("avoid"), list) else []
    meme = d.get("meme") if isinstance(d.get("meme"), list) else []

    # I1 真意图
    if len(_strip(ask)) < 4:
        fails.append("I1 ask 太短：先把用户原话一字不改抄进来")
    if len(_strip(lit)) < 4:
        fails.append("I1 literal 为空：先写「照字面拍会是什么」，才知道要避开什么")
    n_real = len(_strip(real))
    if n_real < 6 or n_real > 24:
        fails.append(f"I1 real_intent 需 6–24 字，当前 {n_real} 字：「{real}」")
    elif _strip(real) == _strip(ask):
        fails.append("I1 real_intent 只是复述原话：没有拆解，等于没想")

    # I2 梗
    has_meme = bool(re.search(MEME_MARK, ask))
    if has_meme and not meme:
        fails.append(f"I2 用户话里像有梗（{re.search(MEME_MARK, ask).group(0)}），但没有登记 meme："
                     "是复现它、还是只当修饰？")
    for i, m in enumerate(meme, 1):
        if not isinstance(m, dict):
            fails.append(f"I2 meme 第{i}项必须是对象（term/layer/keep/note）")
            continue
        term = _t(m.get("term"))
        layer = _t(m.get("layer"))
        if not term:
            fails.append(f"I2 meme 第{i}项没有 term")
        if layer not in ("literal", "extended", "community"):
            fails.append(f"I2 meme「{term}」的 layer 必须是 literal/extended/community")
        if "keep" not in m:
            fails.append(f"I2 meme「{term}」必须明确 keep：true=画面里要复现，false=只当语气")
        elif m.get("keep") is True and term and term not in (one + vis + suc):
            fails.append(f"I2 meme「{term}」标了 keep=true，但 one_thing/visual_proof/success 里没它："
                         "要么拍出来，要么改 keep")

    # I3 只讲一件事
    n_one = len(_strip(one))
    if n_one < 4 or n_one > 18:
        fails.append(f"I3 one_thing 需 4–18 字，当前 {n_one} 字")
    if re.search(r"[和与及、]|以及", one):
        fails.append(f"I3 one_thing 里出现「和/与/及/、」：8 秒讲不了两件事：「{one}」")

    # I4 误读
    if len([x for x in avoid if _strip(x)]) < 2:
        fails.append("I4 avoid 至少写 2 条「最容易的误读」：不写就会犯")

    # I5 成功判据要可观察
    if len(_strip(suc)) < 6:
        fails.append("I5 success 为空：写完观众应该能说出/看到什么")
    elif not re.search(r"看得见|看得到|听得到|说出|指出|数出|认出|能看见|会记住|会笑|会起鸡皮|会沉默|截图", suc):
        warns.append("I5 success 不像可观察判据（缺「看得到/说出/认出」）")

    # I6 视觉证据
    if len(_strip(vis)) < 6:
        fails.append("I6 visual_proof 为空：哪一个画面能证明这一点？")
    elif not re.search(r"人|他|她|手|脸|眼|车|门|窗|水|光|火|雨|桌|街|猫|狗|机器|屏|字|箭头|线|球|船|树|山|海|屋", vis):
        warns.append("I6 visual_proof 里没有具体的人/物：文字证明不了画面")

    # I7 情绪单一
    if not emo:
        fails.append("I7 emotion 为空：看完要有什么感觉？")
    elif len(_strip(emo)) > 4:
        warns.append(f"I7 emotion「{emo}」太长：用一个词（≤4 字）")

    # I8 观众
    if len(_strip(aud)) < 4:
        fails.append("I8 audience 为空：谁看、他们在意什么")

    # I9 真意图与"一件事"要同向
    if real and one and not (_bg(real) & _bg(one)):
        warns.append("I9 real_intent 与 one_thing 没有共同词：可能拆成了两件事")

    notes.append(f"梗 {len(meme)} 个 · 误读 {len([x for x in avoid if _strip(x)])} 条 · "
                 f"真意图 {n_real} 字")
    return fails, warns, notes


def brief(d):
    lines = [
        "# 意图摘要（贴进任务开头，别丢）",
        "",
        f"- 用户原话：{_t(d.get('ask'))}",
        f"- 字面陷阱：{_t(d.get('literal'))}",
        f"- **真正要表达**：{_t(d.get('real_intent'))}",
        f"- 这 8 秒只说：{_t(d.get('one_thing'))}",
        f"- 情绪落点：{_t(d.get('emotion'))}",
        f"- 给谁看：{_t(d.get('audience'))}",
        "",
        "## 梗 / 引用",
    ]
    for m in (d.get("meme") or []):
        if isinstance(m, dict):
            keep = "画面里要复现" if m.get("keep") else "只当语气，不拍出来"
            lines.append(f"- 「{m.get('term')}」（{m.get('layer')}）：{keep}。{_t(m.get('note'))}")
    lines += ["", "## 必须避开"]
    for x in (d.get("avoid") or []):
        if _strip(x):
            lines.append(f"- {x}")
    lines += ["", "## 拍对了的样子",
              f"- 观众能：{_t(d.get('success'))}",
              f"- 决定性画面：{_t(d.get('visual_proof'))}"]
    return "\n".join(lines)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--ask", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--check", default="")
    ap.add_argument("--brief", default="")
    a = ap.parse_args()

    if a.check or a.brief:
        fn = a.check or a.brief
        try:
            d = json.load(open(fn, encoding="utf-8-sig"))
        except FileNotFoundError:
            print(f"读不到文件：{fn}", file=sys.stderr)
            return 2
        except Exception as e:
            print(f"不是合法 JSON：{e}", file=sys.stderr)
            return 2
        if a.brief:
            print(brief(d))
            return 0
        fails, warns, notes = check(d)
        for n in notes:
            print("·", n)
        for w in warns:
            print("△", w)
        for f in fails:
            print("✗", f)
        if fails:
            print(f"\n不通过：{len(fails)} 项（先想清楚再写故事）")
            return 1
        print("\n✓ 意图契约通过" + (f"（{len(warns)} 条建议）" if warns else ""))
        return 0

    tpl = dict(TEMPLATE)
    tpl["ask"] = a.ask
    out = json.dumps(tpl, ensure_ascii=False, indent=1)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
        open(a.out, "w", encoding="utf-8").write(out)
        print(f"模板 → {a.out}")
        print("先填 literal（照字面会拍成什么）→ 再填 real_intent / one_thing / avoid / visual_proof，再 --check")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
