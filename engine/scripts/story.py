#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""story.py —— 叙事层 v2：把"看不懂"变成可检查的错误。

v2 相对 v1 的修正（来自 15 个子智能体的压力测试）：
  · 因果不再只看字数：拒绝「承接第N条：」占位符，要求与上一镜有内容重叠或含因果连接词
  · 关键词改用 2-gram：中文不再整句当一个词（v1 会把好故事判成"没回答"）
  · 逗号规则：先剥掉引号内文字与千分位逗号，再按分句/连接词判多动作（v1 误杀字幕与 10,000）
  · 概念按"个"计：支持列表/顿号串、去重、忽略"无"；预算不再静默放宽
  · 新增：who 连续性、首镜与 audience_knows 对应、时间轴闭合、可拍性、shows 必须有变化
  · 工程：UTF-8 输出与 BOM 容忍；退出码 1=契约不过，2=工具/输入错误（不再混为一谈）
  · --strict：建议项也拦；--audit：可记录答案并评分

用法：
  python scripts/story.py --topic "针孔成像" --seconds 8 --out out/story.json
  python scripts/story.py --check out/story.json [--strict]
  python scripts/story.py --audit out/story.json                  # 出盲评清单
  python scripts/story.py --audit out/story.json --answers a.json # 评分（≥5/6 才发行）
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys

# ── 词表 ────────────────────────────────────────────────────────────
CONNECTORS = r"然后|接着|于是|随后|跟着|立刻|马上|之后|并且|同时"
PLACEHOLDER = r"^(承接|接上|同上|继续|见上|同前|略|待定|待补)"
HOLLOW = r"^(因为)?(这样|如此|那个|这个|本来|就是|反正|而已|随便)$"
SELF_HINT = r"__填|填：|（填|待填|TODO|待补|上一镜的什么|这一镜的什么|上一拍的什么"
CAUSAL = r"因为|所以|由于|导致|才|说明|因此|意味着|是因为|从而|结果|使得|解释|验证|证明|取决于|源自|因而|故此|为什么"
MECHANISM = (r"穿过|透过|照到|照在|落在|投到|投在|变成|缩小|缩小到|吸收|挡住|遮住|散开|聚成|聚拢|"
             r"升起|落下|下沉|融化|凝结|蒸发|反射|折射|交叉|分开|推开|拉开|升温|降温|充满|溢出")
META_TALK = (r"片长|时长|预算|凑够|凑数|收工|赶工|交差|随便|过一下|节奏|观众|素材|剪辑|分镜|"
             r"必须存在|必须有|条数|第\d+条|这一段留给|这一镜的时长|上一镜的时长")
FUNC_CH = set("的了着过是在有和与及或而但也都很把被让使能会可要以对于之其这那我你他她它们个些么呢吗吧啊呀就才又再还只更最不没无别勿未非所因为")
CHANGE_CUE = r"换|切|镜头|转到|其实|原来|此时|另一边|与此同时"
AGENT = r"人|他|她|我|你|猫|狗|鸟|鱼|孩子|老人|女人|男人|少年|女孩|男孩"
ABSTRACT = r"能量|意识|时间|进化|场|信息|意义|灵魂|机制|原理|概念|思维|价值"
VISUAL = r"光|水|面|点|线|形|色|体|影|烟|雾|尘|火|叶|石|沙|波|纹|亮|暗|红|蓝|绿|白|黑|金|灰"
VAGUE = r"展示|表现|体现|传达|呈现|感觉|氛围|意境"
NEG = r"不|没|无|别|勿|未|非"

SPINES = {
    "question": {"desc": "疑问 → 尝试 → 反例 → 揭示 → 收束",
                 "slots": ["疑问", "尝试", "反例", "揭示"],
                 "payoff": "收束"},
    "zoom": {"desc": "宏观 → 细节 → 机制 → 回到宏观",
             "slots": ["宏观", "细节", "机制"], "payoff": "回到宏观"},
    "before_after": {"desc": "旧状态 → 触发 → 新状态 → 对照",
                     "slots": ["旧状态", "触发", "新状态"], "payoff": "对照"},
    "chase": {"desc": "想要 → 受阻 → 变通 → 达成",
              "slots": ["想要", "受阻", "变通"], "payoff": "达成"},
    "mystery": {"desc": "现象 → 猜测 → 验证 → 意外 → 解释",
                "slots": ["现象", "猜测", "验证", "意外"], "payoff": "解释"},
}


