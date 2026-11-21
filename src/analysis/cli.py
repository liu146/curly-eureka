# -*- coding: utf-8 -*-
"""分析命令行：统计汇总 + 图表导出。

python -m src.analysis.cli
"""
from __future__ import annotations

import argparse
import json
import sys

import pandas as pd

from ..config import load_config
from ..crawler.store import Store
from ..utils import force_utf8_stdout
from . import charts, metrics


def main(argv=None) -> int:
    force_utf8_stdout()
    parser = argparse.ArgumentParser(description="天气数据统计分析")
    parser.add_argument("--skip-charts", action="store_true")
    args = parser.parse_args(argv)

    cfg = load_config()
    cfg.ensure_dirs()
    store = Store(cfg.db_path)

    counts = store.counts()
    if counts["history"] == 0 or counts["forecasts"] == 0:
        print("数据库为空，请先运行：python -m src.crawler.cli crawl-all", file=sys.stderr)
        return 1

    hdf = metrics.enrich(store.history_df(), "date")
    fdf = metrics.score_forecast(metrics.enrich(store.forecast_df(), "forecast_date"))
    profile = metrics.climate_profile(hdf)
    monthly = metrics.monthly_series(hdf)
    anom = metrics.anomaly_table(fdf, hdf, cfg.agent_cfg["default_city"])

    out = cfg.output_dir
    out.mkdir(parents=True, exist_ok=True)
    profile.to_csv(out / "climate_profile.csv", index=False, encoding="utf-8-sig")
    monthly.to_csv(out / "monthly_series.csv", index=False, encoding="utf-8-sig")
    fdf[["city_name", "forecast_date", "weekday", "weather", "temp_high", "temp_low",
         "score", "grade"]].to_csv(out / "travel_scores.csv", index=False, encoding="utf-8-sig")
    if not anom.empty:
        anom.to_csv(out / "anomaly_default_city.csv", index=False, encoding="utf-8-sig")

    summary = metrics.summarize(store, cfg)
    summary["figures"] = []

    # 采集审计统计：直接由 crawl_log 计算，避免依赖某一次运行的临时文件
    log = store.query_df("SELECT * FROM crawl_log")
    if not log.empty:
        times = pd.to_datetime(log["created_at"])
        summary["crawl"] = {
            "requests": int(len(log)),
            "ok": int((log["status"] == "ok").sum()),
            "fail": int((log["status"] == "fail").sum()),
            "rows": int(log["rows"].fillna(0).sum()),
            "seconds": round((times.max() - times.min()).total_seconds(), 1),
            "avg_ms": int(log["elapsed_ms"].fillna(0).mean()),
            "start": str(times.min()),
            "end": str(times.max()),
        }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")

    if not args.skip_charts:
        font = charts.setup_font()
        print(f"使用中文字体：{font}")
        figs = [
            charts.fig_forecast_heatmap(fdf, cfg.figures_dir / "fig1_forecast_heatmap.png"),
            charts.fig_monthly_trend(hdf, cfg.figures_dir / "fig2_monthly_trend.png"),
            charts.fig_rain_profile(profile, cfg.figures_dir / "fig3_rain_profile.png"),
            charts.fig_travel_index(fdf, cfg.figures_dir / "fig4_travel_index.png"),
        ]
        if not anom.empty:
            figs.append(charts.fig_anomaly(anom, cfg.agent_cfg["default_city"],
                                           cfg.figures_dir / "fig5_anomaly.png"))
        figs.append(charts.fig_architecture(cfg.figures_dir / "fig6_architecture.png"))
        for f in figs:
            print(f"图表已生成：{f}")

    print("\n各城市气候画像：")
    print(profile.to_string(index=False))
    print(f"\n历史数据 {len(hdf)} 行，预报数据 {len(fdf)} 行，统计摘要：{out / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
