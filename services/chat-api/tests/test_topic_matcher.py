import unittest

from app.utils.topic_matcher import matching_rule


class TopicMatcherTests(unittest.TestCase):
    def test_synonyms_and_unicode_normalization(self) -> None:
        rules = [{"id": "medical", "terms": [{"keyword": "医疗", "synonyms": ["看病", "ＡＢＣ"]}]}]
        self.assertEqual(matching_rule("我要去看病", rules)["id"], "medical")
        self.assertEqual(matching_rule("abc", rules)["id"], "medical")

    def test_overlapping_terms_and_no_match(self) -> None:
        rules = [
            {"id": "short", "terms": [{"keyword": "股票", "synonyms": []}]},
            {"id": "long", "terms": [{"keyword": "股票行情", "synonyms": []}]},
        ]
        self.assertIsNotNone(matching_rule("查股票行情", rules))
        self.assertIsNone(matching_rule("查询天气", rules))


if __name__ == "__main__":
    unittest.main()
