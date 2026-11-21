# -*- coding: utf-8 -*-
"""离线规划器：把自然语言问题解析成"意图 + 槽位 + 工具调用计划"。

不依赖任何大模型，纯规则实现，保证没有 API Key 也能完整演示 Agent 行为；
规则覆盖了课程演示所需的常见问法，并且每一步都能解释"为什么调这个工具"。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from ..config import Config

WEEKDAY_MAP = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}

INTENT_RULES: List[Tuple[str, List[str]]] = [
    ("brief", ["简报", "汇总", "总结", "报告", "周报", "日报", "一份"]),
    ("compare", ["对比", "比较", "哪个", "哪座", "哪里", "去哪儿", "还是",
                 "更适合", "选哪", "哪个好"]),
    ("best_day", ["哪天", "什么时候", "最佳", "最适合", "适合出去玩", "适合出行",
                  "适合旅游", "安排", "周末", "出去玩", "出行"]),
    ("rain", ["伞", "下雨", "降雨", "降水", "淋雨", "会不会淋", "雨天", "下雪"]),
    ("packing", ["穿", "带什么", "穿衣", "衣服", "行李", "装备", "冷不冷", "热不热",
                 "冷不", "热不", "保暖"]),
    ("anomaly", ["反常", "异常", "偏暖", "偏冷", "比往年", "常年", "同期", "距平"]),
    ("trend", ["今年", "去年", "趋势", "变化", "气候", "夏天", "冬天", "变暖",
               "这些年", "近几年"]),
]

PRIORITY = ["brief", "compare", "best_day", "rain", "packing", "anomaly", "trend"]


@dataclass
class Slots:
    cities: List[str] = field(default_factory=list)
    target_date: Optional[date] = None
    date_label: str = "未来 7 天"
    within: int = 7
    weekend_only: bool = False
    assumed_city: bool = False


@dataclass
class PlanStep:
    tool: str
    args: Dict
    reason: str


@dataclass
class Plan:
    question: str
    intents: List[str]
    slots: Slots
    steps: List[PlanStep]
    notes: List[str] = field(default_factory=list)


# ------------------------------------------------------------------ 日期解析
def _next_weekday(today: date, weekday: int, force_next_week: bool = False) -> date:
    if force_next_week:
        # "下周三" = 下一个自然周的周三
        monday_next = today + timedelta(days=7 - today.weekday())
        return monday_next + timedelta(days=weekday)
    return today + timedelta(days=(weekday - today.weekday()) % 7)


def resolve_date(text: str, today: date) -> Tuple[Optional[date], str, int, bool]:
    """返回 (目标日期, 描述, 覆盖天数, 是否仅周末)。"""
    if re.search(r"大后天", text):
        return today + timedelta(days=3), "大后天", 1, False
    if re.search(r"后天", text):
        return today + timedelta(days=2), "后天", 1, False
    if re.search(r"明天|明日|明儿", text):
        return today + timedelta(days=1), "明天", 1, False
    if re.search(r"今天|今日|现在|当前", text):
        return today, "今天", 1, False

    m = re.search(r"下下周([一二三四五六日天])", text)
    if m:
        target = _next_weekday(today, WEEKDAY_MAP[m.group(1)], force_next_week=True) + timedelta(days=7)
        return target, f"下下周{m.group(1)}", 1, False
    m = re.search(r"下周([一二三四五六日天])", text)
    if m:
        target = _next_weekday(today, WEEKDAY_MAP[m.group(1)], force_next_week=True)
        return target, f"下周{m.group(1)}", 1, False
    m = re.search(r"(?:这|本)周([一二三四五六日天])", text)
    if m:
        target = _next_weekday(today, WEEKDAY_MAP[m.group(1)])
        return target, f"本周{m.group(1)}", 1, False

    if re.search(r"周末", text):
        # 本周六；若今天是周日，则指今天
        saturday = _next_weekday(today, 5)
        if today.weekday() == 6:
            saturday = today - timedelta(days=1)
        return saturday, "本周末", 2, True

    m = re.search(r"未来\s*([一二三四五六七八九十两\d]+)\s*天", text)
    if m:
        token = m.group(1)
        num = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
               "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}.get(token) or int(token)
        num = min(max(num, 1), 7)
        return None, f"未来 {num} 天", num, False
    if re.search(r"未来一周|近一周|这一周|一周", text):
        return None, "未来 7 天", 7, False
    if re.search(r"这几天|最近几天", text):
        return None, "最近几天", 3, False

    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?", text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        year = today.year
        try:
            target = date(year, month, day)
            if target < today - timedelta(days=180):
                target = date(year + 1, month, day)
            label = f"{month} 月 {day} 日"
            within = max((target - today).days + 1, 1)
            return (target if within <= 7 else None), label, min(within, 7) if within <= 7 else 7, False
        except ValueError:
            return None, "未来 7 天", 7, False
    return None, "未来 7 天", 7, False


# ------------------------------------------------------------------ 槽位
def extract_cities(text: str, config: Config) -> List[str]:
    found = [c.name for c in config.cities if c.name in text]
    # 去掉被更长城市名包含的情况（如"南京"含"京"不会误伤，但"上海"与"海上"无冲突）
    found = sorted(set(found), key=lambda n: text.index(n))
    return found


def detect_intents(text: str) -> List[str]:
    matched = [name for name, kws in INTENT_RULES if any(k in text for k in kws)]
    if not matched:
        return ["general"]
    # 中文"还是"通常表示比较，避免误判成出行
    return [name for name in PRIORITY if name in matched]


# ------------------------------------------------------------------ 计划
def make_plan(question: str, config: Config, today: Optional[date] = None,
              memory_city: Optional[str] = None) -> Plan:
    today = today or date.today()
    text = question.strip()
    intents = detect_intents(text)
    cities = extract_cities(text, config)
    assumed = False
    if not cities:
        if "compare" in intents:
            cities = []  # 全城市对比
        else:
            cities = [memory_city or config.agent_cfg["default_city"]]
            assumed = True

    far_date_note = ""
    try:
        target, label, within, weekend_only = resolve_date(text, today)
    except (ValueError, TypeError, KeyError):
        target, label, within, weekend_only = None, "未来 7 天", 7, False
    if target is not None and (target - today).days > 6:
        far_date_note = f"{label}已超出 7 天预报范围，改为给出未来 7 天概况"
        target = None
    slots = Slots(cities=cities, target_date=target, date_label=label,
                  within=within, weekend_only=weekend_only, assumed_city=assumed)

    steps: List[PlanStep] = []
    notes: List[str] = []
    if assumed:
        if memory_city:
            notes.append(f"沿用上一轮城市：{cities[0]}。")
        else:
            notes.append(f"未指定城市，默认使用 {cities[0]}。")
    if far_date_note:
        notes.append(far_date_note)
    date_iso = target.isoformat() if target else None

    def add(tool: str, args: Dict, reason: str):
        key = (tool, json.dumps(args, sort_keys=True, ensure_ascii=False, default=str))
        existing = {(s.tool, json.dumps(s.args, sort_keys=True, ensure_ascii=False, default=str))
                    for s in steps}
        if key not in existing:
            steps.append(PlanStep(tool, args, reason))

    if "brief" in intents:
        city = cities[0] if cities else config.agent_cfg["default_city"]
        add("get_forecast", {"city": city, "days": 7}, "生成简报需要完整的一周预报")
        add("best_day", {"city": city, "within": 7}, "简报需要给出最佳出行日")
        add("climate_anomaly", {"city": city}, "简报需要说明与常年同期的差异")
        add("get_history", {"city": city}, "简报需要气候背景数据")
        return Plan(question, intents, slots, steps, notes)

    if "compare" in intents and len(cities) >= 2:
        add("compare_cities", {"cities": cities, "date_str": date_iso},
            f"用户要求比较 {'、'.join(cities)}，调用城市对比工具")
        for c in cities:
            add("best_day", {"city": c, "within": within}, f"补充 {c} 未来几天的候选日期")
        return Plan(question, intents, slots, steps, notes)

    if "compare" in intents and len(cities) == 1:
        notes.append("只识别到一个城市，无法做城市间对比，改为给出该城市的最佳出行日。")
        intents = [i for i in intents if i != "compare"] + ["best_day"]

    for city in cities:
        if "trend" in intents:
            add("get_history", {"city": city}, "趋势类问题需要历史序列")
        if "anomaly" in intents:
            add("climate_anomaly", {"city": city}, "需要与常年同期比较")
        add("get_forecast", {"city": city, "days": within, "start": date_iso},
            "所有出行建议都需要预报数据")
        if "best_day" in intents:
            add("best_day", {"city": city, "within": within}, "需要在未来几天中排序")
        if "packing" in intents:
            add("packing_advice", {"city": city, "date_str": date_iso}, "需要给出穿衣与携带建议")

    if not steps:
        add("get_forecast", {"city": cities[0], "days": 7}, "默认给出未来一周概况")

    return Plan(question, intents, slots, steps, notes)
