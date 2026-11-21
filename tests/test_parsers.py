# -*- coding: utf-8 -*-
"""解析器单元测试：用真实页面快照做回归，防止站点改版后静默失败。"""
from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from src.crawler.parsers import parse_forecast, parse_history, parse_temp

FIXTURES = Path(__file__).parent / "fixtures"


class TestParseTemp(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(parse_temp("8 / -3℃"), (8, -3))

    def test_no_space(self):
        self.assertEqual(parse_temp("22℃/8℃"), (22, 8))

    def test_invalid(self):
        self.assertEqual(parse_temp("暂无"), (None, None))
        self.assertEqual(parse_temp(""), (None, None))


class TestParseForecast(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        html = (FIXTURES / "forecast_beijing.html").read_text("utf-8")
        cls.rows = parse_forecast(
            html, "101010100", "北京",
            "http://www.weather.com.cn/weather/101010100.shtml",
            fallback_date=date(2026, 11, 21),
        )

    def test_count(self):
        self.assertEqual(len(self.rows), 7)

    def test_dates_are_consecutive(self):
        dates = [r["forecast_date"] for r in self.rows]
        self.assertEqual(dates[0], "2026-11-21")
        self.assertEqual(dates[-1], "2026-11-27")
        self.assertEqual(len(set(dates)), 7)

    def test_first_row_fields(self):
        first = self.rows[0]
        self.assertEqual(first["temp_high"], 8)
        self.assertEqual(first["temp_low"], -3)
        self.assertEqual(first["weather"], "晴")
        self.assertEqual(first["weekday"], "周六")
        self.assertTrue(first["wind_dir_day"].endswith("风"))

    def test_issue_date_from_hidden_input(self):
        self.assertEqual(self.rows[0]["issue_date"], "2026-11-21")

    def test_wind_level_split(self):
        # 第 3 天风力为 "3-4级转<3级"
        third = self.rows[2]
        self.assertEqual(third["wind_level_day"], "3-4级")
        self.assertEqual(third["wind_level_night"], "<3级")


class TestParseHistory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        html = (FIXTURES / "history_beijing_202610.html").read_text("utf-8")
        cls.rows = parse_history(
            html, "101010100", "北京",
            "http://www.tianqihoubao.com/lishi/beijing/month/202610.html",
        )

    def test_count(self):
        self.assertEqual(len(self.rows), 31)

    def test_first_row(self):
        first = self.rows[0]
        self.assertEqual(first["date"], "2026-10-01")
        self.assertEqual(first["weather_day"], "晴")
        self.assertEqual(first["weather_night"], "晴")
        self.assertEqual(first["temp_high"], 22)
        self.assertEqual(first["temp_low"], 8)
        self.assertEqual(first["wind_day"], "西南风")
        self.assertEqual(first["wind_level_day"], "1-3级")

    def test_no_invalid_rows(self):
        for r in self.rows:
            self.assertIsInstance(r["temp_high"], int)
            self.assertIsInstance(r["temp_low"], int)
            self.assertLessEqual(r["temp_low"], r["temp_high"])


if __name__ == "__main__":
    unittest.main()
