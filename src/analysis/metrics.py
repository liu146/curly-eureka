# -*- coding: utf-8 -*-
"""统计分析与出行指数计算。

出行指数是一个可解释的 0~100 分规则模型：
气温舒适度、降水、风力、昼夜温差、极端温度五个维度分别扣分，
扣分明细会一并返回，供 Agent 在回答中给出理由（而不是只给一个分数）。
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

import pandas as pd

RAIN_RE = re.compile(r"雨|雪|雷")
HEAVY_RE = re.compile(r"暴雨|大雨|暴雪|大雪|雷阵雨")
SUNNY = {"晴", "多云转晴", "晴转多云"}

DEFAULT_COMFORT = (16.0, 26.0)


# --------------------------------------------------------------------- 基础特征
def is_rainy(weather: str) -> bool:
    return bool(RAIN_RE.search(weather or ""))


def is_heavy(weather: str) -> bool:
    return bool(HEAVY_RE.search(weather or ""))


def wind_level_num(text: str) -> int:
    """'3-4级转<3级' -> 4；'<3级' -> 2；'≥6级' -> 6。"""
    if not text:
        return 0
    text = str(text)
    if text.startswith("<"):
        return 2
    nums = [int(n) for n in re.findall(r"\d+", text)]
    return max(nums) if nums else 0


def enrich(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    """补充均温、温差、月份、降水标记等派生列。"""
    df = df.copy()
    df["mean_temp"] = (df["temp_high"] + df["temp_low"]) / 2.0
    df["temp_range"] = (df["temp_high"] - df["temp_low"]).abs()
    df["month"] = pd.to_datetime(df[date_col]).dt.to_period("M").astype(str)
    weather_col = "weather_day" if "weather_day" in df.columns else "weather"
    df["rainy"] = df[weather_col].apply(is_rainy)
    df["heavy"] = df[weather_col].apply(is_heavy)
    df["wind_num"] = df["wind_level_day"].apply(wind_level_num)
    return df


# --------------------------------------------------------------------- 出行指数
def travel_score(
    temp_high: float,
    temp_low: float,
    weather: str,
    wind_level: str = "",
    comfort: Tuple[float, float] = DEFAULT_COMFORT,
) -> Tuple[int, str, List[str]]:
    """返回 (分数, 等级, 扣分理由列表)。"""
    mean = (temp_high + temp_low) / 2.0
    lo, hi = comfort
    penalties: List[str] = []
    score = 100.0

    if mean < lo:
        gap = lo - mean
        deduct = 12 if gap <= 6 else 25 if gap <= 11 else 35
        score -= deduct
        penalties.append(f"均温 {mean:.1f}℃ 偏低（-{deduct}）")
    elif mean > hi:
        gap = mean - hi
        deduct = 12 if gap <= 4 else 25 if gap <= 8 else 35
        score -= deduct
        penalties.append(f"均温 {mean:.1f}℃ 偏高（-{deduct}）")

    if is_rainy(weather):
        deduct = 25 if is_heavy(weather) else 18
        score -= deduct
        penalties.append(f"{'强' if is_heavy(weather) else ''}降水天气「{weather}」（-{deduct}）")
    elif "阴" in (weather or ""):
        score -= 6
        penalties.append("阴天，体感与观景体验一般（-6）")
    elif "多云" in (weather or ""):
        score -= 2
        penalties.append("多云（-2）")

    level = wind_level_num(wind_level)
    if level >= 6:
        score -= 12
        penalties.append(f"风力 {level} 级偏大（-12）")
    elif level == 5:
        score -= 6
        penalties.append(f"风力 {level} 级（-6）")
    elif level == 4:
        score -= 2
        penalties.append(f"风力 {level} 级（-2）")

    rng = abs(temp_high - temp_low)
    if rng > 15:
        score -= 12
        penalties.append(f"昼夜温差 {rng:.0f}℃ 很大（-12）")
    elif rng > 12:
        score -= 8
        penalties.append(f"昼夜温差 {rng:.0f}℃ 较大（-8）")
    elif rng > 10:
        score -= 4
        penalties.append(f"昼夜温差 {rng:.0f}℃ 略大（-4）")

    if temp_high >= 35:
        score -= 8
        penalties.append(f"最高温 {temp_high:.0f}℃ 高温（-8）")
    if temp_low <= -10:
        score -= 8
        penalties.append(f"最低温 {temp_low:.0f}℃ 严寒（-8）")

    score = int(round(max(0.0, min(100.0, score))))
    grade = "A" if score >= 80 else "B" if score >= 65 else "C" if score >= 50 else "D"
    if not penalties:
        penalties.append("气温、降水、风力均适宜")
    return score, grade, penalties


def score_forecast(fdf: pd.DataFrame, comfort: Tuple[float, float] = DEFAULT_COMFORT) -> pd.DataFrame:
    df = fdf.copy()
    results = [
        travel_score(r.temp_high, r.temp_low, r.weather, r.wind_level_day, comfort)
        for r in df.itertuples()
    ]
    df["score"] = [r[0] for r in results]
    df["grade"] = [r[1] for r in results]
    df["reasons"] = [r[2] for r in results]
    df["mean_temp"] = (df["temp_high"] + df["temp_low"]) / 2.0
    return df


# --------------------------------------------------------------------- 历史画像
def climate_profile(hdf: pd.DataFrame) -> pd.DataFrame:
    """每个城市的气候画像（基于全部历史数据）。"""
    rows = []
    for city, g in hdf.groupby("city_name"):
        rows.append(
            {
                "city": city,
                "days": len(g),
                "avg_high": round(g["temp_high"].mean(), 1),
                "avg_low": round(g["temp_low"].mean(), 1),
                "mean_temp": round(g["mean_temp"].mean(), 1),
                "max_high": int(g["temp_high"].max()),
                "min_low": int(g["temp_low"].min()),
                "rain_days": int(g["rainy"].sum()),
                "rain_ratio": round(g["rainy"].mean() * 100, 1),
                "avg_range": round(g["temp_range"].mean(), 1),
                "strong_wind_days": int((g["wind_num"] >= 6).sum()),
            }
        )
    return pd.DataFrame(rows).sort_values("mean_temp", ascending=False)


def monthly_series(hdf: pd.DataFrame) -> pd.DataFrame:
    g = hdf.groupby(["city_name", "month"]).agg(
        mean_temp=("mean_temp", "mean"),
        rain_days=("rainy", "sum"),
        days=("date", "count"),
    ).reset_index()
    g["mean_temp"] = g["mean_temp"].round(2)
    return g


def season_compare(hdf: pd.DataFrame, season_months=(6, 7, 8)) -> pd.DataFrame:
    """同一年夏季（默认 6-8 月）平均气温，用于年度对比。"""
    df = hdf.copy()
    df["year"] = pd.to_datetime(df["date"]).dt.year
    df["month_num"] = pd.to_datetime(df["date"]).dt.month
    sub = df[df["month_num"].isin(season_months)]
    out = sub.groupby(["city_name", "year"]).agg(
        mean_temp=("mean_temp", "mean"),
        rain_days=("rainy", "sum"),
        days=("date", "count"),
    ).reset_index()
    out["mean_temp"] = out["mean_temp"].round(2)
    return out


def climatology(hdf: pd.DataFrame, city_name: str, target: pd.Timestamp, window: int = 7) -> Dict[str, float]:
    """目标日期前后 window 天、跨年份的历史均值。"""
    g = hdf[hdf["city_name"] == city_name].copy()
    if g.empty:
        return {}
    doy = target.dayofyear
    g["doy"] = pd.to_datetime(g["date"]).dt.dayofyear
    diff = (g["doy"] - doy).abs()
    diff = diff.where(diff <= 180, 365 - diff)  # 处理跨年
    sub = g[diff <= window]
    if sub.empty:
        return {}
    return {
        "mean_temp": float(sub["mean_temp"].mean()),
        "avg_high": float(sub["temp_high"].mean()),
        "avg_low": float(sub["temp_low"].mean()),
        "rain_ratio": float(sub["rainy"].mean()),
        "n_years_days": int(len(sub)),
    }


def anomaly_table(fdf: pd.DataFrame, hdf: pd.DataFrame, city_name: str) -> pd.DataFrame:
    """预报值 vs 常年同期的偏差表。"""
    g = fdf[fdf["city_name"] == city_name].sort_values("forecast_date")
    rows = []
    for r in g.itertuples():
        clim = climatology(hdf, city_name, pd.Timestamp(r.forecast_date))
        if not clim:
            continue
        delta = r.mean_temp - clim["mean_temp"]
        rows.append(
            {
                "date": pd.Timestamp(r.forecast_date).date().isoformat(),
                "weekday": r.weekday,
                "weather": r.weather,
                "temp_high": r.temp_high,
                "temp_low": r.temp_low,
                "mean_temp": round(r.mean_temp, 1),
                "clim_mean": round(clim["mean_temp"], 1),
                "delta": round(delta, 1),
                "verdict": "明显偏暖" if delta >= 2 else "偏暖" if delta >= 1 else
                           "明显偏冷" if delta <= -2 else "偏冷" if delta <= -1 else "接近常年",
            }
        )
    return pd.DataFrame(rows)


def compare_cities(fdf: pd.DataFrame, date_str: Optional[str] = None) -> pd.DataFrame:
    """同一天各城市的天气与出行指数对比。"""
    if fdf.empty:
        return pd.DataFrame()
    if date_str is None:
        date_str = fdf["forecast_date"].min().date().isoformat()
    sub = fdf[fdf["forecast_date"].dt.date.astype(str) == date_str]
    if sub.empty:
        # 找最近的一天
        nearest = fdf.iloc[(fdf["forecast_date"] - pd.Timestamp(date_str)).abs().argsort()[:1]]
        sub = fdf[fdf["forecast_date"].isin(nearest["forecast_date"])]
    return sub.sort_values("score", ascending=False)


def best_days(fdf: pd.DataFrame, city_name: str, top_n: int = 3) -> pd.DataFrame:
    g = fdf[fdf["city_name"] == city_name].sort_values("score", ascending=False)
    return g.head(top_n)


# --------------------------------------------------------------------- 汇总
def summarize(store, config) -> Dict:
    """生成报告所需的全量统计摘要。"""
    hdf = enrich(store.history_df(), "date")
    fdf = enrich(store.forecast_df(), "forecast_date")
    fdf = score_forecast(fdf)

    profile = climate_profile(hdf)
    monthly = monthly_series(hdf)
    seasons = season_compare(hdf)

    issue = fdf["issue_date"].max().date().isoformat() if not fdf.empty else None

    summary = {
        "generated_at": pd.Timestamp.now().isoformat(timespec="seconds"),
        "counts": store.counts(),
        "cities": config.city_names,
        "history": {
            "start": hdf["date"].min().date().isoformat(),
            "end": hdf["date"].max().date().isoformat(),
            "rows": int(len(hdf)),
            "days_per_city": int(hdf.groupby("city_name").size().mean()),
        },
        "forecast": {
            "issue_date": issue,
            "rows": int(len(fdf)),
            "days": int(fdf["forecast_date"].nunique()) if not fdf.empty else 0,
        },
        "profile": profile.to_dict(orient="records"),
        "season": seasons.to_dict(orient="records"),
        "hottest_city": profile.iloc[0]["city"] if not profile.empty else None,
        "coldest_city": profile.iloc[-1]["city"] if not profile.empty else None,
        "rainiest_city": profile.sort_values("rain_ratio", ascending=False).iloc[0]["city"]
        if not profile.empty else None,
        "largest_range_city": profile.sort_values("avg_range", ascending=False).iloc[0]["city"]
        if not profile.empty else None,
        "national_avg_rain_ratio": round(float(profile["rain_ratio"].mean()), 1) if not profile.empty else None,
    }

    if not fdf.empty:
        day0 = fdf["forecast_date"].min()
        cmp0 = compare_cities(fdf, day0.date().isoformat())
        summary["forecast_compare"] = cmp0[
            ["city_name", "weather", "temp_high", "temp_low", "score", "grade"]
        ].to_dict(orient="records")
        summary["best_city_today"] = cmp0.iloc[0]["city_name"] if not cmp0.empty else None
        summary["anomaly_beijing"] = anomaly_table(fdf, hdf, config.agent_cfg["default_city"]).to_dict(
            orient="records"
        )
        summary["travel_scores"] = fdf[
            ["city_name", "forecast_date", "weather", "temp_high", "temp_low", "score", "grade"]
        ].assign(forecast_date=lambda d: d["forecast_date"].dt.date.astype(str)).to_dict(orient="records")

    return summary
