# -*- coding: utf-8 -*-
"""极简 .env 加载器（避免引入 python-dotenv 依赖）。"""
from __future__ import annotations

import os

_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

SETTINGS: dict[str, str] = {}


def load_env() -> None:
    SETTINGS.clear()
    if not os.path.exists(_ENV_PATH):
        return
    with open(_ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            SETTINGS[k.strip()] = v.strip()
            os.environ.setdefault(k.strip(), v.strip())
