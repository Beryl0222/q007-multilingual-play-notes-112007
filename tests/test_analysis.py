"""语言证据分析的行为核对。"""

from pathlib import Path
import unittest

from inspect_records import load_records
import speech_evidence as se

DATA = Path(__file__).resolve().parents[1] / "data" / "records.json"


def analyze_sessions(sessions):
    """用最小资料包分析给定 sessions。"""
    records = {"sessions": sessions, "amendment": [], "schedule": [],
               "partners": [], "bookings": [], "access": []}
    return se.analyze(records)


class AnalysisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = load_records(DATA)
        cls.before = se.analyze(cls.records, amend=False)
        cls.after = se.analyze(cls.records, amend=True)

    def opp(self, analysis, oid):
        return next(o for o in analysis.opportunities if o.oid == oid)

    def test_duplicate_transcriptions_merge_into_one_opportunity(self):
        # 不同人重复转抄同一游戏片段 → 同一机会，保留亲见记录
        o1 = self.opp(self.after, "O1")
        self.assertEqual(o1.primary["id"], "S1")
        self.assertEqual([d["id"] for d in o1.duplicates], ["S2"])
        self.assertEqual(len(self.after.opportunities), 6)

    def test_turn_classification(self):
        # 主动表达：成人只做情境铺垫，孩子自己开口
        o1 = self.opp(self.after, "O1")
        self.assertEqual(o1.turns[1].category, se.SPONTANEOUS)
        self.assertEqual(o1.turns[1].intent, se.REQUEST_INTENT)
        # 直接仿说：紧跟成人示范照念
        o3 = self.opp(self.after, "O3")
        self.assertEqual(o3.turns[1].category, se.IMITATION)
        self.assertEqual(o3.turns[1].intent, se.ECHO_INTENT)
        # 更正后：哥哥替答 → 成人代述；听写缺口 → 证据不足
        o2 = self.opp(self.after, "O2")
        self.assertEqual(o2.turns[1].category, se.PROXY)
        self.assertEqual(o2.turns[2].category, se.INSUFFICIENT)
        # 更正前：说话人不明 → 证据不足
        o2_before = self.opp(self.before, "O2")
        self.assertEqual(o2_before.turns[1].category, se.INSUFFICIENT)

    def test_absence_outcomes_are_distinguished(self):
        # 活动没到这一步 / 给了机会但没有发生 / 听写者没有记下来
        self.assertEqual(self.opp(self.after, "O4").outcome, se.OUTCOME_NOT_REACHED)
        self.assertEqual(self.opp(self.after, "O5").outcome, se.OUTCOME_ABSENT)
        self.assertEqual(self.opp(self.after, "O2").outcome, se.OUTCOME_GAP)

    def test_intent_merge_and_scenario_dependence(self):
        # 粤语“俾我”与普通话“给我”归并到同一交际意图
        self.assertEqual(se._intent_of(se.SPONTANEOUS, "俾我红嗰枝。"), se.REQUEST_INTENT)
        self.assertEqual(se._intent_of(se.SPONTANEOUS, "给我那块。"), se.REQUEST_INTENT)
        # 同一短句在仿说场景承担不同意图
        self.assertEqual(se._intent_of(se.IMITATION, "给我。"), se.ECHO_INTENT)

    def test_judgment_after_amendment(self):
        judgment = self.after.judgments["K17"]
        self.assertFalse(judgment.met)
        self.assertEqual(len(judgment.spontaneous), 1)
        self.assertEqual([o.oid for o in judgment.negatives], ["O5"])
        self.assertEqual({o.oid for o in judgment.unusable}, {"O2", "O4"})
        self.assertTrue(any("家" in m for m in judgment.missing))

    def test_same_turn_not_counted_twice(self):
        # S1 与 S2 是同一回合的两份转抄，只算一次独立证据
        judgment = self.after.judgments["K17"]
        self.assertEqual(len(judgment.spontaneous), 1)

    def test_plan_fills_most_critical_gap_first(self):
        # 只剩一个时段：选 拼画×家庭芬，同时补家场合与第二个伙伴
        plans = self.after.plans["K17"]
        self.assertEqual(len(plans), 1)
        plan = plans[0]
        self.assertEqual((plan["activity"], plan["partner"]), ("拼画", "家庭芬"))
        self.assertEqual(plan["setting"], "家")
        self.assertIn("家场合", plan["fills"])
        self.assertIn("第二个伙伴", plan["fills"])
        # 候选尊重伙伴的语言与活动限制（家庭芬只会普通话、只能做拼画）
        combos = {(c["activity"], c["partner"])
                  for c in plans + self.after.alternatives["K17"]}
        self.assertNotIn(("借蜡笔", "家庭芬"), combos)
        self.assertNotIn(("换绘本", "家庭芬"), combos)

    def test_family_partner_only_records_own_child(self):
        # 家庭芬不为 K18 做家庭场合记录；K18 的家场合缺口如实保留
        combos = {(c["activity"], c["partner"], c["setting"])
                  for c in self.after.plans["K18"] + self.after.alternatives["K18"]}
        self.assertNotIn(("拼画", "家庭芬", "家"), combos)
        self.assertIn("家场合", self.after.remaining["K18"])

    def test_booking_reviews(self):
        reviews = {r["id"]: r for r in self.after.reviews}
        # 已约的 B1 正对关键缺口，值得做
        self.assertTrue(reviews["B1"]["keep"])
        self.assertIn("值得做", reviews["B1"]["verdict"])
        # 已完成的 B2 保留当时条件，重判后仍是独立的“给了机会但没有发生”
        self.assertIn("保留当时条件", reviews["B2"]["verdict"])
        self.assertIn(se.OUTCOME_ABSENT, reviews["B2"]["detail"])

    def test_family_view_access_control(self):
        view = se.family_view(self.after, "家庭芬")
        self.assertIn("俾我红嗰枝", view)          # 授权片段可见
        self.assertIn("哥哥", view)                # 更正依据可解释
        for leaked in ("K18", "家庭何", "把两册摆到桌上", "可以说"):
            self.assertNotIn(leaked, view)         # 其他孩子与未授权原话不可见
        other = se.family_view(self.after, "家庭何")
        self.assertIn("给我那块", other)
        self.assertNotIn("K17", other)
        self.assertNotIn("俾我", other)

    def test_teacher_questions_executable_despite_gaps(self):
        questions = self.after.questions["K17"]
        self.assertTrue(questions)
        self.assertTrue(any("audio_missing" in q for q in questions))
        self.assertTrue(any("拼画" in q for q in questions))

    def test_station_report_renders(self):
        report = se.station_report(self.before, self.after)
        for section in ("观察机会", "交际意图", "跨场景主动判断", "更正带来的影响",
                        "已约与已完成", "下一步安排", "观察问题"):
            self.assertIn(section, report)


