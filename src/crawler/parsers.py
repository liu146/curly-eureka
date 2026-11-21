# -*- coding: utf-8 -*-
"""HTML 解析：中国天气网 7 天预报 + 天气后报历史月度表。

两类页面结构完全不同：
- 中国天气网：<ul class="t clearfix"> 下 7 个 <li>，日期/天气/气温/风向分散在
  h1、p.wea、p.tem、p.win 中，气温形如 "8 / -3℃"；
- 天气后报：一张 4 列表格，单元格形如 "2026年10月01日"、"晴 / 晴"、
  "22℃/8℃"、"西南风 1-3级 / 西北风 1-3级"。
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

try:  # lxml 更快，缺失时退回标准库解析器
    import lxml  # noqa: F401

    _PARSER = "lxml"
except ImportError:  # pragma: no cover
    _PARSER = "html.parser"

TEMP_RE = re.compile(r"(-?\d+)\s*℃?\s*/\s*(-?\d+)\s*℃?")
HISTORY_DATE_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
DAY_LABEL_RE = re.compile(r"(\d{1,2})\s*日")
WIND_RE = re.compile(r"^(?P<dir>.*?)\s*(?P<level>[<>]?\d+(?:\s*-\s*\d+)?\s*级|微风)$")


def _text(node) -> str:
    return node.get_text(" ", strip=True) if node is not None else ""


def parse_temp(value: str) -> Tuple[Optional[int], Optional[int]]:
    """从 "8 / -3℃" 中解析 (最高, 最低)。"""
    if not value:
        return None, None
    m = TEMP_RE.search(value.replace(" ", ""))
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def _issue_date(soup: BeautifulSoup, fallback: date) -> Tuple[date, str]:
    """从页面隐藏域读取预报发布时间。"""
    for input_id in ("fc_3h_internal_update_time", "zs_7d_update_time"):
        node = soup.find("input", {"id": input_id})
        if node and node.get("value"):
            raw = node["value"].strip()
            for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d%H"):
                try:
                    return datetime.strptime(raw, fmt).date(), raw
                except ValueError:
                    continue
    node = soup.find("input", {"id": "hidden_title"})
    if node and node.get("value"):
        raw = node["value"]
        m = re.search(r"(\d{1,2})月(\d{1,2})日", raw)
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            year = fallback.year
            if month < fallback.month - 6:  # 跨年
                year += 1
            return date(year, month, day), raw
    return fallback, ""


def _split_wind(level_text: str) -> Tuple[str, str]:
    """'3-4级转<3级' -> ('3-4级', '<3级')。"""
    level_text = (level_text or "").replace(" ", "")
    if "转" in level_text:
        day, night = level_text.split("转", 1)
        return day, night
    return level_text, level_text


def parse_forecast(html: str, city_code: str, city_name: str, url: str,
                   fallback_date: Optional[date] = None) -> List[Dict]:
    """解析 7 天预报页，返回按日期排序的记录列表。"""
    soup = BeautifulSoup(html, _PARSER)
    issue, raw_issue = _issue_date(soup, fallback_date or date.today())
    ul = soup.select_one("ul.t.clearfix")
    if ul is None:
        raise ValueError(f"{city_name} 预报页结构变化：未找到 ul.t.clearfix")

    records: List[Dict] = []
    for li in ul.select("li"):
        label = _text(li.select_one("h1"))
        m = DAY_LABEL_RE.search(label)
        if not m:
            continue
        day_num = int(m.group(1))

        # 以发布日为起点，找最近的同名"日"
        forecast_date = None
        for offset in range(0, 8):
            cand = issue + timedelta(days=offset)
            if cand.day == day_num:
                forecast_date = cand
                break
        if forecast_date is None:
            continue

        high, low = parse_temp(_text(li.select_one("p.tem")))
        wea_node = li.select_one("p.wea")
        weather = (wea_node.get("title") if wea_node and wea_node.get("title") else _text(wea_node)).strip()

        spans = [s.get("title", "") for s in li.select("p.win em span")]
        wind_dir_day = spans[0] if spans else ""
        wind_dir_night = spans[1] if len(spans) > 1 else wind_dir_day
        wind_level_day, wind_level_night = _split_wind(_text(li.select_one("p.win i")))

        icons = []
        for big in li.select("big"):
            classes = big.get("class") or []
            icons.append(next((c for c in classes if re.fullmatch(r"[dn]\d{2}", c)), ""))
        icon_day = icons[0] if icons else ""
        icon_night = icons[1] if len(icons) > 1 else ""

        records.append(
            {
                "city_code": city_code,
                "city_name": city_name,
                "issue_date": issue.isoformat(),
                "forecast_date": forecast_date.isoformat(),
                "day_label": label,
                "weekday": "周" + "一二三四五六日"[forecast_date.weekday()],
                "weather": weather,
                "temp_high": high,
                "temp_low": low,
                "wind_dir_day": wind_dir_day,
                "wind_dir_night": wind_dir_night,
                "wind_level_day": wind_level_day,
                "wind_level_night": wind_level_night,
                "icon_day": icon_day,
                "icon_night": icon_night,
                "source_url": url,
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
                "raw_issue": raw_issue,
            }
        )

    if not records:
        raise ValueError(f"{city_name} 预报页未解析出任何记录")
    records.sort(key=lambda r: r["forecast_date"])
    return records


def _split_pair(value: str) -> Tuple[str, str]:
    """'晴 / 晴' -> ('晴', '晴')。"""
    parts = [p.strip() for p in re.split(r"\s*/\s*", value, maxsplit=1)]
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], parts[1]


def _parse_wind_cell(value: str) -> Tuple[str, str, str, str]:
    """'西南风 1-3级 / 西北风 1-3级' -> (dir_day, level_day, dir_night, level_night)。"""
    day_part, night_part = _split_pair(value)
    result = []
    for part in (day_part, night_part):
        part = part.strip()
        m = WIND_RE.match(part)
        if m:
            result.extend([m.group("dir").strip(), m.group("level").strip()])
        elif part:
            result.extend([part, ""])
        else:
            result.extend(["", ""])
    return result[0], result[1], result[2], result[3]


def parse_history(html: str, city_code: str, city_name: str, url: str) -> List[Dict]:
    """解析历史月度页表格。"""
    soup = BeautifulSoup(html, _PARSER)
    table = soup.select_one("table")
    if table is None:
        raise ValueError(f"{city_name} 历史页结构变化：未找到 table")

    records: List[Dict] = []
    for tr in table.select("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.select("td")]
        if len(cells) != 4:
            continue
        m = HISTORY_DATE_RE.search(cells[0])
        if not m:
            continue
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        high, low = parse_temp(cells[2])
        if high is None or low is None:
            continue
        weather_day, weather_night = _split_pair(cells[1])
        wd, wl, wn, wln = _parse_wind_cell(cells[3])
        records.append(
            {
                "city_code": city_code,
                "city_name": city_name,
                "date": d.isoformat(),
                "weather_day": weather_day,
                "weather_night": weather_night,
                "temp_high": high,
                "temp_low": low,
                "wind_day": wd,
                "wind_level_day": wl,
                "wind_night": wn,
                "wind_level_night": wln,
                "source_url": url,
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
    return records
