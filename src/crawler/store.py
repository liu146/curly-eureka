# -*- coding: utf-8 -*-
"""SQLite 存储层：建表、幂等写入、查询与断点状态。"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS cities (
    code       TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    slug       TEXT NOT NULL,
    province   TEXT,
    region     TEXT
);

CREATE TABLE IF NOT EXISTS forecasts (
    city_code       TEXT NOT NULL,
    issue_date      TEXT NOT NULL,
    forecast_date   TEXT NOT NULL,
    day_label       TEXT,
    weekday         TEXT,
    weather         TEXT,
    temp_high       INTEGER,
    temp_low        INTEGER,
    wind_dir_day    TEXT,
    wind_dir_night  TEXT,
    wind_level_day  TEXT,
    wind_level_night TEXT,
    icon_day        TEXT,
    icon_night      TEXT,
    source_url      TEXT,
    fetched_at      TEXT,
    PRIMARY KEY (city_code, issue_date, forecast_date)
);

CREATE TABLE IF NOT EXISTS history (
    city_code       TEXT NOT NULL,
    date            TEXT NOT NULL,
    weather_day     TEXT,
    weather_night   TEXT,
    temp_high       INTEGER,
    temp_low        INTEGER,
    wind_day        TEXT,
    wind_level_day  TEXT,
    wind_night      TEXT,
    wind_level_night TEXT,
    source_url      TEXT,
    fetched_at      TEXT,
    PRIMARY KEY (city_code, date)
);

CREATE TABLE IF NOT EXISTS crawl_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task        TEXT,
    city        TEXT,
    url         TEXT,
    status      TEXT,
    http_code   INTEGER,
    rows        INTEGER,
    elapsed_ms  INTEGER,
    message     TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS crawl_state (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_history_date ON history(date);
CREATE INDEX IF NOT EXISTS idx_history_city_date ON history(city_code, date);
CREATE INDEX IF NOT EXISTS idx_forecast_date ON forecasts(forecast_date);
"""


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    # ------------------------------------------------------------------ 写入
    def upsert_cities(self, cities: Iterable) -> None:
        rows = [(c.code, c.name, c.slug, c.province, c.region) for c in cities]
        with self.connect() as conn:
            conn.executemany(
                """INSERT INTO cities(code,name,slug,province,region) VALUES(?,?,?,?,?)
                   ON CONFLICT(code) DO UPDATE SET
                     name=excluded.name, slug=excluded.slug,
                     province=excluded.province, region=excluded.region""",
                rows,
            )

    def upsert_forecasts(self, records: List[Dict]) -> int:
        if not records:
            return 0
        cols = ["city_code", "issue_date", "forecast_date", "day_label", "weekday", "weather",
                "temp_high", "temp_low", "wind_dir_day", "wind_dir_night", "wind_level_day",
                "wind_level_night", "icon_day", "icon_night", "source_url", "fetched_at"]
        rows = [tuple(r.get(c) for c in cols) for r in records]
        placeholders = ",".join("?" * len(cols))
        updates = ",".join(f"{c}=excluded.{c}" for c in cols[3:])
        with self.connect() as conn:
            conn.executemany(
                f"""INSERT INTO forecasts({','.join(cols)}) VALUES({placeholders})
                    ON CONFLICT(city_code, issue_date, forecast_date) DO UPDATE SET {updates}""",
                rows,
            )
        return len(rows)

    def upsert_history(self, records: List[Dict]) -> int:
        if not records:
            return 0
        cols = ["city_code", "date", "weather_day", "weather_night", "temp_high", "temp_low",
                "wind_day", "wind_level_day", "wind_night", "wind_level_night", "source_url", "fetched_at"]
        rows = [tuple(r.get(c) for c in cols) for r in records]
        placeholders = ",".join("?" * len(cols))
        updates = ",".join(f"{c}=excluded.{c}" for c in cols[2:])
        with self.connect() as conn:
            conn.executemany(
                f"""INSERT INTO history({','.join(cols)}) VALUES({placeholders})
                    ON CONFLICT(city_code, date) DO UPDATE SET {updates}""",
                rows,
            )
        return len(rows)

    def log(self, task: str, city: str, url: str, status: str, http_code: int = 0,
            rows: int = 0, elapsed_ms: int = 0, message: str = "") -> None:
        from datetime import datetime
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO crawl_log(task,city,url,status,http_code,rows,elapsed_ms,message,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (task, city, url, status, http_code, rows, elapsed_ms, message,
                 datetime.now().isoformat(timespec="seconds")),
            )

    def set_state(self, key: str, value: str) -> None:
        from datetime import datetime
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO crawl_state(key,value,updated_at) VALUES(?,?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (key, value, datetime.now().isoformat(timespec="seconds")),
            )

    def get_state(self, key: str) -> Optional[str]:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM crawl_state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    # ------------------------------------------------------------------ 查询
    def query_df(self, sql: str, params: Optional[tuple] = None) -> pd.DataFrame:
        with self.connect() as conn:
            return pd.read_sql_query(sql, conn, params=params or ())

    def history_df(self, city_code: Optional[str] = None) -> pd.DataFrame:
        sql = """SELECT h.*, c.name AS city_name, c.region
                 FROM history h JOIN cities c ON c.code = h.city_code"""
        params = ()
        if city_code:
            sql += " WHERE h.city_code = ?"
            params = (city_code,)
        sql += " ORDER BY h.city_code, h.date"
        df = self.query_df(sql, params)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
        return df

    def forecast_df(self, city_code: Optional[str] = None) -> pd.DataFrame:
        sql = """SELECT f.*, c.name AS city_name, c.region
                 FROM forecasts f JOIN cities c ON c.code = f.city_code"""
        params = ()
        if city_code:
            sql += " WHERE f.city_code = ?"
            params = (city_code,)
        sql += " ORDER BY f.city_code, f.forecast_date"
        df = self.query_df(sql, params)
        if not df.empty:
            df["forecast_date"] = pd.to_datetime(df["forecast_date"])
            df["issue_date"] = pd.to_datetime(df["issue_date"])
        return df

    def counts(self) -> Dict[str, int]:
        with self.connect() as conn:
            out = {}
            for table in ("cities", "forecasts", "history", "crawl_log"):
                out[table] = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        return out

    def latest_issue_date(self) -> Optional[str]:
        with self.connect() as conn:
            row = conn.execute("SELECT MAX(issue_date) AS d FROM forecasts").fetchone()
        return row["d"] if row and row["d"] else None
