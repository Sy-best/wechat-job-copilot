# -*- coding: utf-8 -*-
"""离线单测：纯逻辑回归，不需要微信在线 / 不需要 API key。

运行: .venv\\Scripts\\python -m unittest discover -s tests -v
"""
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from copilot import ai, config, context  # noqa: E402
from copilot.main import Copilot  # noqa: E402


class KeywordTests(unittest.TestCase):
    def test_chinese_ngram_breaks_long_run(self):
        # 中文整段当关键词 grep 永远不命中，必须切出 n-gram
        kws = context._keywords("方便聊聊岗位职责吗")
        self.assertIn("岗位职责", kws)
        self.assertIn("岗位", kws)
        self.assertLessEqual(len(kws), 24)

    def test_stopwords_are_individual_words(self):
        self.assertIn("好的", context._STOP)
        self.assertIn("方便", context._STOP)
        self.assertGreater(len(context._STOP), 20)  # 防 .split() 退化成 1 个整串

    def test_stopword_filtered(self):
        self.assertNotIn("好的", context._keywords("好的"))


class ConfigTests(unittest.TestCase):
    def test_job_dir_disabled_by_default(self):
        with patch.dict(config.SETTINGS, {}, clear=True):
            self.assertIsNone(context.job_dir())

    def test_job_dir_from_env(self):
        with patch.dict(config.SETTINGS, {"JOB_DOCS_DIR": "C:/tmp/job"}, clear=True):
            self.assertEqual(str(context.job_dir()), str(Path("C:/tmp/job")))


class PromptTests(unittest.TestCase):
    def test_private_examples_are_used_when_present(self):
        # 数据/代码分离：私有 few-shot 存在时优先用，缺失时退回通用示例
        with patch.object(context, "load_examples", return_value="PRIVATE_EXAMPLE_MARKER"), \
             patch.object(context, "load_pack", return_value=""), \
             patch.object(context, "load_contact_pack", return_value=""):
            s = ai._system("示例联系人", "")
        self.assertIn("PRIVATE_EXAMPLE_MARKER", s)
        self.assertNotIn("上家做了 3 年客户端", s)
        self.assertIn("硬规则", s)

    def test_generic_examples_are_fallback(self):
        with patch.object(context, "load_examples", return_value=""), \
             patch.object(context, "load_pack", return_value=""), \
             patch.object(context, "load_contact_pack", return_value=""):
            s = ai._system("", "")
        self.assertIn("像人说话的例子", s)
        self.assertNotIn("PRIVATE_EXAMPLE_MARKER", s)


class StyleGuardTests(unittest.TestCase):
    def test_ai_tone_detected(self):
        hits = ai._smell("不过也想先了解下岗位职责和薪资范围，方便判断匹配度", 40, 1)
        self.assertTrue(hits)

    def test_human_short_reply_clean(self):
        self.assertEqual(ai._smell("你们这边给到多少？", 40, 1), [])


class BatchRetryTests(unittest.TestCase):
    def test_ai_failure_batch_requeued_with_messages(self):
        c = Copilot(adapter=None, replier=None)
        c._requeue("u1", "示例联系人", ["问1", "问2"], time.time(), 1)
        self.assertEqual(c.pending["u1"]["items"], ["问1", "问2"])
        self.assertEqual(c.pending["u1"]["retries"], 1)
        # 重试期间来新消息：合并，不重复、不丢
        c._enqueue("u1", "示例联系人", "问3")
        self.assertEqual(c.pending["u1"]["items"], ["问1", "问2", "问3"])


if __name__ == "__main__":
    unittest.main()
