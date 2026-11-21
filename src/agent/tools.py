# -*- coding: utf-8 -*-
"""Agent 工具集：所有结论都必须来自这里的确定性查询，禁止模型自由发挥。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from ..analysis import metrics
from ..config import Config
from ..crawler.store import Store

CLOTHING_RULES = [
    (28, "短袖、短裤，注意防晒"),
    (22, "短袖或薄长袖，早晚备一件薄外套"),
    (16, "长袖衬衫 + 薄外套/针织衫"),
    (10, "毛衣 + 风衣或夹克"),
    (4, "厚外套、毛衣，注意保暖"),
    (-99, "羽绒服、保暖内衣、围巾手套"),
]


@dataclass
class ToolResult:
    name: str
    ok: bool
    data: Any = None
    summary: str = ""
    citations: List[Dict] = field(default_factory=list)
    error: str = ""
    elapsed_ms: int = 0

    def to_dict(self) -> Dict:
        return {
            "tool": self.name,
            "ok": self.ok,
            "summary": self.summary,
            "error": self.error,
            "citations": self.citations,
        }


def _cite(row: pd.Series, source_name: str) -> Dict:
    return {
        "source": source_name,
        "url": row.get("source_url", ""),
        "fetched_at": row.get("fetched_at", ""),
    }


class Toolbox:
    """对 SQLite 数据的只读封装，供 Agent 调用。"""

    def __init__(self, store: Store, config: Config, today: Optional[date] = None):
        self.store = store
        self.config = config
        self.today = today or date.today()
        self._history: Optional[pd.DataFrame] = None
        self._forecast: Optional[pd.DataFrame] = None
        self.calls: List[str] = []

    # ------------------------------------------------------------ 数据缓存
    @property
    def history(self) -> pd.DataFrame:
        if self._history is None:
            self._history = metrics.enrich(self.store.history_df(), "date")
        return self._history

    @property
    def forecast(self) -> pd.DataFrame:
        if self._forecast is None:
            fdf = metrics.enrich(self.store.forecast_df(), "forecast_date")
            self._forecast = metrics.score_forecast(fdf)
        return self._forecast

    # ------------------------------------------------------------ 辅助
    def resolve_city(self, name: str) -> Optional[str]:
        if not name:
            return None
        name = name.strip()
        hit = self.config.city(name)
        if hit:
            return hit.name
        for c in self.config.cities:
            if c.name in name or name in c.name:
                return c.name
        return None

    def _forecast_for(self, city: str) -> pd.DataFrame:
        df = self.forecast[self.forecast["city_name"] == city]
        if df.empty:
            return df
        latest = df["issue_date"].max()
        return df[df["issue_date"] == latest].sort_values("forecast_date")

    def _citations_for(self, df: pd.DataFrame, source_name: str, limit: int = 1) -> List[Dict]:
        out, seen = [], set()
        for _, row in df.iterrows():
            cite = _cite(row, source_name)
            if cite["url"] and cite["url"] not in seen:
                seen.add(cite["url"])
                out.append(cite)
            if len(out) >= limit:
                break
        return out

    def _freshness_note(self, df: pd.DataFrame) -> str:
        if df.empty:
            return ""
        issue = pd.Timestamp(df["issue_date"].max()).date()
        gap = (self.today - issue).days
        if gap <= 0:
            return "数据为今日最新发布。"
        return f"注意：当前预报批次为 {issue}，距今 {gap} 天，请以最新发布为准。"

    # ------------------------------------------------------------ 工具 1
    def get_forecast(self, city: str, days: int = 7, start: Optional[str] = None) -> ToolResult:
        t0 = datetime.now()
        df = self._forecast_for(city)
        if df.empty:
            return ToolResult("get_forecast", False, error=f"没有 {city} 的预报数据", elapsed_ms=0)
        if start:
            df = df[df["forecast_date"] >= pd.Timestamp(start)]
        df = df.head(days)
        rows = [
            {
                "date": r.forecast_date.date().isoformat(),
                "weekday": r.weekday,
                "weather": r.weather,
                "high": int(r.temp_high),
                "low": int(r.temp_low),
                "wind": f"{r.wind_dir_day} {r.wind_level_day}",
                "score": int(r.score),
                "grade": r.grade,
                "reasons": r.reasons,
                "mean": round(float(r.mean_temp), 1),
            }
            for r in df.itertuples()
        ]
        rainy = [r for r in rows if metrics.is_rainy(r["weather"])]
        summary = (
            f"{city}未来 {len(rows)} 天："
            f"{rows[0]['date']} 至 {rows[-1]['date']}，"
            f"降水 {len(rainy)} 天，"
            f"气温 {min(r['low'] for r in rows)}~{max(r['high'] for r in rows)}℃。"
        )
        return ToolResult(
            "get_forecast", True, {"city": city, "rows": rows, "rainy_days": len(rainy),
                                   "issue_date": str(pd.Timestamp(df["issue_date"].max()).date())},
            summary, self._citations_for(df, self.config["sources"]["forecast_name"]),
            elapsed_ms=int((datetime.now() - t0).total_seconds() * 1000),
        )

    # ------------------------------------------------------------ 工具 2
    def get_history(self, city: str, start: Optional[str] = None, end: Optional[str] = None) -> ToolResult:
        t0 = datetime.now()
        df = self.history[self.history["city_name"] == city]
        if df.empty:
            return ToolResult("get_history", False, error=f"没有 {city} 的历史数据")
        if start:
            df = df[df["date"] >= pd.Timestamp(start)]
        if end:
            df = df[df["date"] <= pd.Timestamp(end)]
        if df.empty:
            return ToolResult("get_history", False, error="指定时间范围内没有数据")
        prof = metrics.climate_profile(df).iloc[0].to_dict()
        seasons = metrics.season_compare(df).to_dict(orient="records")
        monthly = metrics.monthly_series(df).tail(24).to_dict(orient="records")
        summary = (
            f"{city}历史 {len(df)} 天：均温 {prof['mean_temp']}℃，"
            f"降水日占比 {prof['rain_ratio']}%，平均昼夜温差 {prof['avg_range']}℃。"
        )
        return ToolResult(
            "get_history", True,
            {"city": city, "profile": prof, "seasons": seasons, "monthly": monthly,
             "start": df["date"].min().date().isoformat(),
             "end": df["date"].max().date().isoformat()},
            summary, self._citations_for(df, self.config["sources"]["history_name"]),
            elapsed_ms=int((datetime.now() - t0).total_seconds() * 1000),
        )

    # ------------------------------------------------------------ 工具 3
    def compare_cities(self, cities: List[str], date_str: Optional[str] = None) -> ToolResult:
        t0 = datetime.now()
        fdf = self.forecast
        if fdf.empty:
            return ToolResult("compare_cities", False, error="没有预报数据")
        if date_str is None:
            date_str = str(fdf["forecast_date"].min().date())
        if cities:
            sub = fdf[fdf["city_name"].isin(cities)]
        else:
            sub = fdf
        day = sub[sub["forecast_date"].dt.date.astype(str) == date_str]
        if day.empty:
            return ToolResult("compare_cities", False, error=f"{date_str} 没有可用预报")
        day = day.sort_values("score", ascending=False)
        rows = [
            {
                "city": r.city_name,
                "weather": r.weather,
                "high": int(r.temp_high),
                "low": int(r.temp_low),
                "score": int(r.score),
                "grade": r.grade,
                "wind": f"{r.wind_dir_day} {r.wind_level_day}",
            }
            for r in day.itertuples()
        ]
        summary = f"{date_str} 共比较 {len(rows)} 个城市，最优为 {rows[0]['city']}（{rows[0]['score']} 分）。"
        return ToolResult(
            "compare_cities", True, {"date": date_str, "rows": rows},
            summary,
            [{"source": self.config["sources"]["forecast_name"], "url": r.source_url,
              "fetched_at": r.fetched_at} for r in day.itertuples()][:3],
            elapsed_ms=int((datetime.now() - t0).total_seconds() * 1000),
        )

    # ------------------------------------------------------------ 工具 4
    def travel_score(self, city: str, date_str: Optional[str] = None) -> ToolResult:
        df = self._forecast_for(city)
        if df.empty:
            return ToolResult("travel_score", False, error=f"没有 {city} 的预报")
        if date_str:
            df = df[df["forecast_date"].dt.date.astype(str) == date_str]
            if df.empty:
                return ToolResult("travel_score", False, error=f"{city} {date_str} 无预报")
        row = df.iloc[0]
        data = {
            "city": city,
            "date": row["forecast_date"].date().isoformat(),
            "score": int(row["score"]),
            "grade": row["grade"],
            "reasons": row["reasons"],
            "weather": row["weather"],
            "high": int(row["temp_high"]),
            "low": int(row["temp_low"]),
        }
        return ToolResult(
            "travel_score", True, data,
            f"{city} {data['date']} 出行指数 {data['score']}（{data['grade']} 级）。",
            self._citations_for(df, self.config["sources"]["forecast_name"]),
        )

    # ------------------------------------------------------------ 工具 5
    def best_day(self, city: str, within: int = 7) -> ToolResult:
        df = self._forecast_for(city).head(within)
        if df.empty:
            return ToolResult("best_day", False, error=f"没有 {city} 的预报")
        df = df.sort_values("score", ascending=False)
        rows = [
            {
                "date": r.forecast_date.date().isoformat(),
                "weekday": r.weekday,
                "weather": r.weather,
                "high": int(r.temp_high),
                "low": int(r.temp_low),
                "score": int(r.score),
                "grade": r.grade,
                "reasons": r.reasons,
            }
            for r in df.itertuples()
        ]
        summary = f"{city}未来 {len(rows)} 天最佳出行日：{rows[0]['date']}（{rows[0]['score']} 分）。"
        return ToolResult(
            "best_day", True, {"city": city, "rows": rows}, summary,
            self._citations_for(df, self.config["sources"]["forecast_name"]),
        )

    # ------------------------------------------------------------ 工具 6
    def climate_anomaly(self, city: str, date_str: Optional[str] = None) -> ToolResult:
        df = self._forecast_for(city)
        if df.empty:
            return ToolResult("climate_anomaly", False, error=f"没有 {city} 的预报")
        anom = metrics.anomaly_table(df, self.history, city)
        if anom.empty:
            return ToolResult("climate_anomaly", False, error="历史样本不足，无法计算常年值")
        rows = anom.to_dict(orient="records")
        avg_delta = round(float(anom["delta"].mean()), 1)
        summary = f"{city}未来 {len(rows)} 天平均较常年同期 {'偏高' if avg_delta >= 0 else '偏低'} {abs(avg_delta)}℃。"
        return ToolResult(
            "climate_anomaly", True,
            {"city": city, "rows": rows, "avg_delta": avg_delta}, summary,
            self._citations_for(self.history[self.history["city_name"] == city],
                                self.config["sources"]["history_name"]),
        )

    # ------------------------------------------------------------ 工具 7
    def packing_advice(self, city: str, date_str: Optional[str] = None) -> ToolResult:
        fdf = self._forecast_for(city)
        if fdf.empty:
            return ToolResult("packing_advice", False, error=f"没有 {city} 的预报")
        if date_str:
            day = fdf[fdf["forecast_date"].dt.date.astype(str) == date_str]
            if day.empty:
                return ToolResult("packing_advice", False, error=f"{city} {date_str} 无预报")
            rows = day
            label = date_str
        else:
            rows = fdf.head(3)
            label = f"{rows.iloc[0]['forecast_date'].date()} 至 {rows.iloc[-1]['forecast_date'].date()}"

        low = int(rows["temp_low"].min())
        high = int(rows["temp_high"].max())
        mean = (low + high) / 2
        clothing = next(text for threshold, text in CLOTHING_RULES if mean >= threshold)
        items = []
        if rows["weather"].apply(metrics.is_rainy).any():
            items.append("折叠伞/雨衣")
        if rows["wind_num"].max() >= 5:
            items.append("防风外套")
        if (rows["temp_range"] > 10).any():
            items.append("可分层穿脱的衣物")
        if high >= 30:
            items.append("防晒霜、遮阳帽")
        if low <= 0:
            items.append("手套、保暖内衣")
        if not items:
            items.append("无需特殊装备")
        data = {"city": city, "range": label, "clothing": clothing, "items": items,
                "low": low, "high": high}
        summary = f"{city}{label}：{clothing}；另需 {('、'.join(items))}。"
        return ToolResult(
            "packing_advice", True, data, summary,
            self._citations_for(fdf, self.config["sources"]["forecast_name"]),
        )

    # ------------------------------------------------------------ 工具 8
    def save_brief(self, content: str, filename: str = "") -> ToolResult:
        if not filename:
            filename = f"brief_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        path = self.config.brief_dir / filename
        path.write_text(content, "utf-8")
        return ToolResult("save_brief", True, {"path": str(path)},
                          f"简报已保存：{path}")

    # ------------------------------------------------------------ 调度
    def call(self, tool: str, **kwargs) -> ToolResult:
        self.calls.append(tool)
        fn = getattr(self, tool, None)
        if fn is None:
            return ToolResult(tool, False, error=f"未知工具 {tool}")
        try:
            return fn(**kwargs)
        except TypeError as exc:
            return ToolResult(tool, False, error=f"参数错误：{exc}")