# ── 工具 ────────────────────────────────────────────────────────────
def as_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False)


def strip_punct(s: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s or "")


def norm_show(s: str) -> str:
    """R7 用：去掉标点/空白/全角数字差异，一个句号不算"画面变了"。"""
    t = as_text(s)
    t = t.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", t)


def content_bigrams(s: str) -> set:
    """S5 用：剔除虚词后的 2-gram，避免「因为」「所以」冒充共同内容。"""
    t = strip_punct(as_text(s)).lower()
    out = set()
    for i in range(len(t) - 1):
        a, b = t[i], t[i + 1]
        if re.match(r"[\u4e00-\u9fff]", a) and re.match(r"[\u4e00-\u9fff]", b):
            if a in FUNC_CH or b in FUNC_CH:
                continue
            out.add(a + b)
    out |= set(re.findall(r"[a-z0-9]{2,}", as_text(s).lower()))
    return out


def bigrams(s: str) -> set:
    """中文 2-gram + 拉丁/数字词。比 v1 的整段匹配稳得多。"""
    t = strip_punct(as_text(s)).lower()
    out = {t[i:i + 2] for i in range(len(t) - 1) if re.match(r"[\u4e00-\u9fff]", t[i])} if t else set()
    out |= set(re.findall(r"[a-z0-9]{2,}", as_text(s).lower()))
    return out


def share(a: str, b: str) -> int:
    return len(bigrams(a) & bigrams(b))


def clauses(action: str):
    """剥掉引号内文字与千分位逗号后，按分句/连接词切开。"""
    s = as_text(action)
    s = re.sub(r"(?<=\d),(?=\d{3})", "", s)                    # 10,000 → 10000
    # 引号不再抹掉：藏进引号的多动作也是多动作（v2 的洞）
    parts = re.split(r"[，,；;。！？!?…、\n]+|" + CONNECTORS, s)
    return [p.strip() for p in parts if p.strip()]


def norm_concepts(v):
    if not v:
        return []
    items = []
    if isinstance(v, (list, tuple)):
        for x in v:
            items += norm_concepts(x)
        return items
    s = as_text(v).strip()
    s = re.sub(r"[（(【\[「『][^）)】\]」』]*[）)】\]」』]", "", s)   # 括号里是注解，不算新概念
    s = re.sub(r"(?<=\d),(?=\d{3})", "", s)
    for p in re.split(r"[^\u4e00-\u9fffA-Za-z0-9]+", s):
        p = p.strip()
        if not p:
            continue
        if p in ("无", "没有", "none", "None", "-", "—", "无新概念"):
            continue
        items.append(p)
    seen, out = set(), []
    for p in items:
        k = p.lower()
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def has_verb_like(action: str) -> bool:
    """粗判"是不是动作"：含体标记/趋向补语，或含常见动作字。只用于提示，不拦。"""
    s = as_text(action)
    if re.search(r"了|着|起来|下去|上来|出去|进来|过", s):
        return True
    return bool(re.search(
        r"走|跑|落|升|亮|灭|穿|转|散|凝|开|合|推|拉|抬|浮|沉|摇|抖|涌|压|伸|缩|弯|折|碎|聚|射|照|投|映|切|换|变|生|长|消|退|渗|滴|溅|飘|吹|晃|顶|破|露|藏|盖|抱|放|握|松|碰|撞|跨|靠|离|回|出|进|入|停|等|看|听|喊|笑|哭|站|坐|躺|举|指|点|画|写|撕|贴|拧|烧|冻|融|化|爆|裂|飘|游|飞|爬|滚|流|喷|冒",
        s))


