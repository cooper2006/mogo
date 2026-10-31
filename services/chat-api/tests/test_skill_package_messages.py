from __future__ import annotations

import unittest

from app.api.skill_package_messages import skill_package_message


class SkillPackageMessagesTests(unittest.TestCase):
    def test_structured_error_message_respects_language(self) -> None:
        self.assertEqual(skill_package_message("zip_required", "zh-CN"), "请选择 ZIP 格式的 Skill 安装包")
        self.assertEqual(skill_package_message("zip_required", "en-US"), "Select a Skill installation package in ZIP format")


if __name__ == "__main__":
    unittest.main()
