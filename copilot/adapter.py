# -*- coding: utf-8 -*-
"""微信适配层 —— 唯一接触 wechatauto-replica 的模块。

设计意图：上游库与微信版本强耦合，将来若失配，只重写本文件即可，
业务层（ai.py / main.py）不感知上游 API。

上游 API 速记：
  WeChatDB()                     # 解密本地库（首次约 6s，之后即时）
  db.get_sessions(limit)         # 会话列表 [{username, unread, summary,...}]
  db.search_contact(name)        # 昵称/备注 -> [{username,...}]
  db.get_nickname(sid)           # sender_id -> 昵称
  Listener(db, interval)         # 增量轮询，水位落盘，重启不重复推
  lst.add_listener(username, cb) / add_all(cb, discover=True)
  lst.start() / lst.stop()
  lst._run()                     # 上游用 _stop.wait(interval) 睡眠：
                                 # 回调在 worker 线程里改 interval 不会唤醒它
  quick_send(content, who, verify=False)   # UIA+OCR 发送
  msg["type"]                    # 中文字符串："文本"/"图片"/"文件"，不是数字 1
  msg["sender_id"]               # 2 = 自己；其余为对方
  _run_callbacks 调用 cb(msg, listener)    # 回调第二个参数就是监听器实例
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

# 文本类型白名单：上游返回中文字符串，旧版/自定义消息可能是数字 1
TEXT_TYPES = (1, "1", "文本")


class WeChatAdapter:
    def __init__(self, db_dir: str | None = None):
        from wechatauto.db import WeChatDB
        self.db = WeChatDB(db_dir=db_dir)
        info = self.db.get_self_info()
        self.self_name = info.get("nick_name") or info.get("username") or ""
        self.listener = None
        log.info("微信账号: %s", self.self_name)

    # ---------- 名称解析 ----------

    def resolve(self, name: str) -> str:
        """昵称/备注/wxid -> 会话 username（Listener 只认 username）。"""
        sessions = {s["username"] for s in self.db.get_sessions(limit=500)}
        if name in sessions:
            return name
        hits = self.db.search_contact(name)
        if hits:
            return hits[0]["username"]
        log.warning("联系人「%s」未解析到会话，原样使用", name)
        return name

    def contact_name(self, username: str) -> str:
        """会话 username -> 联系人显示名（检索与 prompt 用）。"""
        try:
            nick = self.db.get_nickname(username)
            if nick:
                return nick
        except Exception:
            pass
        return username

    def sender_name(self, msg: dict) -> str:
        sid = msg.get("sender_id")
        if sid == 2:
            return "我"
        nick = self.db.get_nickname(sid) if isinstance(sid, str) else None
        return nick or f"用户{sid}"

    # ---------- 监听（自适应 tick） ----------

    @property
    def conversation_active(self) -> bool:
        """最近 active_window 内是否有新消息（业务层据此选冷却档）。"""
        lst = self.listener
        return bool(lst and getattr(lst, "active", False))

    def mark_activity(self) -> None:
        """业务层「检测到对话」的统一入口：刷新活跃时间 + 提速 + 唤醒轮询。

        幂等，可重复调（分发层和 on_msg 都会调，避免冷却档位依赖调用顺序）。
        """
        lst = self.listener
        if lst is not None and hasattr(lst, "notify"):
            lst.notify()

    def listen(self, chats: list[str], callback: Callable[[dict], None],
               idle_interval: float = 60.0, active_interval: float = 10.0,
               active_window: float = 600.0) -> "object":
        """启动监听。chats 为空 -> 监听全部会话（跳过群聊）。

        检测节奏自适应：
          - 启动 / 有新消息（检测到对话）-> active_interval（默认 10s）查库一次
          - 连续 active_window（默认 600s = 10 分钟）无新消息 -> idle_interval（60s）
          - 静默期间来消息会立刻唤醒轮询线程，不会傻等满 60s 才发现提速

        callback(msg) 在后台线程执行；msg 含
        username / sender_id / type / content / create_time。
        """
        from wechatauto.db import Listener

        idle = max(1.0, float(idle_interval))
        fast = max(0.5, min(float(active_interval), idle))
        window = max(1.0, float(active_window))

        class AdaptiveListener(Listener):
            """1s 心跳 + 独立 wake 事件，查库间隔按 gap 动态控制。

            上游 `_run` 是 `_stop.wait(self.interval)`：回调在 worker 线程里
            改 interval 时，轮询线程可能已经睡进 60s，提速要等下一轮才生效。
            这里把睡眠换成可唤醒的 1s 心跳（几乎无开销），notify() 能立即
            打断并触发一次查库，所以「检测到对话 -> 提速」没有延迟。
            """

            def __init__(self, *a, **kw):
                self._idle = idle
                self._fast = fast
                self._window = window
                self._wake = threading.Event()
                # 启动先按活跃档：避免重启后第一条消息要等满 60s
                self._gap = self._fast
                self._last_active = time.time()
                self._last_poll = 0.0
                super().__init__(*a, interval=self._fast, **kw)

            @property
            def active(self) -> bool:
                return time.time() - self._last_active < self._window

            @property
            def gap(self) -> float:
                return self._gap

            def refresh_gap(self) -> bool:
                """静默超时则降频；返回是否发生切换（便于日志与测试）。"""
                if self._gap != self._idle and not self.active:
                    old = self._gap
                    self._gap = self._idle
                    self.interval = self._idle
                    log.info("轮询降频 %.0fs -> %.0fs（%.0f 分钟无新消息）",
                             old, self._idle, self._window / 60)
                    print(f"⏱ 检测降频: {old:.0f}s -> {self._idle:.0f}s"
                          f"（{self._window / 60:.0f} 分钟无新消息）", flush=True)
                    return True
                return False

            def notify(self) -> None:
                """每收到一条新消息就调：刷新活跃时间 + 提速 + 唤醒轮询。"""
                self._last_active = time.time()
                if self._gap != self._fast:
                    old = self._gap
                    self._gap = self._fast
                    self.interval = self._fast
                    log.info("检测到对话，轮询提速 %.0fs -> %.0fs", old, self._fast)
                    print(f"⏱ 检测到对话，检测提速: {old:.0f}s -> {self._fast:.0f}s",
                          flush=True)
                self._wake.set()

            def _run(self) -> None:
                while not self._stop.is_set():
                    self.refresh_gap()
                    now = time.time()
                    if now - self._last_poll >= self._gap:
                        try:
                            self._poll_once()
                        except Exception as exc:
                            sys.stderr.write("listener poll error: %r\n" % exc)
                        self._last_poll = time.time()
                    self._wake.wait(1.0)
                    self._wake.clear()

            def stop(self) -> None:
                self._wake.set()
                super().stop()

        lst = AdaptiveListener(self.db)
        self.listener = lst

        if chats:
            for name in chats:
                username = self.resolve(name)
                # 上游回调签名 cb(msg, listener)：先 notify 提速，再走业务层
                lst.add_listener(
                    username,
                    lambda m, _l, u=username: (_l.notify(), callback(m)))
                log.info("监听: %s -> %s", name, username)
        else:
            def _guard(msg: dict, lst_):
                # 图片/群聊也算「有动静」，先提速再按规则过滤
                lst_.notify()
                if msg.get("username", "").endswith("@chatroom"):
                    return
                if msg.get("type") not in TEXT_TYPES:
                    return
                callback(msg)

            lst.add_all(_guard, discover=True)
            log.info("全局监听: 已开启（自动发现新会话，跳过群聊）")

        lst.start()
        return lst

    # ---------- 发送 ----------

    def send(self, content: str, who: str, verify: bool = True) -> bool:
        """发送文本。UIA 优先 + OCR 回退；verify 用本进程已解密的库回读留痕。

        ⚠️ 两个坑（2026-11-04 实测）：
        1) quick_send 的 who 必须是「会话显示名」（昵称/备注），不是 wxid：
           open_chat 拿它去侧栏/搜索框找人，传 wxid 会 3 次「侧栏未确认打开」
           后把搜索词粘进聊天输入框并放弃发送。
        2) 上游 verify=True 会自己调 auto_detect_db_dir() 找库目录，若本机数据目录
           不在默认位置（通过 WECHAT_DB_DIR 显式指定），上游探测不到 -> RuntimeError
           「未找到微信数据库目录」-> 明明 UIA 已经发出去，却返回失败。
           所以这里固定 verify=False，用自己的 self.db 回读（只记日志）。
        """
        from wechatauto.guia import quick_send
        target = self.contact_name(who)
        if target == who:
            log.warning("发送目标 %s 未解析出显示名，quick_send 可能打不开会话", who)
        log.info("发送目标: %s -> %s", who, target)
        since = time.time()
        ok = bool(quick_send(content, target, verify=False))
        if ok and verify:
            self._note_landed(who, content, since)
        return ok

    def _note_landed(self, who: str, content: str, since: float,
                     timeout: float = 4.0) -> None:
        """回读只用于留痕，绝不把「UIA 已提交发送」改判成失败。

        本地库视图有同步延迟，误报失败会让人手动补发一遍 —— 重复发比
        漏报严重得多，所以读不到一律按已发送处理。
        """
        needle = (content or "").strip()[:24]
        if not needle:
            return
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                rows = self.db.get_messages(who, limit=6)
                for r in rows:
                    if (needle in str(r.get("content", ""))
                            and (r.get("create_time") or 0) >= since - 2):
                        log.info("发送回读确认: %s", needle)
                        return
            except Exception as e:
                log.debug("发送回读跳过: %s", e)
                return
            time.sleep(0.5)
        log.info("UIA 已提交发送，本地库 %.0fs 内未回读到（视图延迟常见，按已发送处理）: %s",
                 timeout, needle)