# ── 骨架 ────────────────────────────────────────────────────────────
def pick_spine(topic: str, kind: str) -> str:
    if kind and kind in SPINES:
        return kind
    t = topic or ""
    if re.search(r"为什么|怎么|如何|原理|机制|证明|解释", t):
        return "question"
    if re.search(r"微观|放大|细节|细胞|原子|针孔|成像|镜头|里", t):
        return "zoom"
    if re.search(r"故事|一个人|主角|等|寻找|旅|冒险", t):
        return "chase"
    if re.search(r"变化|从.+到|演变|过去|未来|前后|季节|春|夏|秋|冬", t):
        return "before_after"
    if re.search(r"日出|日落|海|山|雨|夜|风景|氛围", t):
        return "before_after"
    return "question"


def skeleton(topic, seconds, spine, logline="", claim=""):
    sp = SPINES[spine]
    n = max(3, min(4, max(3, round(seconds / 2.6))))
    slots = (sp["slots"] * math.ceil(n / len(sp["slots"])))[:n]
    dt = seconds / n
    st = {
        "topic": topic, "seconds": seconds, "spine": spine,
        "logline": logline, "claim": claim, "audience_knows": [],
        "beats": [], "payoff": "", "payoff_slot": sp["payoff"],
    }
    for i, name in enumerate(slots):
        st["beats"].append({
            "id": i + 1, "slot": name,
            "t0": round(i * dt, 2), "t1": round((i + 1) * dt, 2),
            "who": "", "action": "", "shows": "",
            "because": "" if i == 0 else "__填：上一镜的什么导致这一镜__",   # v2：不再预填可通过的占位
            "new_concept": None,
        })
    return st


