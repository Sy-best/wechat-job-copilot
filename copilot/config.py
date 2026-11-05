# -*- coding: utf-8 -*-
"""分层 .env 加载器（避免引入 python-dotenv 依赖）。

代码仓库与数据仓库分离后，配置只有一个归口：数据仓库的 `.env`。

加载优先级（高 -> 低）：
  1. 真实的系统环境变量（启动脚本用它们传 DATA_DIR / 临时覆盖参数）
  2. <DATA_DIR>/ai_provider.env   AI 接口独立配置（Key / 地址 / 模型）
  3. <DATA_DIR>/.env              数据仓库主配置
  4. <代码仓库>/.env              兼容/引导文件，正常只写一行 DATA_DIR=...

代码仓库里只有空白模板（`.env.example` / `ai_provider.env.example`）+ 字段注释，
不含任何真实配置、密钥或接口地址。
"""
from __future__ import annotations

import os
from pathlib import Path

_REPO_ENV = Path(__file__).resolve().parent.parent / ".env"

SETTINGS: dict[str, str] = {}


def repo_env_path() -> Path:
    """代码仓库的引导 .env 路径（doctor 用）。"""
    return _REPO_ENV


def ai_provider_path() -> Path | None:
    """数据仓库里 AI 接口配置的路径（doctor 用）。"""
    data = os.environ.get("DATA_DIR") or SETTINGS.get("DATA_DIR")
    return Path(data).expanduser() / "ai_provider.env" if data else None


def _read(fp: Path, out: dict[str, str]) -> None:
    try:
        text = fp.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()


def load_env() -> None:
    """按优先级合并三处配置，结果同时反映到 SETTINGS 与 os.environ。"""
    SETTINGS.clear()
    merged: dict[str, str] = {}
    _read(_REPO_ENV, merged)                       # 低：代码仓库引导文件
    data = os.environ.get("DATA_DIR") or merged.get("DATA_DIR")
    if data:
        root = Path(data).expanduser()
        data_env = root / ".env"
        if data_env.exists() and data_env.resolve() != _REPO_ENV.resolve():
            _read(data_env, merged)                # 中：数据仓库主配置
        _read(root / "ai_provider.env", merged)   # 高：AI 接口独立配置（覆盖 .env 里的旧键）
    # 系统环境变量最高优先；同时保证 SETTINGS 与 os.environ 读到的值一致
    for k, v in merged.items():
        SETTINGS[k] = os.environ.get(k, v)
    if data:
        SETTINGS["DATA_DIR"] = os.environ.get("DATA_DIR", data)
    for k, v in SETTINGS.items():
        os.environ.setdefault(k, v)