class SyntheticTest(unittest.TestCase):
    def test_synonyms_in_one_opportunity_count_once(self):
        # 同一机会里“俾我”“给我”都出现，归并后不另计新机会
        analysis = analyze_sessions([{
            "id": "X1", "joint": "OX", "child": "K1", "observer": "站点明",
            "partner": "阿蓝", "date": "2026-10-01", "setting": "站点",
            "activity": "借蜡笔", "language": "粤语",
            "turns": [
                {"speaker": "阿蓝", "text": "这支我先收起。"},
                {"speaker": "K1", "text": "俾我红嗰枝。"},
                {"speaker": "K1", "text": "给我蓝的。"},
            ],
        }])
        self.assertEqual(len(analysis.judgments["K1"].spontaneous), 1)

    def test_prompted_independent_expression(self):
        # 成人提问但无词形示范，孩子用自己的话回应 → 受提示后的独立表达
        analysis = analyze_sessions([{
            "id": "Y1", "joint": "", "child": "K1", "observer": "家庭芬",
            "partner": "家庭芬", "date": "2026-10-02", "setting": "家",
            "activity": "拼画", "language": "普通话",
            "turns": [
                {"speaker": "家庭芬", "text": "缺一块怎么办？"},
                {"speaker": "K1", "text": "给我那块。"},
            ],
        }])
        turn = analysis.opportunities[0].turns[1]
        self.assertEqual(turn.category, se.PROMPTED)
        self.assertEqual(turn.intent, se.REQUEST_INTENT)
        # 受提示的独立表达不计入“主动”，结论仍不达标
        judgment = analysis.judgments["K1"]
        self.assertEqual(len(judgment.spontaneous), 0)
        self.assertEqual(len(judgment.prompted), 1)
        self.assertFalse(judgment.met)

    def test_empty_joint_stays_unlinked(self):
        # joint 留空表示记录员未能关联，各自独立计机会
        analysis = analyze_sessions([
            {"id": "Z1", "joint": "", "child": "K1", "observer": "站点明",
             "partner": "阿蓝", "date": "2026-10-01", "setting": "站点",
             "activity": "借蜡笔", "language": "粤语",
             "turns": [{"speaker": "K1", "text": "俾我。"}]},
            {"id": "Z2", "joint": "", "child": "K1", "observer": "家庭芬",
             "partner": "阿蓝", "date": "2026-10-01", "setting": "站点",
             "activity": "借蜡笔", "language": "粤语",
             "turns": [{"speaker": "K1", "text": "俾我。"}]},
        ])
        self.assertEqual(len(analysis.opportunities), 2)


if __name__ == "__main__":
    unittest.main()
