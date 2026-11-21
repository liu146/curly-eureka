# -*- coding: utf-8 -*-
"""项目配置加载与路径管理。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class City:
    code: str
    name: str
    slug: str
    province: str
    region: str


class Config:
    """对 config.yaml 的轻量封装，附带常用路径。"""

    def __init__(self, data: Dict[str, Any], root: Path = ROOT):
        self._data = data
        self.root = Path(root)

    # ---- 原始读取 ----
    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    # ---- 领域对象 ----
    @property
    def cities(self) -> List[City]:
        return [City(**c) for c in self._data["cities"]]

    def city(self, name_or_code: str) -> Optional[City]:
        for c in self.cities:
            if name_or_code in (c.name, c.code, c.slug):
                return c
        return None

    @property
    def city_names(self) -> List[str]:
        return [c.name for c in self.cities]

    # ---- 采集参数 ----
    @property
    def crawl(self) -> Dict[str, Any]:
        return self._data["crawl"]

    @property
    def history_range(self) -> Dict[str, str]:
        return self._data["history"]

    @property
    def agent_cfg(self) -> Dict[str, Any]:
        return self._data["agent"]

    # ---- 路径 ----
    @property
    def data_dir(self) -> Path:
        return Path(os.environ.get("WTA_DATA_DIR", self.root / "data"))

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def db_path(self) -> Path:
        return Path(os.environ.get("WTA_DB", self.data_dir / "weather.db"))

    @property
    def output_dir(self) -> Path:
        return Path(os.environ.get("WTA_OUT_DIR", self.root / "output"))

    @property
    def figures_dir(self) -> Path:
        return self.output_dir / "figures"

    @property
    def report_dir(self) -> Path:
        return self.root / "report"

    @property
    def brief_dir(self) -> Path:
        p = self.output_dir / "briefs"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.cache_dir, self.output_dir, self.figures_dir):
            p.mkdir(parents=True, exist_ok=True)

    def forecast_url(self, city: City) -> str:
        return self._data["sources"]["forecast"].format(code=city.code)

    def history_url(self, city: City, yyyymm: str) -> str:
        return self._data["sources"]["history"].format(slug=city.slug, yyyymm=yyyymm)


def load_config(path: Optional[Path] = None) -> Config:
    path = Path(path) if path else ROOT / "config.yaml"
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Config(data, root=path.resolve().parent)
