# -*- coding: utf-8 -*-
"""通用小工具。"""
from __future__ import annotations

import sys


def force_utf8_stdout() -> None:
    """Windows 控制台默认 GBK，统一改为 UTF-8，避免中文与符号乱码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream and stream.encoding and stream.encoding.lower() not in ("utf-8", "utf8"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
