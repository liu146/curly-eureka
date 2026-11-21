# -*- coding: utf-8 -*-
"""规划器测试：日期解析、城市抽取、意图识别。"""
from __future__ import annotations

import unittest
from datetime import date

from src.agent import planner
from src.config import load_config

TODAY = date(2026, 11, 21)  # 周六


class TestResolveDate(unittest.TestCase):
    def test_relative_days(self):
        self.assertEqual(planner.resolve_date("今天", TODAY)[0], TODAY)
        self.assertEqual(planner.resolve_date("明天", TODAY)[0], date(2026, 11, 22))
        self.assertEqual(planner.resolve_date("后天", TODAY)[0], date(2026, 11, 23))
        self.assertEqual(planner.resolve_date("大后天", TODAY)[0], date(2026, 11, 24))

    def test_next_week(self):
        self.assertEqual(planner.resolve_date("下周三", TODAY)[0], date(2026, 11, 25))
        self.assertEqual(planner.resolve_date("下周一", TODAY)[0], date(2026, 11, 23))

    def test_weekend(self):
        target, label, within, weekend_only = planner.resolve_date("这周末", TODAY)
        self.assertEqual(target, date(2026, 11, 21))
        self.assertTrue(weekend_only)
        self.assertEqual(within, 2)

    def test_span(self):
        target, label, within, _ = planner.resolve_date("未来三天", TODAY)
        self.assertIsNone(target)
        self.assertEqual(within, 3)

    def test_explicit_date(self):
        target, _, within, _ = planner.resolve_date("11月24日", TODAY)
        self.assertEqual(target, date(2026, 11, 24))

    def test_no_date(self):
        target, _, within, _ = planner.resolve_date("天气怎么样", TODAY)
        self.assertIsNone(target)
        self.assertEqual(within, 7)


class TestSlots(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config()

    def test_city_extraction(self):
        self.assertEqual(planner.extract_cities("上海和杭州哪个好", self.cfg), ["上海", "杭州"])
        self.assertEqual(planner.extract_cities("北京天气", self.cfg), ["北京"])
        self.assertEqual(planner.extract_cities("今天天气", self.cfg), [])

    def test_intents(self):
        self.assertIn("rain", planner.detect_intents("明天要带伞吗"))
        self.assertIn("packing", planner.detect_intents("下周三穿什么"))
        self.assertIn("compare", planner.detect_intents("上海和杭州哪个更适合"))
        self.assertIn("trend", planner.detect_intents("今年夏天比去年热吗"))
        self.assertIn("brief", planner.detect_intents("生成一份出行简报"))
        self.assertIn("best_day", planner.detect_intents("哪天最适合出去玩"))

    def test_plan_default_city(self):
        plan = planner.make_plan("明天要带伞吗", self.cfg, today=TODAY)
        self.assertEqual(plan.slots.cities, ["北京"])
        self.assertTrue(plan.slots.assumed_city)

    def test_plan_memory_city(self):
        plan = planner.make_plan("明天要带伞吗", self.cfg, today=TODAY, memory_city="上海")
        self.assertEqual(plan.slots.cities, ["上海"])

    def test_plan_tools(self):
        plan = planner.make_plan("北京这周末适合出去玩吗，要带伞吗", self.cfg, today=TODAY)
        tools = [s.tool for s in plan.steps]
        self.assertIn("get_forecast", tools)
        self.assertIn("best_day", tools)


if __name__ == "__main__":
    unittest.main()
