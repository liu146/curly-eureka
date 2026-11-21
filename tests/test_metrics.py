# -*- coding: utf-8 -*-
"""出行指数与统计指标单元测试。"""
from __future__ import annotations

import unittest

import pandas as pd

from src.analysis import metrics


class TestTravelScore(unittest.TestCase):
    def test_ideal_weather_scores_high(self):
        score, grade, reasons = metrics.travel_score(24, 16, "晴", "1-3级")
        self.assertGreaterEqual(score, 85)
        self.assertIn(grade, ("A", "B"))
        self.assertTrue(reasons)

    def test_rain_penalised(self):
        dry, _, _ = metrics.travel_score(24, 16, "晴", "1-3级")
        wet, _, reasons = metrics.travel_score(24, 16, "中雨", "1-3级")
        self.assertLess(wet, dry)
        self.assertTrue(any("降水" in r for r in reasons))

    def test_cold_penalised(self):
        score, _, reasons = metrics.travel_score(0, -10, "晴", "3-4级")
        self.assertLess(score, 60)
        self.assertTrue(any("偏低" in r for r in reasons))

    def test_score_bounds(self):
        for high, low in [(45, 35), (-20, -30), (20, 10)]:
            score, grade, _ = metrics.travel_score(high, low, "暴雨", "6-7级")
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)
            self.assertIn(grade, ("A", "B", "C", "D"))


class TestWindAndRain(unittest.TestCase):
    def test_wind_level(self):
        self.assertEqual(metrics.wind_level_num("<3级"), 2)
        self.assertEqual(metrics.wind_level_num("3-4级"), 4)
        self.assertEqual(metrics.wind_level_num("5-6级"), 6)
        self.assertEqual(metrics.wind_level_num(""), 0)

    def test_rain_detection(self):
        self.assertTrue(metrics.is_rainy("小雨"))
        self.assertTrue(metrics.is_rainy("雨夹雪"))
        self.assertFalse(metrics.is_rainy("多云"))
        self.assertTrue(metrics.is_heavy("暴雨"))


class TestEnrich(unittest.TestCase):
    def test_enrich_adds_columns(self):
        df = pd.DataFrame({
            "weather": ["晴", "小雨"],
            "temp_high": [20, 18],
            "temp_low": [10, 9],
            "wind_level_day": ["<3级", "3-4级"],
            "forecast_date": pd.to_datetime(["2026-11-21", "2026-11-22"]),
        })
        out = metrics.enrich(df, "forecast_date")
        self.assertIn("mean_temp", out.columns)
        self.assertIn("rainy", out.columns)
        self.assertAlmostEqual(out.iloc[0]["mean_temp"], 15.0)
        self.assertTrue(bool(out.iloc[1]["rainy"]))


if __name__ == "__main__":
    unittest.main()
