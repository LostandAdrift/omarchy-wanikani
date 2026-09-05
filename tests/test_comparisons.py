import copy
import unittest

from test_backend import EngineFixture, UserError


class ComparisonTests(EngineFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        subject = self.store.subject(6)
        subject["data"]["visually_similar_subject_ids"] = [9, 2, 3]
        self.store.put(subject)

    def test_read_only_cards_are_ordered_unique_and_use_accepted_answers(self):
        subject = self.store.subject(6)
        subject["data"]["visually_similar_subject_ids"] = [9, 9, 6, True, "2", 2]
        self.store.put(subject)
        target = self.store.subject(9)
        target["data"]["meanings"].append({"meaning": "excluded", "accepted_answer": False})
        target["data"]["readings"].append({"reading": "き", "accepted_answer": False})
        self.store.put(target)
        before = list(self.store.db.iterdump())
        cards = self.engine.details(6)["visually_similar"]
        self.assertEqual([9, 2], [card["id"] for card in cards])
        self.assertEqual(["tree"], cards[0]["meanings"])
        self.assertEqual(["もく"], [r["reading"] for r in cards[0]["readings"]])
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.assertEqual([], self.engine.details(6, False)["visually_similar"])

    def test_unfinished_graded_subjects_are_not_comparison_answers(self):
        self.engine.start("reviews", 5)
        self.engine.draft("kept partial answer")
        before = list(self.store.db.iterdump())
        cards = self.engine.details(6)["visually_similar"]
        self.assertEqual([9], [card["id"] for card in cards])
        self.assertEqual(before, list(self.store.db.iterdump()))

    def test_practice_does_not_hide_other_available_comparisons(self):
        self.engine.start("practice", 1, [2])
        self.assertEqual([9, 2, 3], [card["id"] for card in self.engine.details(6)["visually_similar"]])

    def test_access_and_malformed_resources_do_not_leak(self):
        original = self.store.subject(9)
        for field, value in [("level", 61), ("level", True), ("level", "1"),
                ("hidden_at", False), ("characters", None), ("meanings", "bad"),
                ("readings", [None, {"reading": [], "accepted_answer": True}])]:
            with self.subTest(field=field, value=value):
                item = copy.deepcopy(original)
                item["data"][field] = value
                self.store.put(item)
                self.assertNotIn(9, [card["id"] for card in self.engine.details(6)["visually_similar"]])
        self.store.put(original)
        user = self.store.get("user")
        user["data"]["subscription"]["max_level_granted"] = 1
        self.store.set("user", user)
        self.assertNotIn(9, [card["id"] for card in self.engine.details(6)["visually_similar"]])
        user["data"]["subscription"]["max_level_granted"] = 0
        self.store.set("user", user)
        with self.assertRaises(UserError):
            self.engine.details(6)

    def test_unknown_nonkanji_missing_and_malformed_links_are_ignored(self):
        original = self.store.subject(6)
        for value in (None, {}, "9", [None, {}, 4, 999999]):
            item = copy.deepcopy(original)
            item["data"]["visually_similar_subject_ids"] = value
            self.store.put(item)
            self.assertEqual([], self.engine.details(6)["visually_similar"])
        vocab = self.store.subject(4)
        vocab["data"]["visually_similar_subject_ids"] = [2]
        self.store.put(vocab)
        self.assertEqual([], self.engine.details(4)["visually_similar"])

    def test_comparison_count_is_bounded(self):
        subject = self.store.subject(6)
        subject["data"]["visually_similar_subject_ids"] = list(range(1000, 1100))
        self.store.put(subject)
        for sid in range(1000, 1100):
            item = copy.deepcopy(self.store.subject(9))
            item["id"] = sid
            self.store.put(item)
        self.assertEqual(list(range(1000, 1008)), [card["id"] for card in self.engine.details(6)["visually_similar"]])


if __name__ == "__main__":
    unittest.main()
