"""分轮原话的语言证据分析。

把分轮听记整理成可比较的观察机会：
- 用上下文把回合区分为孩子主动表达、受提示后的独立表达、直接仿说、
  成人代述和证据不足（处理省略主语的连续回合、转换语言、模仿和可解释词形）；
- 按交际意图归并多语表达，同一短句在不同场景可承担不同意图；
- 重复转抄关联到同一观察机会，只计一次，并标出亲见记录；
- 机会没有某种表达时，分清“给了机会但没有发生”“活动没到这一步”
  和“听写者没有记下来”；
- 更正（amendment）生效后重算结论，复核已约与已完成的游戏；
- 家庭只看授权片段与站点可解释的依据，跨场景关联不泄露其他孩子。

结果只用于安排游戏和与家长沟通，不构成诊断。
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------- 回合五类判断
SPONTANEOUS = "主动表达"
PROMPTED = "受提示后的独立表达"
IMITATION = "直接仿说"
PROXY = "成人代述"
INSUFFICIENT = "证据不足"

# ---------------------------------------------------------------- 机会结果
OUTCOME_EXPRESSED = "有表达"
OUTCOME_ABSENT = "确实给了表达机会但没有发生"
OUTCOME_NOT_REACHED = "活动没到这一步"
OUTCOME_GAP = "听写者没有记下来"
OUTCOME_UNKNOWN = "记录条件不足"

REQUEST_INTENT = "请求物品"
ECHO_INTENT = "模仿回应"

# 跨语言同义形式：粤语“俾我”与普通话“给我”都是向对方要物品，
# 归并到同一交际意图，不另算新机会。
GIVE_ME_FORMS = ("俾我", "给我")

# 站点确认跨场景主动的依据（见 data/资料格式.md）：
# 至少两次独立的主动表达，来自家与站两种场合、两个不同伙伴。
REQUIRED_SETTINGS = ("家", "站点")
REQUIRED_SPONTANEOUS = 2
REQUIRED_PARTNERS = 2

_QUOTED = re.compile(r"[‘「『\"](.+?)[’」』\"]")
_QUESTION = re.compile(r"[？?]|怎么办|为什么|什么|谁|哪|吗|呢")
_STRIP = "。，、！？；：…—～·‘’“”「」『』\"' \t"
_NOT_REACHED = re.compile(r"没轮到|没有轮到|未轮到|提前结束|活动结束")
_NOT_SPOKEN = re.compile(r"未说|没有说|未开口|没开口|未出声")


def normalize(text):
    """去掉首尾标点空白，便于比较词形。"""
    return text.strip(_STRIP)


def _quoted_models(text):
    """成人回合里被引号标出的示范说法，如“可以说‘给我’。”"""
    return [normalize(m) for m in _QUOTED.findall(text) if normalize(m)]


def _is_prompt(text):
    return bool(_QUESTION.search(text))


# ---------------------------------------------------------------- 数据结构
@dataclass
class TurnView:
    index: int
    speaker: str
    text: str
    role: str                      # 铺垫 / 提示 / 示范 / 记录 / 孩子回合 / 他人 / 待定
    category: str | None = None    # 五类判断（仅孩子或待定的回合）
    intent: str | None = None
    note: str = ""


@dataclass
class Opportunity:
    oid: str
    child: str
    records: list                  # 同一机会的全部笔录
    primary: dict                  # 亲见主记录
    duplicates: list               # 重复转抄
    turns: list = field(default_factory=list)   # TurnView，取主记录
    outcome: str = OUTCOME_UNKNOWN
    outcome_note: str = ""

    @property
    def setting(self):
        return self.primary.get("setting", "")

    @property
    def partner(self):
        return self.primary.get("partner", "")

    @property
    def activity(self):
        return self.primary.get("activity", "")

    @property
    def date(self):
        return self.primary.get("date", "")

    @property
    def language(self):
        return self.primary.get("language", "")


@dataclass
class Evidence:
    oid: str
    session: str
    date: str
    setting: str
    partner: str
    language: str
    text: str
    category: str
    intent: str


@dataclass
class Judgment:
    child: str
    intent: str
    spontaneous: list = field(default_factory=list)
    prompted: list = field(default_factory=list)
    imitations: list = field(default_factory=list)
    negatives: list = field(default_factory=list)   # 可比机会中给了机会但未发生
    unusable: list = field(default_factory=list)    # 不可比机会（缺口/未走到/代述）
    met: bool = False
    missing: list = field(default_factory=list)


@dataclass
class Analysis:
    """一次完整分析的结果。"""
    records: dict
    sessions: list
    opportunities: list
    judgments: dict                # child -> Judgment
    amendment_notes: list
    affected: set = field(default_factory=set)     # 更正波及的孩子
    plans: dict = field(default_factory=dict)      # child -> 建议方案列表
    alternatives: dict = field(default_factory=dict)  # child -> 其他候选
    remaining: dict = field(default_factory=dict)  # child -> 本时段补不了的缺口
    reviews: list = field(default_factory=list)    # 已约/已完成复核
    questions: dict = field(default_factory=dict)  # child -> 教师下一步问题


# ---------------------------------------------------------------- 更正
def apply_amendments(sessions, amendments):
    """返回（更正后的 sessions 深拷贝, 更正说明列表, 受影响的孩子）。

    更正只把指定回合改判为“非孩子本人”，原话保留。
    """
    sessions = copy.deepcopy(sessions)
    by_id = {s["id"]: s for s in sessions}
    notes = []
    affected = set()
    for amend in amendments or []:
        who = by_id.get(amend["session"])
        if who is None:
            raise ValueError(f"更正 {amend['id']} 指向不存在的记录 {amend['session']}")
        index = amend["turn"] - amend.get("ordinal_origin", 1)
        if index not in range(len(who["turns"])):
            raise ValueError(f"更正 {amend['id']} 指向 {amend['session']} 不存在的回合")
        turn = who["turns"][index]
        speaker = ""
        match = re.search(r"的是([^。，]+)。?$", amend.get("text", ""))
        if match:
            speaker = match.group(1)
        turn["proxy"] = True
        turn["proxy_who"] = speaker or "他人"
        turn["amendment"] = amend["id"]
        affected.add(who["child"])
        notes.append(
            f"{amend['id']}（{amend.get('date', '日期不详')}）：{amend['session']} 第 "
            f"{amend['turn']} 回合「{turn['text']}」改判为{turn['proxy_who']}所说，"
            f"不再作为 {who['child']} 的表达。原话：{amend.get('text', '')}")
    return sessions, notes, affected


# ---------------------------------------------------------------- 机会归并
def _audio_gaps(session):
    return sum(1 for t in session["turns"] if t.get("audio_missing"))


def group_opportunities(sessions):
    """按 joint 把重复转抄关联到同一观察机会，并选出亲见主记录。

    亲见主记录取回合最完整、听写缺口最少的一份；其余为重复转抄，
    只用于核对，不另计机会。joint 留空表示记录员未能关联，各自独立。
    """
    groups = {}
    for session in sessions:
        key = session.get("joint") or f"未关联:{session['id']}"
        groups.setdefault(key, []).append(session)
    opportunities = []
    for oid in sorted(groups):
        records = sorted(
            groups[oid],
            key=lambda s: (-len(s["turns"]), _audio_gaps(s), s["id"]),
        )
        children = {s["child"] for s in records}
        if len(children) > 1:
            raise ValueError(f"机会 {oid} 的笔录归属了不同孩子：{sorted(children)}")
        primary, duplicates = records[0], records[1:]
        opp = Opportunity(oid=oid, child=records[0]["child"],
                          records=records, primary=primary, duplicates=duplicates)
        _check_duplicates(opp)
        opportunities.append(opp)
    return opportunities


def _check_duplicates(opp):
    """核对转抄与主记录的孩子原话是否一致。"""
    main = [t["text"] for t in opp.primary["turns"] if t["speaker"] == opp.child]
    for dup in opp.duplicates:
        other = [t["text"] for t in dup["turns"] if t["speaker"] == opp.child]
        if other and other != main[: len(other)]:
            dup["conflict"] = True


# ---------------------------------------------------------------- 回合分类
def _intent_of(category, text):
    """按交际意图归并；同一短句在不同场景可承担不同意图。"""
    if category == IMITATION:
        return ECHO_INTENT
    if category in (SPONTANEOUS, PROMPTED):
        if any(form in text for form in GIVE_ME_FORMS):
            return REQUEST_INTENT
        return "其他意图"
    if category == INSUFFICIENT and any(form in text for form in GIVE_ME_FORMS):
        return REQUEST_INTENT + "（存疑）"
    return None


def classify_opportunity(opp):
    """用上下文对主记录逐回合分类。"""
    child = opp.child
    views = []
    context_role = "铺垫"
    context_text = ""
    context_models = []
    for index, turn in enumerate(opp.primary["turns"]):
        speaker, text = turn["speaker"], turn["text"]
        if turn.get("proxy"):
            views.append(TurnView(
                index, speaker, text, role="他人", category=PROXY,
                note=f"非孩子本人：{turn.get('proxy_who', '他人')}所说"
                     f"（更正 {turn.get('amendment', '')}），不作 {child} 的表达"))
            context_role, context_text, context_models = "铺垫", text, []
            continue
        if speaker == "记录员":
            views.append(TurnView(index, speaker, text, role="记录"))
            continue
        if speaker == "不明":
            views.append(TurnView(
                index, speaker, text, role="待定", category=INSUFFICIENT,
                intent=_intent_of(INSUFFICIENT, text),
                note="听记者未能确认说话人，不能记到孩子名下"))
            context_role, context_text, context_models = "铺垫", text, []
            continue
        if speaker != child:
            models = _quoted_models(text)
            if models:
                role = "示范"
            elif _is_prompt(text):
                role = "提示"
            else:
                role = "铺垫"
            views.append(TurnView(index, speaker, text, role=role))
            context_role, context_text, context_models = role, text, models
            continue
        # 孩子回合：省略主语的短句借助上文（铺垫/提示/示范）判断
        category, note = SPONTANEOUS, ""
        plain = normalize(text)
        if turn.get("audio_missing"):
            category, note = INSUFFICIENT, "听写缺口，原话未录全"
        elif context_models and any(m and (m in plain or plain in m)
                                    for m in context_models):
            category = IMITATION
            note = f"紧跟成人示范「{context_models[0]}」，是照念不是自己的话"
        elif context_role == "提示":
            category = PROMPTED
            note = f"成人先问「{context_text}」，孩子用自己的话回应"
        elif context_role == "示范":
            category = PROMPTED
            note = "成人给了示范，孩子未照念但受提示"
        if category != INSUFFICIENT and not any(f in text for f in GIVE_ME_FORMS) \
                and len(plain) <= 3:
            extra = f"可解释词形「{text}」，需结合上文「{context_text}」理解"
            note = f"{note}；{extra}" if note else extra
        views.append(TurnView(
            index, speaker, text, role="孩子回合", category=category,
            intent=_intent_of(category, text), note=note))
        context_role, context_text, context_models = "铺垫", text, []
    opp.turns = views
    opp.outcome, opp.outcome_note = _outcome_of(opp)
    return opp


def _outcome_of(opp):
    """机会没有目标表达时，分清三种情况。"""
    child_turns = [v for v in opp.turns if v.role == "孩子回合"]
    if any(v.category in (SPONTANEOUS, PROMPTED, IMITATION) for v in child_turns):
        return OUTCOME_EXPRESSED, ""
    if any(v.category == INSUFFICIENT for v in child_turns) or \
            any(v.role == "待定" for v in opp.turns):
        return OUTCOME_GAP, "关键回合听写不全或说话人不明，不能算孩子没有表达"
    notes = "；".join(v.text for v in opp.turns if v.role == "记录")
    if _NOT_REACHED.search(notes):
        return OUTCOME_NOT_REACHED, "活动提前结束，没走到需要表达的那一步"
    if _NOT_SPOKEN.search(notes):
        return OUTCOME_ABSENT, "伙伴给了等待机会，孩子当时没有表达"
    if any(v.category == PROXY for v in opp.turns):
        return OUTCOME_GAP, "唯一相关回合已更正为他人所说"
    return OUTCOME_UNKNOWN, "记录条件不足，无法判断"


def build_opportunities(sessions):
    return [classify_opportunity(opp) for opp in group_opportunities(sessions)]


# ---------------------------------------------------------------- 跨场景判断
def judge_child(opportunities, child, intent=REQUEST_INTENT):
    """比较可比的观察机会，判断是否已有跨场景主动表达的依据。"""
    judgment = Judgment(child=child, intent=intent)
    for opp in opportunities:
        if opp.child != child:
            continue
        expressed = [v for v in opp.turns
                     if v.role == "孩子回合" and v.intent == intent]
        if expressed:
            first = expressed[0]
            evidence = Evidence(opp.oid, opp.primary["id"], opp.date, opp.setting,
                                opp.partner, opp.language, first.text,
                                first.category, intent)
            if first.category == SPONTANEOUS:
                judgment.spontaneous.append(evidence)
            elif first.category == PROMPTED:
                judgment.prompted.append(evidence)
            elif first.category == IMITATION:
                judgment.imitations.append(evidence)
            continue
        if opp.outcome == OUTCOME_ABSENT:
            judgment.negatives.append(opp)
        elif opp.outcome in (OUTCOME_NOT_REACHED, OUTCOME_GAP, OUTCOME_UNKNOWN):
            judgment.unusable.append(opp)
    settings = {e.setting for e in judgment.spontaneous}
    partners = {e.partner for e in judgment.spontaneous}
    judgment.met = (len(judgment.spontaneous) >= REQUIRED_SPONTANEOUS
                    and all(s in settings for s in REQUIRED_SETTINGS)
                    and len(partners) >= REQUIRED_PARTNERS)
    if len(judgment.spontaneous) < REQUIRED_SPONTANEOUS:
        judgment.missing.append(
            f"还差 {REQUIRED_SPONTANEOUS - len(judgment.spontaneous)} 次独立的主动表达")
    for setting in REQUIRED_SETTINGS:
        if setting not in settings:
            judgment.missing.append(f"缺{setting}场合的主动表达")
    if len(partners) < REQUIRED_PARTNERS:
        judgment.missing.append("需要第二个不同伙伴面前的主动表达")
    return judgment


# ---------------------------------------------------------------- 下一步安排
def _family_partners(sessions, child):
    """为这个孩子做过家庭记录的家庭成员。"""
    return {s["observer"] for s in sessions
            if s["child"] == child and str(s.get("observer", "")).startswith("家庭")}


def plan_slots(analysis, child):
    """用剩余时段优先补最影响判断的缺口。

    考虑谁会哪种语言、能使用什么活动、哪些伙伴已经参与过；
    家庭伙伴只能为自家孩子做家庭场合记录；
    一个活动可同时补足关联缺口，但同一回合只算一次独立证据。
    """
    judgment = analysis.judgments[child]
    partners = {p["id"]: p for p in analysis.records.get("partners", [])}
    family_ok = _family_partners(analysis.sessions, child)
    have_partners = {e.partner for e in judgment.spontaneous}
    have_settings = {e.setting for e in judgment.spontaneous}

    def fills_for(partner_id, setting):
        fills = []
        if setting not in have_settings:
            fills.append(f"{setting}场合")
        if partner_id not in have_partners:
            fills.append("第二个伙伴")
        return fills

    plans, alternatives = [], []
    for slot in analysis.records.get("schedule", []):
        candidates = []
        for activity in slot.get("activities", []):
            for partner_id in slot.get("partners", []):
                partner = partners.get(partner_id)
                if partner is None or activity not in partner.get("activities", []):
                    continue
                if partner_id.startswith("家庭"):
                    if partner_id not in family_ok:
                        continue  # 家庭伙伴只记录自家孩子
                    setting = "家"
                else:
                    setting = "站点"
                candidates.append({
                    "slot": slot["id"], "date": slot.get("date", ""),
                    "activity": activity, "partner": partner_id,
                    "setting": setting,
                    "languages": list(partner.get("languages", [])),
                    "fills": fills_for(partner_id, setting),
                })
        candidates.sort(key=lambda c: (-len(c["fills"]), c["partner"]))
        for _ in range(slot.get("slots", 0)):
            if not candidates:
                break
            best = candidates.pop(0)
            plans.append(best)
            have_settings |= {best["setting"]}
            have_partners |= {best["partner"]}
            for rest in candidates:  # 剩余候选按新缺口重排
                rest["fills"] = fills_for(rest["partner"], rest["setting"])
            candidates.sort(key=lambda c: (-len(c["fills"]), c["partner"]))
        alternatives = candidates
    return plans, alternatives


# ---------------------------------------------------------------- 已约/已完成复核
def evaluate_bookings(analysis, plans_by_child):
    """更正生效后复核：已约的还值不值得做，已完成的保留当时条件重判。"""
    by_session = {}
    for opp in analysis.opportunities:
        for rec in opp.records:
            by_session[rec["id"]] = opp
    planned = {(p["activity"], p["partner"])
               for plans in plans_by_child.values() for p in plans}
    reviews = []
    for booking in analysis.records.get("bookings", []):
        evidences = [by_session[s] for s in booking.get("evidence", []) if s in by_session]
        if booking.get("state") == "已完成":
            parts = [
                f"{opp.primary['id']}（{opp.date} {opp.setting}·{opp.activity}·"
                f"{opp.partner}·{opp.language}）：{opp.outcome}"
                for opp in evidences
            ]
            reviews.append({
                "id": booking["id"], "state": "已完成", "keep": True,
                "verdict": "保留当时条件，重新判断能否作为独立证据",
                "detail": "；".join(parts) or "原证据已不在记录中",
            })
            continue
        fills_gap = (booking["activity"], booking["partner"]) in planned
        usable = [o for o in evidences
                  if any(v.role == "孩子回合" and v.category in (SPONTANEOUS, PROMPTED)
                         for v in o.turns)]
        if fills_gap:
            verdict = "值得做：正对当前最影响判断的缺口"
        elif usable:
            verdict = "可做：原有证据仍有效"
        else:
            verdict = "暂缓：原依据已不成立，且不在当前关键缺口上"
        reviews.append({
            "id": booking["id"], "state": booking.get("state", "已约"),
            "verdict": verdict, "keep": fills_gap or bool(usable),
            "detail": f"{booking['activity']}×{booking['partner']}；"
                      f"原证据 {', '.join(booking.get('evidence', [])) or '无'}，"
                      f"更正后仍可用 {len(usable)} 条",
        })
    return reviews


# ---------------------------------------------------------------- 教师下一步问题
def teacher_questions(judgment, opportunities, plans):
    """缺材料时也要能给老师可执行的下一次观察问题。"""
    questions = []
    for plan in plans:
        lang = "、".join(plan["languages"]) or "孩子会的语言"
        questions.append(
            f"{plan['date']} {plan['activity']}（{plan['partner']}，{plan['setting']}，{lang}）："
            f"先摆好材料看向孩子，等约 10 秒再开口；孩子有没有主动说出要东西？"
            f"原话是什么、哪种语言？（粤语“俾我”和普通话“给我”算同一意图）")
        questions.append(
            "如果问了“缺一块怎么办？”孩子才说，记下问之前孩子有没有自己开口；"
            "照着成人示范念的单独标出，不算主动。")
    if any(o.outcome == OUTCOME_GAP for o in opportunities):
        questions.append(
            "每句标清是谁说的；哥哥等别人在场时尤其注意，听不清就标 audio_missing，"
            "不要猜原话。")
    if any(o.outcome == OUTCOME_NOT_REACHED for o in opportunities):
        questions.append(
            "活动要走到需要表达的那一步再结束；若提前结束，记下停在哪一步。")
    if not questions:
        questions.append("按约定活动观察孩子是否主动表达，并逐句记录说话人。")
    return questions


# ---------------------------------------------------------------- 汇总分析
def analyze(records, amend=True):
    """对资料包做一次完整分析。amend=False 表示更正前的状态。"""
    if amend:
        sessions, notes, affected = apply_amendments(records["sessions"],
                                                     records.get("amendment"))
    else:
        sessions, notes, affected = copy.deepcopy(records["sessions"]), [], set()
    opportunities = build_opportunities(sessions)
    children = sorted({s["child"] for s in sessions})
    judgments = {child: judge_child(opportunities, child) for child in children}
    analysis = Analysis(records=records, sessions=sessions,
                        opportunities=opportunities, judgments=judgments,
                        amendment_notes=notes, affected=affected)
    for child in children:
        if judgments[child].met:
            analysis.plans[child] = []
            analysis.alternatives[child] = []
            continue
        plans, alternatives = plan_slots(analysis, child)
        analysis.plans[child] = plans
        analysis.alternatives[child] = alternatives
        own = [o for o in opportunities if o.child == child]
        analysis.questions[child] = teacher_questions(judgments[child], own, plans)
        settings = {e.setting for e in judgments[child].spontaneous}
        settings |= {p["setting"] for p in plans}
        partners = {e.partner for e in judgments[child].spontaneous}
        partners |= {p["partner"] for p in plans}
        left = [f"{s}场合" for s in REQUIRED_SETTINGS if s not in settings]
        if len(partners) < REQUIRED_PARTNERS:
            left.append("第二个伙伴")
        if left:
            analysis.remaining[child] = left
    analysis.reviews = evaluate_bookings(analysis, analysis.plans)
    return analysis


# ---------------------------------------------------------------- 站点报告
def _format_turn(view):
    head = f"    {view.index + 1}. {view.speaker}：{view.text}"
    if view.category:
        tail = f"　→ {view.category}"
        if view.intent:
            tail += f"（意图：{view.intent}）"
    else:
        tail = f"　→ {view.role}"
    if view.note:
        tail += f"；{view.note}"
    return head + tail


def _judgment_lines(judgment, indent="  "):
    lines = [f"{indent}孩子 {judgment.child}，意图「{judgment.intent}」"]
    settings = "、".join(sorted({e.setting for e in judgment.spontaneous})) or "无"
    partners = "、".join(sorted({e.partner for e in judgment.spontaneous})) or "无"
    lines.append(f"{indent}独立主动表达 {len(judgment.spontaneous)} 次"
                 f"（场合 {settings}；伙伴 {partners}）")
    if judgment.prompted:
        lines.append(f"{indent}另有受提示后的独立表达 {len(judgment.prompted)} 次，"
                     "提示强度不同，不计入主动。")
    if judgment.imitations:
        lines.append(f"{indent}直接仿说 {len(judgment.imitations)} 次，不作独立证据。")
    if judgment.negatives:
        lines.append(f"{indent}可比机会中给了机会但没有发生："
                     + "、".join(o.oid for o in judgment.negatives))
    if judgment.unusable:
        lines.append(f"{indent}不能作数的机会（缺口不算没有能力）："
                     + "、".join(f"{o.oid}（{o.outcome}）" for o in judgment.unusable))
    lines.append(f"{indent}结论：" + ("已有跨场景主动表达的依据，可以向家庭确认。"
                                     if judgment.met else
                                     "还没有跨场景主动表达的依据。"))
    if judgment.missing:
        lines.append(f"{indent}缺口：" + "；".join(judgment.missing))
    return lines


def station_report(before, after):
    """站点完整视图：机会、分类、归并、判断、更正影响与下一步。"""
    lines = ["站点完整报告", "结果只用于安排游戏和与家庭沟通，不构成诊断。", ""]
    section = 0

    def head(title):
        nonlocal section
        section += 1
        lines.append(f"{_SECTION_NO[section]}、{title}")

    head("观察机会（重复转抄只计一次，同一回合不重复算证据）")
    for opp in after.opportunities:
        dups = "、".join(d["id"] for d in opp.duplicates)
        dup_note = f"；重复转抄 {dups} 不计入" if dups else ""
        conflict = "；⚠ 转抄与主记录不一致" if any(
            d.get("conflict") for d in opp.duplicates) else ""
        lines.append(
            f"  机会 {opp.oid}｜{opp.date}｜{opp.child}｜{opp.setting}·{opp.activity}｜"
            f"伙伴 {opp.partner}｜{opp.language}｜亲见记录 {opp.primary['id']}"
            f"（{opp.primary['observer']}）{dup_note}{conflict}")
        for view in opp.turns:
            lines.append(_format_turn(view))
        if opp.outcome != OUTCOME_EXPRESSED:
            note = f"（{opp.outcome_note}）" if opp.outcome_note else ""
            lines.append(f"    机会结果：{opp.outcome}{note}")
    lines.append("")
    head("按交际意图归并（多语同形不另计机会，同一短句可承担不同意图）")
    for judgment in after.judgments.values():
        for ev in judgment.spontaneous + judgment.prompted + judgment.imitations:
            lines.append(f"  [{ev.intent}] {judgment.child}｜{ev.date} {ev.setting}·"
                         f"{ev.partner}·{ev.language} 「{ev.text}」→ {ev.category}"
                         f"（机会 {ev.oid}）")
    lines.append("")
    head("跨场景主动判断（更正后）")
    for judgment in after.judgments.values():
        lines.extend(_judgment_lines(judgment))
    if after.amendment_notes:
        lines.append("")
        head("更正带来的影响")
        for note in after.amendment_notes:
            lines.append(f"  - {note}")
        for child in sorted(after.affected):
            judgment = after.judgments[child]
            old = before.judgments.get(child)
            if old is None:
                continue
            if old.met != judgment.met or len(old.spontaneous) != len(judgment.spontaneous):
                lines.append(f"  {child} 结论更正：更正前独立主动 {len(old.spontaneous)} 次"
                             f"（{'达标' if old.met else '未达标'}）→ 更正后 "
                             f"{len(judgment.spontaneous)} 次"
                             f"（{'达标' if judgment.met else '未达标'}）。")
            else:
                lines.append(f"  {child} 结论维持未达标，但家场合那次“待确认”"
                             "已确定为他人所说，不用再等重听，直接安排重新观察。")
    lines.append("")
    head("已约与已完成游戏复核")
    for review in after.reviews:
        lines.append(f"  {review['id']}（{review['state']}）：{review['verdict']}")
        lines.append(f"      {review['detail']}")
    lines.append("")
    head("下一步安排（剩余时段优先补最影响判断的缺口）")
    any_plan = False
    for child, plans in after.plans.items():
        if not plans:
            continue
        any_plan = True
        for plan in plans:
            fills = "、".join(plan["fills"]) or "巩固已有证据"
            lines.append(f"  {child}：{plan['date']}「{plan['activity']}」× {plan['partner']}"
                         f"（{plan['setting']}，语言 {'、'.join(plan['languages'])}）"
                         f"——同时补足：{fills}")
        for alt in after.alternatives.get(child, []):
            fills = "、".join(alt["fills"]) or "不补当前缺口"
            lines.append(f"    备选：「{alt['activity']}」× {alt['partner']}"
                         f"（{alt['setting']}）——{fills}")
        if after.remaining.get(child):
            lines.append(f"    本时段补不了：{'、'.join(after.remaining[child])}"
                         "（没有可行的人×活动组合，需再约时段）")
        lines.append("    注意：同一回合只算一次独立证据；“俾我/给我”是同一意图，"
                     "不另计机会。")
    if not any_plan:
        lines.append("  当前没有需要补的缺口。")
    lines.append("")
    head("给老师的一次观察问题（缺材料也可执行）")
    for child, questions in after.questions.items():
        for question in questions:
            lines.append(f"  [{child}] {question}")
    return "\n".join(lines)


_SECTION_NO = "零一二三四五六七八九十"


# ---------------------------------------------------------------- 家庭可见视图
def family_view(analysis, viewer):
    """家庭只看授权片段和站点可解释的依据，不泄露其他孩子。"""
    records = analysis.records
    allowed = {a["session"] for a in records.get("access", [])
               if viewer in a.get("viewers", [])}
    by_id = {s["id"]: s for s in analysis.sessions}
    own = [by_id[s] for s in sorted(allowed) if s in by_id]
    children = {s["child"] for s in own}
    lines = [f"家庭可见视图（{viewer}）", "结果只用于安排游戏和沟通，不构成诊断。", ""]
    lines.append("一、授权可见的原始片段")
    if not own:
        lines.append("（没有授权可见的片段。）")
    for session in own:
        lines.append(f"- {session['id']} {session['date']} {session['setting']}·"
                     f"{session['activity']}（伙伴 {session['partner']}，"
                     f"{session['language']}）")
        for turn in session["turns"]:
            extra = ""
            if turn.get("proxy"):
                extra = f"　※ 已更正：这句是{turn.get('proxy_who', '他人')}说的，不算孩子的"
            elif turn.get("audio_missing"):
                extra = "　※ 这段没录全"
            lines.append(f"    {turn['speaker']}：{turn['text']}{extra}")
    lines.append("")
    lines.append("二、站点可以向家庭解释的依据")
    explained = False
    for child in sorted(children):
        judgment = analysis.judgments.get(child)
        if judgment is None:
            continue
        explained = True
        for ev in judgment.spontaneous + judgment.prompted:
            if ev.session in allowed:
                wording = "主动" if ev.category == SPONTANEOUS else "在大人提示后自己"
                lines.append(f"- {ev.date} {ev.setting}：孩子{wording}说了"
                             f"「{ev.text}」（伙伴 {ev.partner}）。")
        for opp in judgment.negatives + judgment.unusable:
            if opp.primary["id"] in allowed:
                lines.append(f"- {opp.date} {opp.setting}：这次没能作为依据"
                             f"（{opp.outcome}）。")
        if judgment.met:
            lines.append("- 依据已够：孩子在家和站点、不同伙伴面前都主动要过东西。")
        else:
            lines.append(f"- 目前还不能说孩子已经跨场景主动："
                         f"{'；'.join(judgment.missing)}。")
        for plan in analysis.plans.get(child, []):
            lines.append(f"- 下次安排：{plan['date']} 请 {plan['partner']} 在"
                         f"{plan['setting']}做「{plan['activity']}」，"
                         "先等孩子自己开口，再回应。")
    if not explained:
        lines.append("（没有可向该家庭说明的本站判断。）")
    return "\n".join(lines)
