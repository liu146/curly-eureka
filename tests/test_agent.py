# -*- coding: utf-8 -*-
"""Agent 集成测试：用临时 SQLite 构造可控数据，验证问答、引用与上下文记忆。"""
from __future__ import annotations

import math
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from src.agent.loop import Agent, Session
from src.agent.tools import Toolbox
from src.config import load_config
from src.crawler.store import Store

TODAY = date(2026, 11, 21)
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def seed(store: Store, cfg) -> None:
    store.init_schema()
    store.upsert_cities(cfg.cities)

    forecasts = []
    for city in cfg.cities[:2]:  # 北京、上海
        for i in range(7):
            d = TODAY + timedelta(days=i)
            forecasts.append({
                "city_code": city.code,
                "issue_date": TODAY.isoformat(),
                "forecast_date": d.isoformat(),
                "day_label": f"{d.day}日",
                "weekday": WEEKDAYS[d.weekday()],
                "weather": "小雨" if i == 2 else "晴",
                "temp_high": 12 + i,
                "temp_low": 2 + i,
                "wind_dir_day": "北风",
                "wind_dir_night": "南风",
                "wind_level_day": "3-4级",
                "wind_level_night": "<3级",
                "icon_day": "d01",
                "icon_night": "n01",
                "source_url": f"https://example.com/{city.code}",
                "fetched_at": "2026-11-21T08:00:00",
            })
    store.upsert_forecasts(forecasts)

    history = []
    for city in cfg.cities[:2]:
        for back in range(730, 0, -1):
            d = TODAY - timedelta(days=back)
            doy = d.timetuple().tm_yday
            high = round(15 + 10 * math.sin(2 * math.pi * (doy - 100) / 365))
            low = high - 8
            history.append({
                "city_code": city.code,
                "date": d.isoformat(),
                "weather_day": "小雨" if doy % 9 == 0 else "晴",
                "weather_night": "多云",
                "temp_high": high,
                "temp_low": low,
                "wind_day": "北风",
                "wind_level_day": "1-3级",
                "wind_night": "南风",
                "wind_level_night": "1-3级",
                "source_url": f"https://example.com/history/{city.code}",
                "fetched_at": "2026-11-21T08:00:00",
            })
    store.upsert_history(history)


class TestAgent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.cfg = load_config()
        cls.store = Store(Path(cls.tmp.name) / "test.db")
        seed(cls.store, cls.cfg)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def make_agent(self):
        return Agent(Toolbox(self.store, self.cfg, today=TODAY), self.cfg, today=TODAY)

    def test_rain_answer(self):
        agent = self.make_agent()
        ans = agent.ask("北京明天要带伞吗？")
        self.assertIn("北京", ans.text)
        self.assertIn("降水", ans.text)
        self.assertTrue(ans.trace)
        self.assertTrue(ans.citations)

    def test_compare_answer(self):
        agent = self.make_agent()
        ans = agent.ask("北京和上海哪个更适合周末出游？")
        self.assertIn("城市对比", ans.text)
        self.assertIn("上海", ans.text)
        self.assertGreaterEqual(len(ans.trace), 1)

    def test_brief_saves_file(self):
        agent = self.make_agent()
        ans = agent.ask("帮我生成一份北京出行简报")
        self.assertIn("出行简报", ans.text)
        saved = [t for t in ans.trace if t.action == "save_brief"]
        self.assertTrue(saved)

    def test_context_memory(self):
        agent = self.make_agent()
        session = Session()
        agent.ask("上海明天天气怎么样", session)
        ans = agent.ask("那后天呢？", session)
        self.assertIn("上海", ans.text)

    def test_unknown_city_falls_back(self):
        agent = self.make_agent()
        ans = agent.ask("天津天气怎么样")
        self.assertIn("默认", ans.text)

    def test_checks_present(self):
        agent = self.make_agent()
        ans = agent.ask("北京这周末适合出去玩吗？")
        names = [c["check"] for c in ans.checks]
        self.assertIn("结论包含可溯源引用", names)
        self.assertTrue(all(c["pass"] for c in ans.checks))


if __name__ == "__main__":
    unittest.main()
