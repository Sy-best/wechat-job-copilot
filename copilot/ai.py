# -*- coding: utf-8 -*-
"""AI 回复建议层 —— DeepSeek OpenAI 兼容接口。

注意：模型名用 deepseek-flash / deepseek-v4-pro，
旧别名 deepseek-chat 已被 API 拒绝（2026-10-30 实测）。

回复决策依据（2026-11-03 起）：
- copilot/口径包.md  固定口径（人工维护，每次触发现读）
- context.retrieve() 按联系人/消息关键词去找工作目录检索命中行

2026-11-04 去 AI 腔改版：抽象要求换成硬约束 + 真人示例 + 连发合并规则。
2026-11-04 二次改版：口径包策略句被当话术照抄、薪资 few-shot 本身是 HR 腔，
改为「内部笔记不可转述」+ AI 腔负例对照 + 程序化风格守门（命中自动重写一次）。
"""
from __future__ import annotations

import logging
import re
import requests

from . import context

log = logging.getLogger(__name__)

BASE_PROMPT = """你在替一个真实的人用微信打字回复 HR / 猎头。目标是让对方觉得在跟人聊天，不是跟 AI 对话。

【怎么说 · 硬规则，逐条遵守】
1. 一条回复只做一件事：要么答一句，要么反问一句。不要又报数字又反问，不要一次说两件事。
2. 默认 1 句，最多 2 句，40 字以内。能 10 个字说完就别写 20 个。
3. 口语短句，一句话最多一个逗号。禁分号、破折号、冒号、编号、括号、引号、markdown。
4. 禁书面连接词：不过、另外、同时、此外、首先、其次、综上、整体、基于、结合、针对、关于。
   也不要「也想先…」「还想再…」「具体看…」这种铺垫。
5. 禁职场客套：方便、麻烦、您、请问、期待、感谢、对齐、进一步、咱们、希望有机会、细节。
6. 禁 HR 黑话：匹配度、判断、评估、了解下、岗位职责、职责、薪资范围、预算、区间、薪酬结构、期望年包、目标薪资、这块、这一块、方面、主要是。
7. 不要复述对方问题，不要解释自己为什么这么答，不要追加邀请或固定结尾。
   「方便的话我把简历发您」「细节可以电话聊」「您看可以吗」一律不要。
8. 简历数据只在被问到时给，一次最多带一个数字。
   被问薪资时先只反问一句对方给多少，不主动报自己的数字；对方给了数或坚持要才报。
9. 用「你」不用「您」。可以用「对」「嗯」「就」「挺」，但别每条都加。
10. 不确定的事就说不了解或没做过，不要编，也不要拿「可以电话细聊」糊弄。
11. 只输出回复正文，纯文本，不要前缀、解释、引号。
12. 别把自己上一轮说过的话原样再说一遍。对方换个说法追问时，换个说法答，或只补一句。

【决策依据怎么用】
下面全是你自己的内部笔记，写给你看的，不是可以发出去的话。
只用来核对事实：离职原因、到岗时间、薪资数字、项目数据。
- 带【内部】的条目只用来判断，一个字都不能出现在回复里。
- 笔记里的书面词组、策略句、检索命中的笔记原文，一律不要沿用措辞；要表达就用大白话。
- 每次只取被问到的那一句，不要把整段搬出来。
"""

# few-shot 例子属于个人数据（可能含真实履历），放到 copilot/examples.md（gitignored）；
# 未配置时用这份完全虚构的通用示例，保证开源仓库不含任何个人信息。
GENERIC_EXAMPLES = """【像人说话的例子 · 照这个语气写】
对方：可以说一下你的项目经历吗
回：上家做了 3 年客户端，现在这家做工具链。

对方：你只有两段工作经历吗
回：对，就两段。

对方：为什么上家待了 3 年
回：每个版本都有新东西做，就一直留下来了。

对方：你的目标薪资是多少
回：你们这边给到多少？

对方：在吗
回：在的。

【这些是 AI 腔，一个字都别学】
✗ 期望年包 30 以上；不过也想先了解下这个岗位的职责和薪资范围，方便判断匹配度。
✗ 方便的话我把简历发您，细节也可以电话聊。
这几句的毛病：用分号把两件事拼一起、职场客套、HR 黑话、一次问两件、书面连接词。
"""

BATCH_PROMPT = """
【本批是对方连着发来的多条消息】
按真人聊天的样子回一条：接住最后一句，前面没答的关键点最多顺带带一句。
不要逐条编号，不要「针对你的三个问题」「关于第一点」，不要把几条问题重新各答一遍。
能合成一句短话就合成一句，长度仍按上面的 40 字规则。
"""

# 程序化风格守门：光靠 prompt 挡不住，命中就带纠偏重写一次
_SMELL_WORDS = (
    "不过", "另外", "同时", "此外", "首先", "其次", "综上", "整体来说",
    "基于", "结合", "针对", "关于", "也想", "还想", "具体看", "先了解",
    "方便", "麻烦", "您", "请问", "期待", "感谢", "对齐", "进一步",
    "咱们", "希望有机会", "细节",
    "匹配度", "判断", "评估", "了解下", "岗位职责", "职责", "薪资范围",
    "预算", "区间", "薪酬结构", "期望年包", "目标薪资", "这块", "这一块",
    "方面", "主要是",
)
_SMELL_PATTERNS = (
    r"[；;]", r"[—–]", r"[:：]", r"[（()）]", r"[「」“”\"']",
    r"[【】]", r"^\s*\d+[\.、]", r"\*",
)
_RETRY_HINT = (
    "上一句太像 AI 写的了。重写一句大白话：15 字以内，只做一件事（答或问），"
    "去掉所有客套和书面词，不要分号，不要同时说两件事。只输出正文。"
)
_RETRY_HINT_BATCH = (
    "上一句太像 AI 写的了。重写：两句以内的大白话，把对方问的关键点说到，"
    "去掉客套和书面词，不要分号、不要编号、不要逐条重答。只输出正文。"
)


