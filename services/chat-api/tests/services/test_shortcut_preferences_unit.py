import unittest

from app.services.shortcut_preferences import apply_preferences, normalize_groups


class ShortcutPreferenceTests(unittest.TestCase):
    def test_legacy_entry_lock_promotes_to_group(self):
        entries = [{"id": "a", "categoryKey": "work", "locked": True}]
        groups = normalize_groups([{"key": "work", "label": "Work"}], entries)
        self.assertTrue(groups[0]["locked"])

    def test_locked_group_ignores_personal_order(self):
        entries = [
            {"id": "a", "categoryKey": "locked"}, {"id": "b", "categoryKey": "locked"},
            {"id": "c", "categoryKey": "open"}, {"id": "d", "categoryKey": "open"},
        ]
        groups = [{"key": "locked", "locked": True}, {"key": "open", "locked": False}]
        rows, _, prefs = apply_preferences(entries, groups, {"group_orders": {"locked": ["b", "a"], "open": ["d", "c"]}})
        self.assertEqual([row["id"] for row in rows], ["a", "b", "d", "c"])
        self.assertNotIn("locked", prefs["groupOrders"])

    def test_personal_group_exists_without_entries(self):
        rows, groups, prefs = apply_preferences([], [], {"personal_group": {"key": "personal", "label": "Mine"}})
        self.assertEqual(rows, [])
        self.assertEqual(groups[-1]["label"], "Mine")
        self.assertEqual(prefs["personalGroup"]["key"], "personal")

    def test_personal_group_limits_six(self):
        personal = [{"id": str(i), "type": "prompt"} for i in range(8)]
        rows, _, _ = apply_preferences([], [], {"personal_entries": personal})
        self.assertEqual(len(rows), 6)


if __name__ == "__main__":
    unittest.main()
