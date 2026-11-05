# -*- coding: utf-8 -*-
"""回复决策上下文层 —— 代码/数据分离后的唯一数据入口。

所有个人数据都从 `DATA_DIR`（数据仓库根目录）读取，代码仓库里没有任何
数据文件、没有硬编码的个人路径。契约见 DATA_CONTRACT.md：

  DATA_DIR/口径包.md          固定口径（人工维护，改文件即生效）
  DATA_DIR/examples.md        风格 few-shot
  DATA_DIR/contacts/<名字>.md 联系人专属档案
  DATA_DIR/notes/ 或 JOB_DOCS_DIR   关键词检索语料

未配置 DATA_DIR 时全部返回空串，AI 用内置通用示例兜底，程序照常运行，
适合「只跑逻辑、不挂个人数据」的场景（含公开仓库的第一次试跑）。
"""
from __future__ import annotations

import re
from pathlib import Path

# 单字停用词必须用 set(字符串) 逐字拆开，不能对一整串调 .split()
# （之前 .split() 无空格可切，整串变成一个元素，停用词等于全部失效）。
_STOP = set("的了吗呢吧啊呀嗯哦你我他她它们这那") | {
    "您好", "谢谢", "你好", "在吗", "请问", "方便", "一下", "可以", "看看",
    "好的", "嗯嗯", "哈哈", "这个", "那个", "什么", "怎么",
}

# 文件名里出现这些词的记录优先检索（投递作战/面试追踪类）
_PRIORITY_HINTS = ("投递", "清单", "追踪", "跟进", "面试", "问答库", "名单")


def data_root() -> Path | None:
    """数据仓库根目录。只认 config.SETTINGS（load_env 已把环境变量同步进去），
    这样离线单测可以干净地 patch SETTINGS，不会被宿主环境变量干扰。"""
    from .config import SETTINGS
    raw = SETTINGS.get("DATA_DIR", "").strip()
    return Path(raw).expanduser() if raw else None


def _data_path(rel: str) -> Path | None:
    root = data_root()
    return root / rel if root else None


def load_pack() -> str:
    """读口径包。每次触发现读，文件改了立即生效。"""
    fp = _data_path("口径包.md")
    if fp is None:
        return ""
    try:
        return fp.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def load_examples() -> str:
    """读风格 few-shot（缺失时 ai.py 用通用虚构示例兜底）。"""
    fp = _data_path("examples.md")
    if fp is None:
        return ""
    try:
        return fp.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


_BAD_CHARS = '\\/:*?"<>|'


def load_contact_pack(contact: str) -> str:
    """读联系人专属档案（contacts/<名字>.md），优先级高于通用口径包。

    文件名里的非法字符（如备注名中的 |）替换为 _，两套名字都尝试命中。
    """
    if not contact:
        return ""
    root = data_root()
    if root is None:
        return ""
    sanitized = "".join("_" if c in _BAD_CHARS else c for c in contact)
    for name in dict.fromkeys([contact, sanitized]):
        fp = root / "contacts" / f"{name}.md"
        try:
            return fp.read_text(encoding="utf-8").strip()
        except OSError:
            continue
    return ""


def job_dir() -> Path | None:
    """检索语料目录：JOB_DOCS_DIR 显式配置优先，否则用数据仓库的 notes/。"""
    from .config import SETTINGS
    raw = SETTINGS.get("JOB_DOCS_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    root = data_root()
    return root / "notes" if root else None


def _keywords(text: str, max_kw: int = 24) -> list[str]:
    """从文本抽检索词：中文连续段 + 其 2/3/4 字滑窗，外加英数词。

    中文没有空格，整段（如「方便聊聊岗位职责吗」）拿去 grep 几乎永远不命中，
    必须切成 n-gram 才能和笔记里的「岗位职责」「薪资」这类短语对上。
    """
    runs = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_]{1,}", text)
    out: list[str] = []

    def add(c: str):
        if len(c) < 2 or c in _STOP or c in out or len(out) >= max_kw:
            return
        out.append(c)

    for r in runs:
        add(r.strip())
        if re.fullmatch(r"[\u4e00-\u9fff]+", r):
            for size in (2, 3, 4):
                for i in range(len(r) - size + 1):
                    add(r[i:i + size])
    return out


def retrieve(contact: str, incoming: str, max_lines: int = 12) -> str:
    """A 兜底：拿联系人名 + 对方消息关键词去语料目录 grep，返回命中行摘要。

    找不到命中返回空串（口径包已覆盖通用场景，检索只是补充）。
    """
    root = job_dir()
    if root is None or not root.exists():
        return ""
    kws = _keywords(contact) + _keywords(incoming)
    if not kws:
        return ""
    # 联系人名（如 公司名/HR名）权重高，单独列出保证命中
    scored: list[tuple[int, str]] = []
    files = sorted(root.rglob("*.md"))
    for fp in files:
        name_bonus = 2 if any(h in fp.name for h in _PRIORITY_HINTS) else 0
        try:
            lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for ln in lines:
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            hits = sum(1 for k in kws if k in s)
            if hits:
                scored.append((hits + name_bonus,
                               f"[{fp.name}] {s[:150]}"))
    if not scored:
        return ""
    scored.sort(key=lambda x: -x[0])
    seen: set[str] = set()
    out: list[str] = []
    for _, line in scored:
        key = line[:60]
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
        if len(out) >= max_lines:
            break
    return "\n".join(out)
