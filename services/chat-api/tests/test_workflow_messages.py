import unittest

from app.api.workflow_messages import localized_workflow_message


class WorkflowMessageTests(unittest.TestCase):
    def test_translates_known_status_for_english(self):
        self.assertEqual(
            localized_workflow_message("模型未返回可用节点", "en-US,en;q=0.9", "Workflow generation failed"),
            "The model returned no usable nodes",
        )

    def test_preserves_chinese_response(self):
        self.assertEqual(
            localized_workflow_message("模型未返回可用节点", "zh-CN", "Workflow generation failed"),
            "模型未返回可用节点",
        )

    def test_uses_english_fallback_for_unknown_chinese_error(self):
        self.assertEqual(
            localized_workflow_message("未知中文错误", "en-US", "Workflow check failed"),
            "Workflow check failed",
        )
