from __future__ import annotations

import unittest

from app.api.workflow_check_messages import workflow_check_fallback, workflow_check_language_instruction


class WorkflowCheckMessagesTests(unittest.TestCase):
    def test_fallbacks_and_prompt_instruction_follow_response_language(self) -> None:
        self.assertEqual(workflow_check_fallback("logic_label", "zh-CN"), "需要澄清")
        self.assertEqual(workflow_check_fallback("logic_label", "en-US"), "Needs clarification")
        self.assertIn("English", workflow_check_language_instruction("en-US"))
        self.assertIn("Chinese", workflow_check_language_instruction("zh-CN"))


if __name__ == "__main__":
    unittest.main()
