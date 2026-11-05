# -*- coding: utf-8 -*-
"""离线单测：纯逻辑回归，不需要微信在线 / 不需要 API key。

运行: .venv\\Scripts\\python -m unittest discover -s tests -v
"""
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from copilot import ai, config, context  # noqa: E402
from copilot.main import Copilot  # noqa: E402

_REPO = Path(__file__).parent.parent


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

    def test_layered_env_priority(self):
        """系统环境变量 > ai_provider.env > 数据仓库 .env > 代码仓库引导 .env。"""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            data = base / "data"
            repo = base / "code"
            data.mkdir()
            repo.mkdir()
            (repo / ".env").write_text(
                f"DATA_DIR={data}\nWATCH_CHATS=from-bootstrap\n", encoding="utf-8")
            (data / ".env").write_text(
                "MODEL=from-main\nAI_API_KEY=old-key\n", encoding="utf-8")
            (data / "ai_provider.env").write_text(
                "AI_API_KEY=new-key\nAI_BASE_URL=https://example.invalid/v1\n"
                "AI_MODEL=custom-model\n", encoding="utf-8")
            with patch.object(config, "_REPO_ENV", repo / ".env"), \
                 patch.dict(os.environ, {}, clear=True):
                config.load_env()
                self.assertEqual(config.SETTINGS["DATA_DIR"], str(data))
                self.assertEqual(config.SETTINGS["WATCH_CHATS"], "from-bootstrap")
                self.assertEqual(config.SETTINGS["AI_API_KEY"], "new-key")
                self.assertEqual(config.SETTINGS["AI_MODEL"], "custom-model")
                self.assertEqual(config.SETTINGS["MODEL"], "from-main")

    def test_system_env_beats_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "ai_provider.env").write_text("AI_MODEL=file-model\n", encoding="utf-8")
            with patch.object(config, "_REPO_ENV", data / "missing" / ".env"), \
                 patch.dict(os.environ, {"DATA_DIR": str(data), "AI_MODEL": "env-model"}, clear=True):
                config.load_env()
                self.assertEqual(config.SETTINGS["AI_MODEL"], "env-model")


class DataRepoTests(unittest.TestCase):
    def test_all_private_data_read_from_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "口径包.md").write_text("PACK", encoding="utf-8")
            (root / "examples.md").write_text("EX", encoding="utf-8")
            (root / "contacts").mkdir()
            (root / "contacts" / "示例联系人.md").write_text("CP", encoding="utf-8")
            (root / "notes").mkdir()
            with patch.dict(config.SETTINGS, {"DATA_DIR": str(root)}, clear=True):
                self.assertEqual(context.data_root(), root)
                self.assertEqual(context.load_pack(), "PACK")
                self.assertEqual(context.load_examples(), "EX")
                self.assertEqual(context.load_contact_pack("示例联系人"), "CP")
                self.assertEqual(context.job_dir(), root / "notes")

    def test_no_data_dir_is_zero_data_mode(self):
        with patch.dict(config.SETTINGS, {}, clear=True):
            self.assertIsNone(context.data_root())
            self.assertEqual(context.load_pack(), "")
            self.assertEqual(context.load_examples(), "")
            self.assertEqual(context.load_contact_pack("示例联系人"), "")
            self.assertIsNone(context.job_dir())

    def test_replier_reads_ai_provider_config(self):
        with patch.dict(config.SETTINGS, {
            "AI_API_KEY": "k", "AI_BASE_URL": "https://example.invalid/v1/",
            "AI_MODEL": "m", "AI_TEMPERATURE": "0.3",
        }, clear=True):
            r = ai.Replier()
        self.assertEqual(r.api_key, "k")
        self.assertEqual(r.base_url, "https://example.invalid/v1")
        self.assertEqual(r.model, "m")
        self.assertEqual(r.temperature, 0.3)

    def test_explicit_args_beat_settings(self):
        with patch.dict(config.SETTINGS, {"AI_MODEL": "from-file"}, clear=True):
            r = ai.Replier(api_key="explicit", model="explicit-model")
        self.assertEqual(r.model, "explicit-model")
        self.assertEqual(r.api_key, "explicit")


class TemplatePrivacyTests(unittest.TestCase):
    def test_templates_are_blank_and_documented(self):
        for name in (".env.example", "ai_provider.env.example"):
            fp = _REPO / name
            self.assertTrue(fp.is_file(), f"缺模板 {name}")
            text = fp.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"sk-[A-Za-z0-9]{20,}", text),
                              f"{name} 里不允许出现真实 key")
            # 只查真正的个人指纹；"xwechat_files" 是微信 4.x 的通用目录名，不算隐私。
            # 这些字面量故意拆开拼，避免测试文件本身成为公开仓库里的隐私线索。
            fingerprints = ("906" + "86", "光" + "子", "盛" + "宇", "小" + "P")
            for word in fingerprints:
                self.assertNotIn(word, text)
            # 模板里不应出现任何本机绝对路径
            self.assertIsNone(re.search(r"[A-Za-z]:[\\/]{1,2}(Users|文档)[\\/]", text))
            if name == "ai_provider.env.example":
                self.assertIn("[必填]", text)
        # AI 模板三个键都要是空白占位
        t = (_REPO / "ai_provider.env.example").read_text(encoding="utf-8")
        for key in ("AI_API_KEY=", "AI_BASE_URL=", "AI_MODEL="):
            self.assertIn(key, t)
            self.assertRegex(t, re.escape(key) + r"\s*\n")

    def test_code_repo_has_no_private_markdown(self):
        leftovers = [p.name for p in (_REPO / "copilot").glob("*.md")
                     if not p.name.endswith(".example.md")]
        self.assertEqual(leftovers, [], "个人数据文件不应出现在代码仓库")


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
