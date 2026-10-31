from __future__ import annotations

import unittest

from app.api.dsh_access_messages import code_capability_denied


class DshAccessMessagesTests(unittest.TestCase):
    def test_denial_respects_language(self) -> None:
        self.assertEqual(code_capability_denied("zh-CN"), "当前岗位未开通代码生成能力，本次任务未执行")
        self.assertIn("Code generation", code_capability_denied("en-US"))


if __name__ == "__main__":
    unittest.main()
