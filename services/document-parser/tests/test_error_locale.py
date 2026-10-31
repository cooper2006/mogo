from __future__ import annotations

import unittest

from app.api.error_locale import localize_detail


class ErrorLocaleTests(unittest.TestCase):
    def test_queue_error_respects_language(self) -> None:
        self.assertEqual(localize_detail("任务队列不可用", 503, "zh-CN"), "任务队列不可用")
        self.assertEqual(localize_detail("任务队列不可用", 503, "en-US"), "The task queue is unavailable")

    def test_configuration_error_preserves_capability(self) -> None:
        self.assertEqual(
            localize_detail("知识库尚未选择 embedding 模型", 422, "en-US"),
            "No embedding model has been selected for the knowledge base",
        )

    def test_unknown_chinese_does_not_leak_to_english(self) -> None:
        self.assertEqual(localize_detail("未知解析失败", 422, "en-US"), "Invalid request data")
        self.assertEqual(localize_detail({"message": "用户内容"}, 422, "en-US"), {"message": "用户内容"})

    def test_job_error_preserves_original_for_chinese_and_exposes_safe_english(self) -> None:
        original = "Embedding 请求失败: HTTP 503 内部服务错误"
        self.assertEqual(localize_detail(original, 503, "zh-CN"), original)
        self.assertEqual(localize_detail(original, 503, "en-US"), "Embedding request failed: HTTP 503")


if __name__ == "__main__":
    unittest.main()
