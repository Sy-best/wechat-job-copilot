# -*- coding: utf-8 -*-
"""控制台主循环：新消息 -> 入队合并 -> AI 一条回复 -> 人工确认 / 自动发送。

用法:
    python -m copilot.main                     # 监听：人工确认模式（默认）
    python -m copilot.main --auto              # 监听：自动回复模式（队列合并）
    python -m copilot.main --auto --dry-run    # 自动模式演练（只打印不发送）
    python -m copilot.main 张三 某公司          # 只监听指定联系人（覆盖 WATCH_CHATS）
    python -m copilot.main search 关键词        # 搜索联系人，拿准确昵称 / wxid
    python -m copilot.main read                # 拉取：列出最近会话
    python -m copilot.main read 张三 --ai      # 拉取 + AI 建议（不发送）

自动模式（队列，2026-11-04 起）：
  每条消息都进队列，绝不丢；同一联系人 REPLY_WINDOW(60s) 内连发的多条
  攒成一批，用一条回复统一答；单条消息静默 REPLY_QUIET_FAST(8s) 就先回。
  两次发送间隔 >= 60s。人工确认模式仍是每条即时给建议。

确认模式: s=发送 | e=编辑后发 | n/回车=忽略 | q=退出
检测节奏: 对话中 TICK_ACTIVE(10s)，静默 TICK_WINDOW(600s) 后回 TICK_IDLE(60s)。
"""
from __future__ import annotations

import logging
import os
import queue
import re
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

from .adapter import WeChatAdapter
from .ai import Replier
from .config import load_env, SETTINGS

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("copilot")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_ROOT = Path(__file__).parent.parent