# ── 检查 ────────────────────────────────────────────────────────────
def check(story):
    fails, warns, notes = [], [], []
    s = story if isinstance(story, dict) else {}
    try:
        secs = float(s.get("seconds"))
    except Exception:
        fails.append("S0 seconds 缺失或不是数字（无法定预算与时间轴）")
        secs = 0.0

    log = as_text(s.get("logline")).strip()
    claim = as_text(s.get("claim")).strip()
    ak_raw = s.get("audience_knows")
    ak = ak_raw if isinstance(ak_raw, list) else ([ak_raw] if ak_raw else [])
    ak = [as_text(x).strip() for x in ak if as_text(x).strip()]

    # ── S1 一句话论点 ──
    n_log = len(strip_punct(log))
    if n_log < 6 or n_log > 24:
        fails.append(f"S1 logline 需 6–24 字（去标点），当前 {n_log} 字：「{log}」")
    else:
        # 「在」只有作介词/进行体才算动作；存在/现在/所在 不算（v2 的洞）
        pred = re.search(r"了|着|过|把|被|从|向|往|穿过|落|亮|变|出现|看见|听|抬|走|升|散|开|冒出|浮|沉|撞|推|拉|翻|烧|冻|融|照", log)
        pred = pred or re.search(r"(正在|在)[\u4e00-\u9fff]{0,4}(里|上|下|中|外|旁|前|后|边)", log)
        noun_only = re.match(r"^[\u4e00-\u9fff]{2,12}(的[\u4e00-\u9fff]{2,12})?$", strip_punct(log))
        if noun_only and not pred:
            fails.append(f"S1 logline 只是名词短语，没写「发生了什么」：「{log}」")
        elif not pred:
            fails.append(f"S1 logline 没写出事件（缺动作/位移）：「{log}」")

    if len(strip_punct(claim)) < 4:
        fails.append("S1 claim 至少 4 个字：这一支片要回答的一句话是什么？")
    else:
        if re.search(r"(吗|呢|吧)$", claim) or re.search(r"[？?]|是否|为什么|怎么|如何|多少|几个|哪", claim):
            fails.append(f"S1 claim 是问句，不是判断句：「{claim}」（问句放 logline 或开头旁白）")
        elif not re.search(r"因为|所以|让|使|导致|能|会|把|被|是|沿|向|从|越|变|说明|证明|意味着", claim):
            warns.append("S1 claim 像标签而不是判断句（缺 因为/所以/让/是…）")

    if not ak:
        fails.append("S1 audience_knows 为空：开场 1.5 秒内必须交代「这是哪儿、看谁」")
    else:
        short = [x for x in ak if len(strip_punct(x)) < 6]
        if short:
            fails.append(f"S1 audience_knows 每项至少 6 字，太短：{short}")
        vague = [x for x in ak if re.search(r"交代|说明|补充|背景|一些|相关|待定|待补|记得|注意|观众", x)]
        if vague:
            fails.append(f"S1 audience_knows 写成了待办说明，不是具体场景：{vague}")

    beats = [b for b in (s.get("beats") or []) if isinstance(b, dict)]
    if len(beats) < 3:
        fails.append("S2 至少 3 条 beat（起承转合）")
    beats = sorted(beats, key=lambda b: b.get("id") or 0)

    # ── R10 时间轴：正时长、单调、闭合、总覆盖 ──
    if beats and secs > 0:
        try:
            TOL = 0.2
            t0s = [float(b.get("t0")) for b in beats]
            t1s = [float(b.get("t1")) for b in beats]
            if t0s[0] > 0.5:
                fails.append(f"R10 第一条 beat 从 {t0s[0]}s 才开始：开头有空档")
            if abs(t1s[-1] - secs) > 0.5:
                fails.append(f"R10 最后一镜结束于 {t1s[-1]}s，与 {secs:.0f}s 不符")
            cover = 0.0
            for i, (a0, a1) in enumerate(zip(t0s, t1s)):
                if a1 <= a0:
                    fails.append(f"R10 第{beats[i].get('id')}条时长 ≤0（{a0}→{a1}），镜头倒放")
                    continue
                cover += a1 - a0
                if i and t0s[i] < t0s[i - 1] - TOL:
                    fails.append(f"R10 第{beats[i].get('id')}条开始时间早于上一条（顺序乱了）")
                if i:
                    gap = a0 - t1s[i - 1]
                    if gap > TOL:
                        fails.append(f"R10 第{i}/{i+1}条之间有 {gap:.2f}s 空档")
                    if gap < -TOL:
                        warns.append(f"R10 第{i}与{i+1}条重叠 {-gap:.2f}s")
            if cover < secs * 0.85:
                fails.append(f"R10 镜头总时长 {cover:.1f}s 只覆盖 {cover/secs:.0%} 的片长（黑场太多）")
        except Exception:
            fails.append("R10 beat 的 t0/t1 必须是数字")

    # ── S2 逐条 ──
    for b in beats:
        bid = b.get("id")
        who = as_text(b.get("who")).strip()
        act = as_text(b.get("action")).strip()
        shows = as_text(b.get("shows")).strip()
        if not who:
            fails.append(f"S2 第{bid}条没有 who：镜头里谁/什么在动？")
        if not act:
            fails.append(f"S2 第{bid}条没有 action：观众看不到事情发生")
            continue
        cs = clauses(act)
        if len(cs) > 1:
            fails.append(f"S2 第{bid}条 action 里有 {len(cs)} 个分句：「{act}」→ 一镜只演一个动作")
        n_act = len(strip_punct(act))
        if n_act > 22:
            fails.append(f"S2 第{bid}条 action {n_act} 字 > 22，画面装不下")
        if not has_verb_like(act):
            warns.append(f"S2 第{bid}条 action 不像动作（没有变化/位移）：「{act}」")
        if not shows:
            fails.append(f"S2 第{bid}条没有 shows：观众能看见的具体东西是什么？")
        elif re.search(VAGUE, shows) and not re.search(VISUAL, shows):
            fails.append(f"S2 第{bid}条 shows 不可拍：「{shows}」→ 写出可见物与前后变化")
        elif re.search(ABSTRACT, shows) and not re.search(VISUAL, shows):
            warns.append(f"S2 第{bid}条 shows 偏抽象：「{shows}」→ 补一个可见替身")

    # ── S3 因果：占位符/空话/制作口径一律拦；因果词或机制词需与上文有关联 ──
    for i, b in enumerate(beats[1:], start=1):
        bc = as_text(b.get("because")).strip()
        bid = b.get("id")
        core = strip_punct(bc)
        if len(core) < 4:
            fails.append(f"S3 第{bid}条没有 because：它为什么接在上一镜后面？")
            continue
        lead = re.sub(r"^[（(【\[「『\s]+", "", bc)
        if re.match(PLACEHOLDER, lead) or re.match(PLACEHOLDER, core) or re.match(HOLLOW, core):
            fails.append(f"S3 第{bid}条 because 是占位符/空话：「{bc}」→ 写真实因果")
            continue
        if re.search(SELF_HINT, core):
            fails.append(f"S3 第{bid}条 because 里还有脚手架提示词：「{bc}」")
            continue
        if re.search(META_TALK, core):
            fails.append(f"S3 第{bid}条 because 在讲制作/节奏，不是故事里的因果：「{bc}」")
            continue
        prior = " ".join(as_text(p.get("who")) + as_text(p.get("action")) + as_text(p.get("shows"))
                         for p in beats[:i])
        linked = share(bc, prior) >= 1
        causal = bool(re.search(CAUSAL, bc))
        mech = bool(re.search(MECHANISM, bc))
        if not (linked or causal or mech):
            fails.append(f"S3 第{bid}条 because 与前文没有内容关联，也没有因果/机制词：「{bc}」")
        elif not linked and not causal:
            warns.append(f"S3 第{bid}条 because 只靠机制词过关，建议与上文用同一个物象：「{bc}」")

    # ── S4 概念预算：按个计，去重，忽略"无" ──
    concepts = []
    for b in beats:
        concepts += norm_concepts(b.get("new_concept"))
    budget = int(math.ceil(secs / 12.0)) if secs > 0 else 1
    if len(concepts) > budget:
        fails.append(f"S4 新概念 {len(concepts)} 个 > 预算 {budget} 个（{secs:.0f} 秒）：「"
                     + "、".join(concepts) + "」")

    # ── S5 收尾回扣：要有新增实词 + 与本片有锚点 ──
    pay = as_text(s.get("payoff")).strip()
    if len(strip_punct(pay)) < 4:
        fails.append("S5 没有 payoff：最后一镜要回答开头的问题")
    elif claim:
        FILL = r"这句话|这句|就是答案|答案就是|换句话说|也就是说|简单说|总之|记住了|记住|真的"
        pay_core = re.sub(FILL, "", pay)
        C = content_bigrams(claim)
        Pb = content_bigrams(pay_core)
        beats_bg = set()
        for b in beats:
            beats_bg |= content_bigrams(as_text(b.get("who")) + as_text(b.get("action")) + as_text(b.get("shows")))
        new_info = len(Pb - C)
        anchor = len(Pb & (C | beats_bg))
        if anchor == 0:
            fails.append("S5 payoff 与 claim/画面没有共同内容：观众会觉得「没回答」或「跑题了」")
        if new_info < 2:
            fails.append("S5 payoff 相对 claim 没有新信息（只是复述或填充）：补上「所以」那一层")
        if len(Pb & C) and strip_punct(claim) and strip_punct(claim) in strip_punct(pay) and new_info < 4:
            warns.append("S5 payoff 整句照抄 claim：把答案改写成后果/证据")
        if bool(re.search(NEG, strip_punct(claim))) != bool(re.search(NEG, strip_punct(pay))):
            warns.append("S5 claim 与 payoff 的否定极性不一致（一个说不能，一个说能）")

    # ── R7 画面必须有变化（先归一化，句号不算变化）──
    shows_n = [norm_show(b.get("shows")) for b in beats if norm_show(b.get("shows"))]
    if len(shows_n) >= 2 and len(set(shows_n)) == 1:
        fails.append("R7 所有 beat 的 shows 完全相同：画面没有可见变化")

    # ── R8 who 连续性（代词归并；跨物体镜保留上一个人）──
    if beats:
        first = beats[0]
        fw, fs = as_text(first.get("who")), as_text(first.get("shows"))
        if ak and share(fw + fs, " ".join(ak)) == 0:
            warns.append("R8 第一镜的人和物与 audience_knows 没有任何共同词：开场可能没交代清")
        last_person = None
        for b in beats:
            w = as_text(b.get("who")).strip()
            if not w:
                continue
            is_pron = bool(re.fullmatch(r"他|她|它|他们|她们|它们", w))
            is_agent = bool(re.search(AGENT, w)) or is_pron
            if is_pron:
                continue                       # 代词不算换人
            if is_agent and last_person and share(w, last_person) == 0:
                bc = as_text(b.get("because"))
                if not (re.search(CHANGE_CUE, bc) and share(bc, w) >= 1):
                    warns.append(f"R8 第{b.get('id')}条主体从「{last_person}」换成「{w}」，because 没点名交代")
            if is_agent:
                last_person = w

    notes.append(f"骨架 {s.get('spine','?')} · {len(beats)} 条 · {secs:.0f} 秒 · "
                 f"新概念 {len(concepts)}/{budget}")
    return fails, warns, notes


