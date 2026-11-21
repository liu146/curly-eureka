# -*- coding: utf-8 -*-
"""图表生成：预报热力图、月度气候趋势、降水画像、出行指数、气候异常、系统架构。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.font_manager import FontProperties, findfont
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

# ------------------------------------------------------------------ 中文字体
_CANDIDATES = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei"]

PALETTE = {
    "blue": "#2F5D8A",
    "teal": "#2A9D8F",
    "orange": "#E76F51",
    "sand": "#E9C46A",
    "dark": "#264653",
    "gray": "#8D99AE",
}


def setup_font() -> str:
    """设置中文字体，返回实际使用的字体名。"""
    available = {f.name for f in matplotlib.font_manager.fontManager.ttflist}
    chosen = next((c for c in _CANDIDATES if c in available), None)
    if chosen is None:
        # 直接按文件注册
        for path in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
            if Path(path).exists():
                matplotlib.font_manager.fontManager.addfont(path)
                chosen = FontProperties(fname=path).get_name()
                break
    if chosen:
        plt.rcParams["font.sans-serif"] = [chosen]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.facecolor"] = "white"
    plt.rcParams["axes.edgecolor"] = "#CBD5E1"
    plt.rcParams["axes.labelcolor"] = "#1F2937"
    plt.rcParams["text.color"] = "#1F2937"
    return chosen or "sans-serif"


def _save(fig, path: Path, dpi: int = 170) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


# ------------------------------------------------------------------ 图1 预报热力图
def fig_forecast_heatmap(fdf: pd.DataFrame, path: Path) -> Path:
    pivot = fdf.pivot_table(index="city_name", columns="forecast_date", values="mean_temp")
    order = fdf.drop_duplicates("city_name").sort_values("mean_temp", ascending=False)["city_name"]
    pivot = pivot.reindex([c for c in order if c in pivot.index])
    labels = [f"{d.month}/{d.day}" for d in pivot.columns]

    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    im = ax.imshow(pivot.values, cmap="RdYlBu_r", aspect="auto")
    ax.set_xticks(range(len(labels)), labels)
    ax.set_yticks(range(len(pivot.index)), pivot.index)
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            v = pivot.values[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:.0f}", ha="center", va="center",
                        fontsize=9, color="white" if v >= 24 or v <= 3 else "#1F2937")
    cbar = fig.colorbar(im, ax=ax, pad=0.02)
    cbar.set_label("日平均气温（℃）")
    ax.set_title("未来 7 天 12 城市日平均气温（%s 发布）" % fdf["issue_date"].max().date(), pad=12)
    ax.set_xlabel("预报日期（月/日）")
    return _save(fig, path)


# ------------------------------------------------------------------ 图2 月度趋势
def fig_monthly_trend(hdf: pd.DataFrame, path: Path, cities: Optional[list] = None) -> Path:
    cities = cities or ["哈尔滨", "北京", "上海", "广州", "三亚"]
    fig, ax = plt.subplots(figsize=(10.5, 5.2))
    colors = [PALETTE["dark"], PALETTE["blue"], PALETTE["teal"], PALETTE["orange"], PALETTE["sand"]]
    for city, color in zip(cities, colors):
        g = hdf[hdf["city_name"] == city].copy()
        if g.empty:
            continue
        g["ym"] = pd.to_datetime(g["date"]).dt.to_period("M").dt.to_timestamp()
        s = g.groupby("ym")["mean_temp"].mean()
        ax.plot(s.index, s.values, marker="o", ms=3, lw=1.8, label=city, color=color)
    nat = hdf.copy()
    nat["ym"] = pd.to_datetime(nat["date"]).dt.to_period("M").dt.to_timestamp()
    s = nat.groupby("ym")["mean_temp"].mean()
    ax.plot(s.index, s.values, lw=2.4, ls="--", color=PALETTE["gray"], label="12 城平均")
    ax.axhline(0, color="#CBD5E1", lw=0.8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.setp(ax.get_xticklabels(), rotation=40, ha="right")
    ax.set_ylabel("月平均气温（℃）")
    ax.set_title("24 个月月平均气温变化（2024-11 至 2026-10）")
    ax.legend(ncol=3, frameon=False, loc="upper left")
    ax.grid(axis="y", alpha=0.25)
    return _save(fig, path)


# ------------------------------------------------------------------ 图3 降水与温差
def fig_rain_profile(profile: pd.DataFrame, path: Path) -> Path:
    df = profile.sort_values("rain_ratio", ascending=True)
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.4), gridspec_kw={"width_ratios": [1.35, 1]})

    ax = axes[0]
    colors = [PALETTE["teal"] if v < df["rain_ratio"].mean() else PALETTE["blue"] for v in df["rain_ratio"]]
    ax.barh(df["city"], df["rain_ratio"], color=colors, height=0.62)
    for y, v in enumerate(df["rain_ratio"]):
        ax.text(v + 0.4, y, f"{v:.1f}%", va="center", fontsize=8.5)
    ax.axvline(df["rain_ratio"].mean(), color=PALETTE["orange"], ls="--", lw=1.2,
               label=f"均值 {df['rain_ratio'].mean():.1f}%")
    ax.set_xlabel("有降水日占比（%）")
    ax.set_title("各城市降水频率（24 个月）")
    ax.legend(frameon=False, loc="lower right")
    ax.set_xlim(0, max(df["rain_ratio"]) * 1.18)

    ax2 = axes[1]
    df2 = df.sort_values("avg_range", ascending=True)
    ax2.barh(df2["city"], df2["avg_range"], color=PALETTE["sand"], height=0.62)
    for y, v in enumerate(df2["avg_range"]):
        ax2.text(v + 0.15, y, f"{v:.1f}", va="center", fontsize=8.5)
    ax2.set_xlabel("平均昼夜温差（℃）")
    ax2.set_title("昼夜温差对比")
    ax2.set_xlim(0, max(df2["avg_range"]) * 1.2)
    return _save(fig, path)


# ------------------------------------------------------------------ 图4 出行指数
def fig_travel_index(sdf: pd.DataFrame, path: Path) -> Path:
    pivot = sdf.pivot_table(index="city_name", columns="forecast_date", values="score")
    order = sdf.drop_duplicates("city_name").sort_values("score", ascending=False)["city_name"]
    pivot = pivot.reindex([c for c in order if c in pivot.index])
    labels = [f"{pd.Timestamp(d).month}/{pd.Timestamp(d).day}" for d in pivot.columns]

    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    im = ax.imshow(pivot.values, cmap="RdYlGn", vmin=30, vmax=95, aspect="auto")
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            v = pivot.values[i, j]
            if not np.isnan(v):
                color = "white" if (v >= 88 or v <= 45) else "#1F2937"
                ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=9, color=color)
    ax.set_xticks(range(len(labels)), labels)
    ax.set_yticks(range(len(pivot.index)), pivot.index)
    cbar = fig.colorbar(im, ax=ax, pad=0.02)
    cbar.set_label("出行指数（0-100）")
    ax.set_title("未来 7 天出行指数矩阵（分数越高越适宜出行）")
    ax.set_xlabel("预报日期（月/日）")
    return _save(fig, path)


# ------------------------------------------------------------------ 图5 气候异常
def fig_anomaly(anom: pd.DataFrame, city: str, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(9.6, 4.6))
    colors = [PALETTE["orange"] if v > 0 else PALETTE["blue"] for v in anom["delta"]]
    bars = ax.bar(range(len(anom)), anom["delta"], color=colors, width=0.6)
    ax.axhline(0, color="#334155", lw=1)
    ax.axhline(1, color=PALETTE["orange"], ls=":", lw=0.9)
    ax.axhline(-1, color=PALETTE["blue"], ls=":", lw=0.9)
    for i, (v, b) in enumerate(zip(anom["delta"], bars)):
        ax.text(i, v + (0.15 if v >= 0 else -0.25), f"{v:+.1f}", ha="center", fontsize=8.5)
    ax.set_xticks(range(len(anom)), [f"{d[5:]}\n{w}" for d, w in zip(anom["date"], anom["weekday"])])
    ax.set_ylabel("较常年同期偏差（℃）")
    ax.set_title(f"{city}未来 7 天冷暖距平（相对近两年同期均值）")
    ax.grid(axis="y", alpha=0.25)
    return _save(fig, path)


# ------------------------------------------------------------------ 图6 架构图
def fig_architecture(path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(11, 6.2))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 106)
    ax.axis("off")

    def box(x, y, w, h, title, body, color):
        patch = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.6,rounding_size=1.6",
                               linewidth=1.2, edgecolor=color, facecolor=color + "14")
        ax.add_patch(patch)
        ax.text(x + w / 2, y + h - 4.2, title, ha="center", va="top", fontsize=11,
                fontweight="bold", color=color)
        ax.text(x + w / 2, y + h - 9.5, body, ha="center", va="top", fontsize=8.6,
                color="#334155", linespacing=1.55)

    def arrow(x1, y1, x2, y2, color="#94A3B8"):
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=14,
                                     lw=1.3, color=color, shrinkA=0, shrinkB=0))

    box(2, 72, 27, 22, "数据源", "中国天气网 · 7 天预报\n天气后报 · 历史月度天气\n（12 城市 / 24 个月）", PALETTE["dark"])
    box(36, 72, 27, 22, "采集层 crawler", "请求封装 · 限速 · 重试\nrobots 校验 · 页面缓存\nHTML 解析 · 断点续爬", PALETTE["blue"])
    box(70, 72, 27, 22, "存储层 SQLite", "cities / forecasts\nhistory / crawl_log\ncrawl_state", PALETTE["teal"])

    box(70, 38, 27, 22, "分析层 analysis", "气候画像 · 月度趋势\n降水与温差统计\n出行指数 · 冷暖距平", PALETTE["orange"])
    box(36, 38, 27, 22, "Agent 层", "意图识别 · 槽位抽取\n工具调用 · 反思校验\n简报生成", "#7C3AED")
    box(2, 38, 27, 22, "输出层", "图表 PNG · 统计 JSON\n出行简报 Markdown\n实验报告 DOCX", PALETTE["gray"])

    box(20, 4, 60, 20, "用户交互", "CLI 问答  |  一键脚本 run_all.ps1  |  离线规则规划器（无 API Key 可运行）", "#334155")

    arrow(29.5, 83, 35.5, 83)
    arrow(63.5, 83, 69.5, 83)
    arrow(83, 71.5, 83, 60.5)
    arrow(69.5, 49, 63.5, 49)
    arrow(35.5, 49, 29.5, 49)
    arrow(50, 37.5, 50, 24.5)

    ax.text(50, 104, "城市天气与出行建议爬虫 Agent — 系统架构", ha="center", va="top",
            fontsize=14, fontweight="bold")
    return _save(fig, path)