def _auto_logger():
    """自动回复留痕（logging 自带线程锁，后台线程也能安全写）。"""
    lg = logging.getLogger("copilot.autosend")
    lg.setLevel(logging.INFO)
    lg.propagate = False
    if not lg.handlers:
        d = _ROOT / "logs"
        d.mkdir(exist_ok=True)
        fh = logging.FileHandler(d / f"auto_send_{time.strftime('%Y%m%d')}.log",
                                 encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        lg.addHandler(fh)
    return lg


class Copilot:
    def __init__(self, adapter: WeChatAdapter, replier: Replier,
                 auto_send: bool = False, dry_run: bool = False,
                 reply_window: int = 60, quiet_fast: int = 8,
                 max_per_chat: int = 20):
        self.adapter = adapter
        self.replier = replier
        self.history: dict[str, list[dict]] = defaultdict(list)  # username -> 上下文
        self.queue: queue.Queue = queue.Queue()       # 人工确认用
        self.flush_q: queue.Queue = queue.Queue()     # 待合并发送的批次
        self.lock = threading.Lock()
        self.auto_send = auto_send
        self.dry_run = dry_run
        self.reply_window = max(1, int(reply_window))  # 合批窗口 / 两次发送最小间隔
        self.quiet_fast = max(0, int(quiet_fast))      # 单条消息静默多久就先回
        self.max_per_chat = max_per_chat
        self.logger = _auto_logger() if auto_send else None
        # 每个联系人一个待回批次：{items, start, last, contact, flushing}
        self.pending: dict[str, dict] = {}
        self.next_send_at: dict[str, float] = {}
        self.auto_count: dict[str, int] = defaultdict(int)
        self._stop = threading.Event()
        self._workers: list[threading.Thread] = []

    # ---------- 消息入口 ----------

    def on_msg(self, msg: dict):
        # 「检测到开始对话」：先提速到活跃档（10s）。图片/文件也算有动静。
        mark = getattr(self.adapter, "mark_activity", None)
        if mark:
            mark()
        username = msg.get("username", "")
        # 上游返回的 type 是中文字符串（"文本"/"图片"/"文件"），不是数字 1。
        mtype = msg.get("type")
        if mtype not in (1, "1", "文本"):
            return
        text = str(msg.get("content") or "").strip()
        if not text:
            return
        sender = self.adapter.sender_name(msg)
        t = time.strftime("%H:%M:%S",
                          time.localtime(msg.get("create_time") or time.time()))
        print(f"\n[{t}] {sender}({username}): {text}", flush=True)
        contact = self.adapter.contact_name(username) if username else sender
        if self.logger:  # 收到即留痕，分清「没收到」还是「收到了没发出」
            self.logger.info("[收到] %s(%s) type=%s | %s",
                             contact, username, mtype, text)
        if sender == "我":
            return
        if self.auto_send:
            self._enqueue(username, contact, text)
            return
        # 人工确认模式：每条消息即时给建议，不合并
        with self.lock:
            self.history[username].append({"role": "them", "text": text})
        try:
            with self.lock:
                context = list(self.history[username])
            suggestion = self.replier.suggest(context, text, contact=contact)
        except Exception as e:
            log.error("AI 生成失败: %s", e)
            print(f"❌ AI 生成失败: {e}", flush=True)
            return
        self.queue.put((username, sender, suggestion))

    # ---------- 队列：攒批 + 定时合并 ----------

    def _enqueue(self, username: str, contact: str, text: str):
        now = time.time()
        with self.lock:
            b = self.pending.get(username)
            if not b:
                b = {"items": [], "start": now, "last": now,
                     "contact": contact, "flushing": False, "retries": 0}
                self.pending[username] = b
            b["items"].append(text)
            b["last"] = now
            b["contact"] = contact
            n = len(b["items"])
            wait = max(0.0, b["start"] + self.reply_window - now)
        if self.logger:
            self.logger.info("[入队] %s(%s) 本批第%d条 | %s",
                             contact, username, n, text)
        print(f"📥 已入队（本批第 {n} 条，最晚 {wait:.0f}s 后统一回）", flush=True)

    def start_workers(self):
        for target in (self._batch_loop, self._flush_loop):
            t = threading.Thread(target=target, daemon=True,
                                 name=f"copilot-{target.__name__}")
            t.start()
            self._workers.append(t)

    def stop_workers(self):
        self._stop.set()
        for t in self._workers:
            t.join(timeout=2)

    def _batch_loop(self):
        """每 0.5s 判定哪些批次该发，丢进 flush 队列（串行发送，UIA 不能并发）。"""
        while not self._stop.is_set():
            now = time.time()
            with self.lock:
                snapshot = [(u, dict(b)) for u, b in self.pending.items()
                            if b["items"] and not b["flushing"]]
            for username, b in snapshot:
                if self._ready(username, b, now):
                    with self.lock:
                        cur = self.pending.get(username)
                        if not cur or not cur["items"] or cur["flushing"]:
                            continue
                        cur["flushing"] = True
                    self.flush_q.put(username)
            self._stop.wait(0.5)

    def _ready(self, username: str, b: dict, now: float) -> bool:
        """60s 内最多发一次；多条等窗口，单条静默够了就先回。"""
        if now < self.next_send_at.get(username, 0):
            return False
        if len(b["items"]) > 1:
            return now - b["start"] >= self.reply_window
        if self.quiet_fast > 0:
            return now - b["last"] >= self.quiet_fast
        return now - b["start"] >= self.reply_window

    def _flush_loop(self):
        while not self._stop.is_set():
            try:
                username = self.flush_q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._flush(username)
            except Exception as e:
                log.error("批次处理异常 %s: %s", username, e)
            finally:
                self.flush_q.task_done()

    def _flush(self, username: str):
        """把一整批消息交给 AI，生成一条回复并发送。"""
        with self.lock:
            # 整批取出后直接删掉：下一批由新消息重新建，窗口从它的第一条算起
            b = self.pending.pop(username, None)
            if not b:
                return
            texts = list(b["items"])
            contact = b["contact"]
            retries = b.get("retries", 0)
            history = list(self.history[username])  # 自动模式下入队不写历史，此处不含本批
        if not texts:
            return
        print(f"\n📤 本批 {len(texts)} 条，生成一条回复 → {contact}", flush=True)
        try:
            reply = self.replier.suggest_batch(history, texts, contact=contact)
        except Exception as e:
            log.error("AI 生成失败: %s", e)
            if self.logger:
                self.logger.info("[AI失败·需人工补回] %s(%s) | 本批=%s | %s",
                                 contact, username, " / ".join(texts), e)
            # 批次已从 pending 弹出，AI 挂了不能把消息丢掉：有限次重试后转人工
            if retries < 2:
                self._requeue(username, contact, texts, b["start"], retries + 1)
                print(f"❌ AI 生成失败，本批已重新入队（第 {retries + 1}/2 次重试）: {e}",
                      flush=True)
            else:
                print(f"❌ AI 生成失败，重试已用尽，本批 {len(texts)} 条需人工补回"
                      f"（原文已留痕）: {e}", flush=True)
            return
        self._deliver(username, contact, texts, reply)
        # 批次成功后清掉重试计数（防止下一批继承旧计数）
        with self.lock:
            cur = self.pending.get(username)
            if cur and not cur["items"]:
                cur["retries"] = 0

    def _requeue(self, username: str, contact: str, texts: list[str],
                 start: float, retries: int):
        """AI 失败时把整批塞回队列；期间来的新消息要合并，不能重复更不能丢。"""
        now = time.time()
        with self.lock:
            b = self.pending.get(username)
            if b and b["items"]:
                b["items"] = texts + [x for x in b["items"] if x not in texts]
                b["start"] = min(b["start"], start)
                b["retries"] = max(b.get("retries", 0), retries)
                b["flushing"] = False
            else:
                self.pending[username] = {
                    "items": list(texts), "start": start, "last": now,
                    "contact": contact, "flushing": False, "retries": retries,
                }
        if self.logger:
            self.logger.info("[重试入队] %s(%s) retries=%d | %s",
                             contact, username, retries, " / ".join(texts))

    def _fallback(self, username: str, contact: str, texts: list[str],
                  reply: str, reason: str):
        """被护栏拦下：不发送，但把建议打出来 + 留痕，绝不静默丢。"""
        self.logger.info("[需人工] %s(%s) 原因=%s | 本批=%s | 建议=%s",
                         contact, username, reason, " / ".join(texts), reply)
        print(f"\n⚠️ 未自动发送（{reason}）\n建议: {reply}\n", flush=True)

    def _deliver(self, username: str, contact: str, texts: list[str],
                 reply: str):
        reply = (reply or "").strip()
        joined = " / ".join(texts)
        if not reply or len(reply) > 500:
            self._fallback(username, contact, texts, reply, "回复为空或超长")
            return
        if username.endswith("@chatroom"):  # 群聊绝不自动发
            self._fallback(username, contact, texts, reply, "群聊不自动回复")
            return
        with self.lock:
            if self.auto_count[username] >= self.max_per_chat:
                self._fallback(username, contact, texts, reply,
                               f"本次运行已达上限 {self.max_per_chat} 批")
                return
            self.auto_count[username] += 1
            # 一批只发一条，发完锁 60s；期间新消息继续攒，下一窗口统一回
            self.next_send_at[username] = time.time() + self.reply_window

        print(f"\n🤖 回复（覆盖 {len(texts)} 条）:\n{reply}", flush=True)
        if self.dry_run:
            self.logger.info("[DRY-RUN] %s(%s) | 本批=%s | 将发送=%s",
                             contact, username, joined, reply)
            print("🧪 演练模式：未真实发送", flush=True)
            return
        try:
            ok = self.adapter.send(reply, username)
        except Exception as e:
            self.logger.info("[发送异常] %s(%s) | 本批=%s | %s",
                             contact, username, joined, e)
            log.error("发送失败: %s", e)
            return
        self.logger.info("[%s] %s(%s) | 本批=%s | 回复=%s",
                         "已发送" if ok else "发送未确认",
                         contact, username, joined, reply)
        print("✅ 已发送" if ok else
              "❌ 发送未确认：检查微信窗口是否在前台、被别的窗口遮挡或已最小化，"
              "必要时手动补发（内容已留在上方和日志里）", flush=True)
        # 无论回读结果如何都写回历史，模型下一批能看到完整时间线
        with self.lock:
            for t in texts:
                self.history[username].append({"role": "them", "text": t})
            self.history[username].append({"role": "me", "text": reply})

    # ---------- 人工确认 ----------

    def confirm_loop(self):
        while True:
            username, sender, suggestion = self.queue.get()
            print("\n" + "-" * 60)
            print(f"AI 建议回复给 {sender}:\n{suggestion}")
            print("[s=发送 | e=编辑 | n=忽略 | q=退出] > ", end="", flush=True)
            try:
                cmd = input().strip()
            except (EOFError, KeyboardInterrupt):
                break
            if cmd == "q":
                break
            if cmd != "s" and cmd != "e":
                if cmd == "n":
                    print("(已忽略)")
                continue
            if cmd == "e":
                print("请输入修改后的内容: ", end="", flush=True)
                suggestion = input().strip()
                if not suggestion:
                    continue
            try:
                ok = self.adapter.send(suggestion, username)
            except Exception as e:
                log.error("发送失败: %s", e)
                continue
            print("✅ 已发送" if ok else "❌ 发送未确认（建议手动检查微信窗口）")
            if ok:
                with self.lock:
                    self.history[username].append({"role": "me", "text": suggestion})


def run_read(args: list[str]):
    """拉取模式：不启动监听，按需读取指定会话的最近消息。"""
    load_env()
    names: list[str] = []
    skip_next = False
    for a in args:  # 解析参数，同时把 -n 的值从联系人名单里剔除
        if skip_next:
            skip_next = False
            continue
        if a == "-n":
            skip_next = True
            continue
        if a.startswith("-"):
            continue
        names.append(a)
    n = int(args[args.index("-n") + 1]) if "-n" in args else 20
    want_ai = "--ai" in args
    adapter = WeChatAdapter(db_dir=SETTINGS.get("WECHAT_DB_DIR") or None)
    print(f"账号: {adapter.self_name}")

    if not names:
        sessions = adapter.db.get_sessions(limit=15)
        print(f"\n最近会话（用名字或 username 调 read）:")
        for s in sessions:
            print(f"  {s['username']:<28} {(s.get('summary') or '')[:30]}")
        return

    for name in names:
        username = adapter.resolve(name)
        msgs = adapter.db.get_messages(username, limit=n)
        history: list[dict] = []
        print(f"\n===== {name} ({username}) 最近 {len(msgs)} 条 =====")
        for m in msgs:
            sender = adapter.sender_name(m)
            t = time.strftime("%m-%d %H:%M", time.localtime(m["create_time"]))
            raw = str(m.get("content", ""))
            # XML 块（文件/名片/小程序等）压缩成摘要，避免刷屏；
            # 且整块 XML 绝不喂给模型（几千字符的标签会污染上下文、白烧 token）。
            if raw.startswith("<"):
                title = re.search(r"<title>(.*?)</title>", raw)
                display = f"[文件/卡片] {title.group(1)}" if title else "[文件/卡片消息]"
                compact = None
            elif len(raw) > 300:
                display, compact = raw[:120] + "…", None
            else:
                display, compact = raw, raw
            print(f"[{t}] {sender}: {display}")
            if compact:
                history.append({"role": "me" if sender == "我" else "them",
                                "text": compact})
        # get_messages 返回的是「最新在前」，喂给模型必须倒回正序时间线
        history.reverse()
        if want_ai:
            incoming = next((h["text"] for h in reversed(history)
                             if h["role"] == "them"), None)
            if not incoming:
                print("\n(对方暂无文本消息，跳过 AI 建议)")
                continue
            api_key = SETTINGS.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
            if not api_key:
                print("\n(未配置 DEEPSEEK_API_KEY，跳过 AI 建议)")
                continue
            replier = Replier(api_key=api_key, model=SETTINGS.get("MODEL", "deepseek-flash"))
            print("\n----- AI 建议回复（仅展示，不发送）-----")
            print(replier.suggest(history, incoming, contact=name))


def run_search(args: list[str]):
    """搜索联系人，拿准确昵称/备注和 wxid（配 WATCH_CHATS 用）。"""
    load_env()
    kw = " ".join(args).strip()
    if not kw:
        sys.exit("用法: python -m copilot.main search <关键词>")
    adapter = WeChatAdapter(db_dir=SETTINGS.get("WECHAT_DB_DIR") or None)
    hits = adapter.db.search_contact(kw)
    print(f"搜索「{kw}」命中 {len(hits)} 个:")
    for h in hits[:30]:
        name = h.get("nick_name") or h.get("remark") or ""
        print(f"  {h.get('username', ''):<32} {name}")


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "read":
        run_read(argv[1:])
        return
    if argv and argv[0] == "search":
        run_search(argv[1:])
        return

    load_env()
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        sys.exit("缺少 DEEPSEEK_API_KEY：请复制 .env.example 为 .env 并填入")

    flags = {a for a in argv if a.startswith("-")}
    auto = "--auto" in flags or SETTINGS.get("AUTO_SEND", "0").strip() == "1"
    dry = "--dry-run" in flags
    # 命令行给的名字覆盖 .env；名字里不能带逗号（分隔符）
    names = [a for a in argv if not a.startswith("-")]
    if names:
        chats = names
    else:
        # 逗号/顿号分隔；不能用 | 做分隔符（联系人备注名里可能带 |）
        chats = [c.strip() for c in
                 re.split(r"[,，、]", SETTINGS.get("WATCH_CHATS", "")) if c.strip()]

    # 检测节奏：对话中 10s，静默 10 分钟后降回 60s（查库频率，与回复节流无关）
    tick_idle = float(SETTINGS.get("TICK_IDLE", "60"))
    tick_active = float(SETTINGS.get("TICK_ACTIVE", "10"))
    tick_window = float(SETTINGS.get("TICK_WINDOW", "600"))
    # 回复队列：60s 窗口合批，单条静默 8s 先回
    reply_window = int(float(SETTINGS.get("REPLY_WINDOW", "60")))
    quiet_fast = int(float(SETTINGS.get("REPLY_QUIET_FAST", "8")))

    replier = Replier(api_key=api_key, model=SETTINGS.get("MODEL", "deepseek-flash"))
    adapter = WeChatAdapter(db_dir=SETTINGS.get("WECHAT_DB_DIR") or None)

    cop = Copilot(
        adapter, replier,
        auto_send=auto, dry_run=dry,
        reply_window=reply_window, quiet_fast=quiet_fast,
        max_per_chat=int(SETTINGS.get("AUTO_MAX_PER_CHAT", "20")),
    )
    listener = adapter.listen(
        chats, cop.on_msg,
        idle_interval=tick_idle, active_interval=tick_active,
        active_window=tick_window)
    if auto:
        cop.start_workers()
    print(f"\n🤖 Copilot 已启动（账号: {adapter.self_name}）")
    print("监听模式:", "指定联系人 " + ", ".join(chats) if chats else "全局（跳过群聊）")
    print(f"⏱ 检测节奏: 对话中 {tick_active:.0f}s / 静默 {tick_idle:.0f}s"
          f"（连续 {tick_window / 60:.0f} 分钟无消息降频；启动先按快档）")
    if auto:
        print(f"📥 回复队列: 每条消息都回，{reply_window}s 内连发合并成一条"
              f" | 单条静默 {quiet_fast}s 直接回"
              f" | 两次发送间隔 ≥ {reply_window}s"
              f" | 每人上限 {cop.max_per_chat} 批")
        print(f"⚡ 自动发送: {'演练 DRY-RUN，不真实发送' if dry else '已开启'}"
              f" | 群聊/图片不自动回 | 日志 logs/")
    else:
        print("人工确认: s 发送 / 回车忽略（默认，每条即时给建议）")
    try:
        if auto:
            while True:  # 自动模式无需键盘确认，主线程只负责保持进程存活
                time.sleep(1)
        else:
            cop.confirm_loop()
    except KeyboardInterrupt:
        pass
    finally:
        cop.stop_workers()
        listener.stop()
        print("已退出。")


if __name__ == "__main__":
    main()