AUDIT_Q = [
    ("这支片在说什么？", "S1 claim"),
    ("画面里主要是什么在动？", "S2 who/action"),
    ("第一幕让你知道这是哪儿吗？", "S1 audience_knows"),
    ("中间那个转折为什么发生？", "S3 because"),
    ("最后回答开头的问题了吗？", "S5 payoff"),
    ("哪一幕你记住了？", "R7 shows"),
]


def audit_text(story):
    lines = [f"# 盲评：{story.get('topic','')}", "",
             f"logline：{as_text(story.get('logline'))}",
             f"claim：{as_text(story.get('claim'))}", "",
             "> 让没看过方案的人看一遍片，逐条问。答不上 → 对应规则没做到。", ""]
    for i, (q, rule) in enumerate(AUDIT_Q, 1):
        lines.append(f"{i}. {q}    （对应 {rule}）")
    lines += ["", "判分：6 条答对 <5 → 不发行。把答案写进 answers JSON 后：",
              "  python scripts/story.py --audit out/story.json --answers out/answers.json"]
    return "\n".join(lines)


def score_answers(fn):
    data = json.load(open(fn, encoding="utf-8-sig"))
    ans = data.get("answers", data if isinstance(data, list) else [])
    ok = 0
    for i, item in enumerate(ans, 1):
        good = bool(item.get("ok")) if isinstance(item, dict) else bool(item)
        ok += 1 if good else 0
        q = AUDIT_Q[i - 1][0] if i <= len(AUDIT_Q) else f"第{i}问"
        print(f"  {'✓' if good else '✗'} {q}")
    print(f"\n答对 {ok}/{len(AUDIT_Q)} → {'可以发行' if ok >= 5 else '不发行：回去补对应 beat'}")
    return 0 if ok >= 5 else 1


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default="")
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--spine", default="auto")
    ap.add_argument("--logline", default="")
    ap.add_argument("--claim", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--check", default="")
    ap.add_argument("--strict", action="store_true", help="建议项也当作不通过")
    ap.add_argument("--audit", default="")
    ap.add_argument("--answers", default="")
    ap.add_argument("--spines", action="store_true")
    a = ap.parse_args()

    if a.spines:
        for k, v in SPINES.items():
            print(f"{k:12s} {v['desc']}  （收束：{v['payoff']}）")
        return 0

    if a.check or a.audit:
        fn = a.check or a.audit
        try:
            story = json.load(open(fn, encoding="utf-8-sig"))
        except FileNotFoundError:
            print(f"读不到文件：{fn}", file=sys.stderr)
            return 2
        except Exception as e:
            print(f"故事文件不是合法 JSON：{e}", file=sys.stderr)
            return 2

        if a.audit:
            print(audit_text(story))
            if a.answers:
                return score_answers(a.answers)
            return 0

        fails, warns, notes = check(story)
        for n in notes:
            print("·", n)
        for w in warns:
            print("△", w)
        for f in fails:
            print("✗", f)
        if fails:
            print(f"\n不通过：{len(fails)} 项硬伤（改完再渲）")
            return 1
        if warns and a.strict:
            print(f"\n不通过（--strict）：{len(warns)} 条建议未处理")
            return 1
        print("\n✓ 叙事契约通过" + (f"（{len(warns)} 条建议）" if warns else ""))
        return 0

    spine = pick_spine(a.topic, a.spine)
    st = skeleton(a.topic, a.seconds, spine, a.logline, a.claim)
    out = json.dumps(st, ensure_ascii=False, indent=1)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
        if os.path.exists(a.out):
            print(f"注意：覆盖已有 {a.out}")
        open(a.out, "w", encoding="utf-8").write(out)
        print(f"骨架 → {a.out}（{spine}，{len(st['beats'])} 条 beat）")
        print("填 logline / claim / audience_knows / payoff / 每条 who+action+shows+because，再 --check")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
