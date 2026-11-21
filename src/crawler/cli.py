# -*- coding: utf-8 -*-
"""爬虫命令行入口。

用法示例
--------
python -m src.crawler.cli init-db
python -m src.crawler.cli crawl-forecast --cities 北京,上海
python -m src.crawler.cli crawl-history --start 2024-11 --end 2026-10
python -m src.crawler.cli crawl-all
python -m src.crawler.cli status
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date
from pathlib import Path
from typing import List, Optional

from ..config import City, Config, load_config
from ..utils import force_utf8_stdout
from .fetcher import Fetcher, FetchError
from .parsers import parse_forecast, parse_history
from .store import Store

log = logging.getLogger("crawler")


def month_range(start: str, end: str) -> List[str]:
    """'2024-11' ~ '2026-10' -> ['202411', ..., '202610']。"""
    sy, sm = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    out = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def build(args) -> tuple:
    cfg = load_config()
    cfg.ensure_dirs()
    store = Store(cfg.db_path)
    store.init_schema()
    store.upsert_cities(cfg.cities)
    fetcher = Fetcher(
        delay=cfg.crawl["delay_seconds"],
        timeout=cfg.crawl["timeout"],
        retries=cfg.crawl["retries"],
        backoff_base=cfg.crawl["backoff_base"],
        cache_dir=cfg.cache_dir,
        cache_ttl_hours=cfg.crawl["cache_ttl_hours"],
        user_agent=cfg.crawl["user_agent"],
        obey_robots=cfg.crawl["obey_robots"],
    )
    return cfg, store, fetcher


def pick_cities(cfg: Config, names: Optional[str]) -> List[City]:
    if not names:
        return cfg.cities
    wanted = [n.strip() for n in names.replace("，", ",").split(",") if n.strip()]
    picked = []
    for n in wanted:
        c = cfg.city(n)
        if c is None:
            raise SystemExit(f"未知城市：{n}（可选：{', '.join(cfg.city_names)}）")
        picked.append(c)
    return picked


def crawl_forecast(cfg: Config, store: Store, fetcher: Fetcher, cities: List[City],
                   force: bool = False) -> dict:
    from datetime import timedelta

    ok, fail, rows = 0, 0, 0
    t0 = time.time()
    for i, city in enumerate(cities, 1):
        url = cfg.forecast_url(city)
        try:
            result = fetcher.get(url, force=force, cache_ttl=timedelta(hours=2))
            records = parse_forecast(result.text, city.code, city.name, url,
                                     fallback_date=date.today())
            n = store.upsert_forecasts(records)
            store.log("forecast", city.name, url, "ok", result.status, n, result.elapsed_ms)
            ok += 1
            rows += n
            print(f"[{i}/{len(cities)}] {city.name} 预报 {n} 天  "
                  f"{'缓存' if result.from_cache else str(result.elapsed_ms) + 'ms'}")
        except (FetchError, ValueError) as exc:
            fail += 1
            store.log("forecast", city.name, url, "fail", 0, 0, 0, str(exc))
            print(f"[{i}/{len(cities)}] {city.name} 失败：{exc}")
    stats = {"task": "forecast", "ok": ok, "fail": fail, "rows": rows,
             "seconds": round(time.time() - t0, 1)}
    print(f"预报采集完成：成功 {ok}，失败 {fail}，写入 {rows} 行，耗时 {stats['seconds']}s")
    return stats


def crawl_history(cfg: Config, store: Store, fetcher: Fetcher, cities: List[City],
                  months: List[str], force: bool = False) -> dict:
    ok, fail, rows, skipped = 0, 0, 0, 0
    t0 = time.time()
    total = len(cities) * len(months)
    idx = 0
    for city in cities:
        for ym in months:
            idx += 1
            key = f"history:{city.code}:{ym}"
            if not force and store.get_state(key) == "done":
                skipped += 1
                continue
            url = cfg.history_url(city, ym)
            try:
                result = fetcher.get(url, encoding="utf-8", force=force,
                                     cache_ttl=None)  # 历史页永久缓存
                records = parse_history(result.text, city.code, city.name, url)
                if not records:
                    raise ValueError("解析结果为空")
                n = store.upsert_history(records)
                store.set_state(key, "done")
                store.log("history", city.name, url, "ok", result.status, n, result.elapsed_ms)
                ok += 1
                rows += n
                if idx % 12 == 0 or idx == total:
                    print(f"[{idx}/{total}] {city.name} {ym} 累计 {rows} 行 "
                          f"（缓存 {fetcher.stats['cache_hits']}，失败 {fail}）")
            except (FetchError, ValueError) as exc:
                fail += 1
                store.log("history", city.name, url, "fail", 0, 0, 0, str(exc))
                print(f"[{idx}/{total}] {city.name} {ym} 失败：{exc}")
    stats = {"task": "history", "ok": ok, "fail": fail, "skipped": skipped, "rows": rows,
             "seconds": round(time.time() - t0, 1)}
    print(f"历史采集完成：成功 {ok}，失败 {fail}，跳过 {skipped}，写入 {rows} 行，"
          f"耗时 {stats['seconds']}s")
    return stats


def cmd_status(cfg: Config, store: Store) -> None:
    counts = store.counts()
    print("数据表统计：")
    for k, v in counts.items():
        print(f"  {k:12s} {v}")
    latest = store.latest_issue_date()
    print(f"  最新预报批次 {latest}")
    with store.connect() as conn:
        rows = conn.execute("SELECT status, COUNT(*) n FROM crawl_log GROUP BY status").fetchall()
        for r in rows:
            print(f"  日志 {r['status']}: {r['n']}")


def main(argv=None) -> int:
    force_utf8_stdout()
    parser = argparse.ArgumentParser(description="城市天气爬虫")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="初始化数据库")
    sub.add_parser("status", help="查看采集状态")

    p_fc = sub.add_parser("crawl-forecast", help="采集 7 天预报")
    p_fc.add_argument("--cities", help="逗号分隔的城市名，默认全部")
    p_fc.add_argument("--force", action="store_true", help="忽略缓存")

    p_hs = sub.add_parser("crawl-history", help="采集历史月度天气")
    p_hs.add_argument("--cities", help="逗号分隔的城市名，默认全部")
    p_hs.add_argument("--start", help="起始月份 YYYY-MM")
    p_hs.add_argument("--end", help="结束月份 YYYY-MM")
    p_hs.add_argument("--force", action="store_true", help="忽略断点与缓存")

    p_all = sub.add_parser("crawl-all", help="先预报后历史")
    p_all.add_argument("--start")
    p_all.add_argument("--end")
    p_all.add_argument("--force", action="store_true")

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    cfg, store, fetcher = build(args)

    if args.cmd == "init-db":
        print(f"数据库已初始化：{cfg.db_path}")
        print(f"城市 {len(cfg.cities)} 个：{', '.join(cfg.city_names)}")
        return 0

    if args.cmd == "status":
        cmd_status(cfg, store)
        return 0

    stats = []
    if args.cmd in ("crawl-forecast", "crawl-all"):
        cities = pick_cities(cfg, getattr(args, "cities", None))
        stats.append(crawl_forecast(cfg, store, fetcher, cities, force=args.force))

    if args.cmd in ("crawl-history", "crawl-all"):
        cities = pick_cities(cfg, getattr(args, "cities", None))
        start = getattr(args, "start", None) or cfg.history_range["start_month"]
        end = getattr(args, "end", None) or cfg.history_range["end_month"]
        stats.append(crawl_history(cfg, store, fetcher, cities, month_range(start, end),
                                   force=args.force))

    payload = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "fetcher": fetcher.summary(), "tasks": stats, "counts": store.counts()}
    out = cfg.data_dir / "crawl_stats.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    print(f"采集统计已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