def _smell(text: str, max_len: int, comma_limit: int) -> list[str]:
    """返回命中的 AI 腔特征；空列表表示干净。"""
    hits = [w for w in _SMELL_WORDS if w in text]
    hits += [p for p in _SMELL_PATTERNS if re.search(p, text, flags=re.M)]
    if len(text) > max_len:
        hits.append(f"超{len(text)}字")
    if text.count("，") > comma_limit:
        hits.append("逗号过多")
    return hits


def _system(contact: str, retrieved: str) -> str:
    parts = [BASE_PROMPT, "\n" + (context.load_examples() or GENERIC_EXAMPLES),
             "\n【你的内部笔记 · 不是可以发出去的话】"]
    parts.append(context.load_pack() or "（口径包缺失，按通用求职礼仪回复，不要给承诺性数据）")
    cp = context.load_contact_pack(contact)
    if cp:
        parts.append(f"\n【联系人「{contact}」专属档案（优先级最高，与其它依据冲突时以此为准，同样不可转述）】")
        parts.append(cp)
    if retrieved:
        parts.append("\n【相关记录检索命中（笔记原文，只提取事实，不要沿用措辞）】")
        parts.append(retrieved)
    if contact:
        parts.append(f"\n当前对话对象：{contact}")
    return "\n".join(parts)


MAX_CONTEXT_MSGS = 10


class Replier:
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com",
                 model: str = "deepseek-flash", temperature: float = 0.7):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature

    # ---------- 对外接口 ----------

    def suggest(self, history: list[dict], incoming: str,
                contact: str = "") -> str:
        """单条消息。history: [{role:'me'|'them', text}]，不含 incoming 时会自动补上。"""
        retrieved = context.retrieve(contact, incoming)
        msgs = [{"role": "system", "content": _system(contact, retrieved)}]
        self._append_history(msgs, history)
        # 调用方传入的 incoming 通常已在 history 末尾，避免同一句重复喂两遍
        if not (msgs and msgs[-1]["role"] == "user"
                and msgs[-1]["content"] == incoming):
            msgs.append({"role": "user", "content": incoming})
        return self._call(msgs, max_len=40, comma_limit=1)

    def suggest_batch(self, history: list[dict], incoming_list: list[str],
                      contact: str = "") -> str:
        """一批连发消息合并成一条回复。

        history 必须**不含**本批消息（调用方在 flush 成功后才写回历史）。
        """
        texts = [str(t).strip() for t in incoming_list if str(t).strip()]
        if not texts:
            raise ValueError("空批次，无法生成回复")
        if len(texts) == 1:
            return self.suggest(history, texts[0], contact)

        retrieved = context.retrieve(contact, " ".join(texts))
        msgs = [{"role": "system", "content": _system(contact, retrieved) + BATCH_PROMPT}]
        self._append_history(msgs, history)
        payload = (f"对方连着发来 {len(texts)} 条（按时间顺序）：\n"
                   + "\n".join(f"「{t}」" for t in texts))
        msgs.append({"role": "user", "content": payload})
        return self._call(msgs, max_len=60, comma_limit=2,
                          retry_hint=_RETRY_HINT_BATCH)

    # ---------- 内部 ----------

    @staticmethod
    def _append_history(msgs: list[dict], history: list[dict]) -> None:
        for h in history[-MAX_CONTEXT_MSGS:]:
            role = "assistant" if h["role"] == "me" else "user"
            msgs.append({"role": role, "content": h["text"]})

    def _call(self, msgs: list[dict], max_len: int = 40,
              comma_limit: int = 1, _retry: int = 0,
              retry_hint: str | None = None) -> str:
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": msgs,
                "temperature": self.temperature,
                "max_tokens": 2000,  # deepseek-flash 的推理也吃 max_tokens，太小会正文为空
            },
            timeout=60,
        )
        resp.raise_for_status()
        choice = resp.json()["choices"][0]
        content = (choice["message"].get("content") or "").strip()
        if not content:  # 兜底：思考吃光 token 之类的情况，宁可报错也不发空消息
            raise RuntimeError(
                f"AI 返回空正文 (finish_reason={choice.get('finish_reason')})")
        content = self._clean(content)

        hits = _smell(content, max_len, comma_limit)
        if hits:
            if _retry < 1:  # 带纠偏提示重写一次，不阻断发送
                log.info("风格守门命中 %s，重写一次: %s", hits, content)
                retry_msgs = msgs + [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": retry_hint or _RETRY_HINT},
                ]
                return self._call(retry_msgs, max_len=max_len,
                                  comma_limit=comma_limit, _retry=_retry + 1,
                                  retry_hint=retry_hint)
            log.warning("重写后仍有 AI 腔特征 %s: %s", hits, content)
        return content

    @staticmethod
    def _clean(s: str) -> str:
        s = (s or "").strip().strip('"').strip("'").strip()
        return re.sub(r"\*\*|`|^#+\s*|^>\s*", "", s, flags=re.M).strip()
