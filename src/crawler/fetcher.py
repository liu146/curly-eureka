# -*- coding: utf-8 -*-
"""HTTP 采集器：限速、重试、缓存、robots.txt 校验。

设计要点
--------
1. 每个 host 维护一个"下次允许请求时间"，实现简单的令牌间隔限速；
2. 对 429/5xx/超时做指数退避重试，避免偶发网络抖动导致整批任务失败；
3. 页面落盘缓存（历史页永久、预报页按 TTL），既减少对目标站的压力，
   也让断网时依然可以复现实验；
4. 请求前检查 robots.txt（RFC 9309：4xx 视为允许、2xx 解析、5xx 视为禁止）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import time
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


class FetchError(RuntimeError):
    """请求最终失败（重试耗尽或 robots 禁止）。"""


@dataclass
class FetchResult:
    url: str
    status: int
    text: str
    encoding: str
    from_cache: bool
    elapsed_ms: int
    fetched_at: str
    crawl_delay: float = 0.0
    meta: Dict = field(default_factory=dict)


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _detect_encoding(resp: requests.Response, preferred: Optional[str] = None) -> str:
    """优先使用调用方指定编码，其次按内容嗅探，最后回退 gb18030。"""
    if preferred:
        return preferred
    ctype = resp.headers.get("Content-Type", "")
    if "charset=" in ctype.lower():
        enc = ctype.lower().split("charset=")[-1].split(";")[0].strip()
        if enc:
            return enc
    head = resp.content[:4096].decode("ascii", errors="ignore").lower()
    if "charset=utf-8" in head or "charset=\"utf-8\"" in head:
        return "utf-8"
    if "charset=gb" in head:
        return "gb18030"
    # 用严格解码试探：UTF-8 能解通就 UTF-8，否则 gb18030
    try:
        resp.content.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "gb18030"


class Fetcher:
    def __init__(
        self,
        delay: float = 1.2,
        timeout: int = 15,
        retries: int = 3,
        backoff_base: float = 1.5,
        cache_dir: Optional[Path] = None,
        cache_ttl_hours: float = 6,
        user_agent: str = "WeatherTripAgent/1.0",
        obey_robots: bool = True,
    ):
        self.delay = float(delay)
        self.timeout = int(timeout)
        self.retries = int(retries)
        self.backoff_base = float(backoff_base)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.cache_ttl = timedelta(hours=float(cache_ttl_hours))
        self.user_agent = user_agent
        self.obey_robots = obey_robots

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
                "Connection": "keep-alive",
            }
        )
        self._next_allowed: Dict[str, float] = {}
        self._robots: Dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}
        self._robots_allow_all: Dict[str, bool] = {}
        self.stats = {
            "requests": 0,
            "cache_hits": 0,
            "retries": 0,
            "robots_blocked": 0,
            "bytes": 0,
            "failed": 0,
        }
        if self.cache_dir:
            (self.cache_dir / "pages").mkdir(parents=True, exist_ok=True)
            (self.cache_dir / "robots").mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ robots
    def _robots_for(self, url: str) -> Optional[urllib.robotparser.RobotFileParser]:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base in self._robots:
            return self._robots[base]

        # 先看磁盘缓存（24 小时有效）
        cache_file = None
        if self.cache_dir:
            cache_file = self.cache_dir / "robots" / (_sha1(base) + ".json")
            if cache_file.exists():
                try:
                    payload = json.loads(cache_file.read_text("utf-8"))
                    if (datetime.now() - datetime.fromisoformat(payload["saved_at"])).total_seconds() < 86400:
                        if payload["mode"] == "allow_all":
                            self._robots[base] = None
                            self._robots_allow_all[base] = True
                            return None
                        rp = urllib.robotparser.RobotFileParser()
                        rp.parse(payload["lines"])
                        self._robots[base] = rp
                        self._robots_allow_all[base] = False
                        return rp
                except Exception:  # 缓存损坏则忽略
                    pass

        robots_url = base + "/robots.txt"
        try:
            resp = self.session.get(robots_url, timeout=min(10, self.timeout))
        except requests.RequestException as exc:
            log.warning("robots.txt 无法访问（%s），按允许处理：%s", robots_url, exc)
            self._robots[base] = None
            self._robots_allow_all[base] = True
            return None

        if 200 <= resp.status_code < 300:
            lines = resp.text.splitlines()
            rp = urllib.robotparser.RobotFileParser()
            rp.parse(lines)
            self._robots[base] = rp
            self._robots_allow_all[base] = False
            if cache_file:
                cache_file.write_text(
                    json.dumps({"mode": "parsed", "lines": lines, "saved_at": datetime.now().isoformat()},
                               ensure_ascii=False),
                    "utf-8",
                )
            return rp

        if 400 <= resp.status_code < 500:
            # RFC 9309：4xx 表示"无限制"
            log.info("%s 返回 %s，视为允许全站抓取", robots_url, resp.status_code)
            self._robots[base] = None
            self._robots_allow_all[base] = True
            if cache_file:
                cache_file.write_text(
                    json.dumps({"mode": "allow_all", "saved_at": datetime.now().isoformat()}), "utf-8"
                )
            return None

        # 5xx：保守处理为禁止
        log.warning("%s 返回 %s，按 robots 不可用处理（全站禁止）", robots_url, resp.status_code)
        self._robots[base] = None
        self._robots_allow_all[base] = False
        return None

    def can_fetch(self, url: str) -> bool:
        if not self.obey_robots:
            return True
        rp = self._robots_for(url)
        host = urlparse(url).netloc
        if host in self._robots_allow_all and self._robots_allow_all[host]:
            return True
        if rp is None:
            return False
        return rp.can_fetch(self.user_agent, url)

    def crawl_delay(self, url: str) -> float:
        rp = self._robots_for(url)
        if rp is None:
            return 0.0
        try:
            return float(rp.crawl_delay(self.user_agent) or 0.0)
        except Exception:
            return 0.0

    # ------------------------------------------------------------------ cache
    def _cache_paths(self, url: str):
        assert self.cache_dir
        key = _sha1(url)
        return self.cache_dir / "pages" / (key + ".txt"), self.cache_dir / "pages" / (key + ".json")

    def _read_cache(self, url: str, ttl: Optional[timedelta]):
        if not self.cache_dir:
            return None
        body, meta = self._cache_paths(url)
        if not (body.exists() and meta.exists()):
            return None
        try:
            info = json.loads(meta.read_text("utf-8"))
            saved = datetime.fromisoformat(info["saved_at"])
        except Exception:
            return None
        if ttl is not None and datetime.now() - saved > ttl:
            return None
        self.stats["cache_hits"] += 1
        return FetchResult(
            url=url,
            status=int(info.get("status", 200)),
            text=body.read_text("utf-8"),
            encoding=info.get("encoding", "utf-8"),
            from_cache=True,
            elapsed_ms=0,
            fetched_at=saved.isoformat(timespec="seconds"),
            crawl_delay=float(info.get("crawl_delay", 0.0)),
        )

    def _write_cache(self, result: FetchResult):
        if not self.cache_dir:
            return
        body, meta = self._cache_paths(result.url)
        body.write_text(result.text, "utf-8")
        meta.write_text(
            json.dumps(
                {
                    "url": result.url,
                    "status": result.status,
                    "encoding": result.encoding,
                    "saved_at": result.fetched_at,
                    "crawl_delay": result.crawl_delay,
                },
                ensure_ascii=False,
            ),
            "utf-8",
        )

    # ------------------------------------------------------------------ fetch
    def _wait_turn(self, url: str, extra_delay: float = 0.0) -> None:
        host = urlparse(url).netloc
        now = time.monotonic()
        wait = self._next_allowed.get(host, 0.0) - now
        if wait > 0:
            time.sleep(wait)
        delay = max(self.delay, extra_delay)
        self._next_allowed[host] = time.monotonic() + delay

    def get(
        self,
        url: str,
        encoding: Optional[str] = None,
        force: bool = False,
        cache_ttl: Optional[timedelta] = None,
    ) -> FetchResult:
        ttl = self.cache_ttl if cache_ttl is None else cache_ttl
        if not force:
            cached = self._read_cache(url, ttl)
            if cached is not None:
                log.debug("缓存命中 %s", url)
                return cached

        if not self.can_fetch(url):
            self.stats["robots_blocked"] += 1
            raise FetchError(f"robots.txt 不允许抓取：{url}")

        delay = self.crawl_delay(url)
        last_exc: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            self._wait_turn(url, delay)
            started = time.monotonic()
            try:
                resp = self.session.get(url, timeout=self.timeout)
                self.stats["requests"] += 1
                self.stats["bytes"] += len(resp.content)
                if resp.status_code in RETRY_STATUS and attempt < self.retries:
                    raise requests.HTTPError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                enc = _detect_encoding(resp, encoding)
                result = FetchResult(
                    url=url,
                    status=resp.status_code,
                    text=resp.content.decode(enc, errors="replace"),
                    encoding=enc,
                    from_cache=False,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                    fetched_at=datetime.now().isoformat(timespec="seconds"),
                    crawl_delay=delay,
                )
                self._write_cache(result)
                log.info("GET %s -> %s (%d bytes, %d ms)", url, resp.status_code, len(resp.content), result.elapsed_ms)
                return result
            except (requests.RequestException, UnicodeDecodeError) as exc:
                last_exc = exc
                if attempt >= self.retries:
                    break
                self.stats["retries"] += 1
                backoff = self.backoff_base ** attempt + random.uniform(0, 0.5)
                log.warning("请求失败（%s），%.1fs 后重试 %d/%d", exc, backoff, attempt + 1, self.retries)
                time.sleep(backoff)

        self.stats["failed"] += 1
        raise FetchError(f"抓取失败：{url}（{last_exc}）")

    def summary(self) -> Dict[str, int]:
        return dict(self.stats)
