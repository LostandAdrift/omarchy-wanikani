"""Malformed remote data stays durable but cannot become a gradeable answer."""
import copy
import json
import unittest

from test_backend import Engine, EngineFixture, NOW, Store, UserError
from wanikani.practice import catalogue, validate_selection
from wanikani.readiness import calculate


class ContentConsistencyTests(EngineFixture, unittest.TestCase):
    def assert_unavailable(self, subject_id=2):
        subject = self.store.subject(subject_id)
        with self.assertRaises(UserError) as error:
            self.engine.ensure_study_content(subject)
        self.assertEqual("content_unavailable", error.exception.code)
        with self.assertRaises(UserError) as error:
            validate_selection(self.engine, [subject_id])
        self.assertEqual("content_unavailable", error.exception.code)
        readiness = calculate(self.engine)
        self.assertTrue(readiness["complete"])
        self.assertEqual((5, 5, 4, 1), tuple(readiness["reviews"][key] for key in ("total", "checked", "ready", "missing_text")))
        library = catalogue(self.engine, group="learned")
        row = next(item for item in library["items"] if item["id"] == subject_id)
        self.assertFalse(row["ready"])
        self.assertEqual(library["counts"]["learned"] - 1, library["ready_counts"]["learned"])
        self.assertIn("accepted answers", row["cache_note"])
        detail = self.engine.details(subject_id)
        self.assertTrue(detail["content_error"])
        self.assertIsInstance(detail["material"]["meaning_synonyms"], list)
        self.assertTrue(any(item["id"] == subject_id for item in self.engine.search(subject["data"]["characters"])))

    def test_malformed_answer_lists_and_flags_are_consistently_unavailable(self):
        original = self.store.subject(2)
        fixtures = []
        for field in ("meanings", "readings", "auxiliary_meanings"):
            fixtures.extend((field, value) for value in (None, "broken", 7, False, {}, [None], ["broken"]))
        fixtures.extend([
            ("meanings", [{"meaning": "mountain", "accepted_answer": "true"}]),
            ("meanings", [{"meaning": "mountain", "accepted_answer": 1}]),
            ("readings", [{"reading": "さん", "accepted_answer": "false"}]),
            ("readings", [{"reading": "さん", "accepted_answer": 0}]),
            ("auxiliary_meanings", [{"meaning": "ridge", "type": "allow"}]),
        ])
        for field, value in fixtures:
            with self.subTest(field=field, value=value):
                subject = copy.deepcopy(original)
                subject["data"][field] = value
                self.store.put(subject)
                before = list(self.store.db.iterdump())
                self.assert_unavailable()
                self.assertEqual(before, list(self.store.db.iterdump()))

    def test_malformed_synonyms_are_unavailable_without_breaking_search(self):
        for location in ("remote", "draft"):
            for synonyms in (None, "ridge", 1, {}, [None], [1], [{"nestedtoken": "ridge"}], [""]):
                with self.subTest(location=location, synonyms=synonyms):
                    self.store.execute("DELETE FROM resources WHERE kind='study_material'")
                    self.store.execute("DELETE FROM meta WHERE key='material_draft_2'")
                    material = {"subject_id": 2, "meaning_synonyms": synonyms}
                    if location == "remote":
                        self.store.put({"id": 990002, "object": "study_material", "data": material})
                    else:
                        self.store.set("material_draft_2", material)
                    self.assert_unavailable()
                    self.assertEqual([], self.engine.search("nestedtoken"))
                    if not isinstance(synonyms, list):
                        self.assertEqual([], self.engine.search("ridge"))

    def test_nonobject_drafts_never_become_synonyms_or_crash_surfaces(self):
        for draft in (False, 0, 5, "broken", [], ["ridge"]):
            with self.subTest(draft=draft):
                self.store.set("material_draft_2", draft)
                self.assert_unavailable()
                self.assertEqual([], self.engine.search("ridge"))

    def test_null_draft_falls_back_but_explicit_empty_draft_overrides_remote(self):
        self.store.put({"id": 990002, "object": "study_material", "data": {"subject_id": 2, "meaning_synonyms": "ridge"}})
        self.store.set("material_draft_2", None)
        self.assert_unavailable()
        self.store.set("material_draft_2", {})
        self.engine.ensure_study_content(self.store.subject(2))
        self.assertEqual(5, calculate(self.engine)["reviews"]["ready"])
        self.assertTrue(next(item for item in catalogue(self.engine, group="learned")["items"] if item["id"] == 2)["ready"])
        self.assertEqual([], self.engine.search("ridge"))
        self.assertEqual("", self.engine.details(2)["content_error"])
        self.engine.start("practice", 1, [2])
        self.assertTrue(self.engine.answer("mountain")["feedback"]["correct"])

    def test_derived_lookup_ignores_nontext_values_and_can_rebuild_them(self):
        subject = self.store.subject(2)
        subject["data"]["meanings"] = ["nestedtoken", None, {"meaning": {"nestedtoken": "bad"}, "accepted_answer": True}]
        subject["data"]["readings"] = [{"reading": 123, "accepted_answer": True}]
        self.store.put(subject)
        self.assertEqual([], self.engine.search("nestedtoken"))
        self.assertEqual([], catalogue(self.engine, group="learned", query="nestedtoken")["items"])
        document = self.store.rows("SELECT meanings,readings FROM search_documents WHERE id='2'")[0]
        self.assertEqual(([], []), (json.loads(document[0]), json.loads(document[1])))
        self.store.execute("DELETE FROM search_documents WHERE id='2'")
        self.store.close()
        self.store = Store(self.path)
        self.engine = Engine(self.store, clock=lambda: NOW)
        self.assert_unavailable()
        self.assertEqual(subject, self.store.subject(2))

    def test_malformed_optional_lists_do_not_block_valid_text_or_crash_details(self):
        original = self.store.subject(2)
        for value in (None, "broken", 5, {}, [None, "broken", {"url": []}]):
            with self.subTest(value=value):
                subject = copy.deepcopy(original)
                for field in ("pronunciation_audios", "character_images", "context_sentences", "component_subject_ids", "amalgamation_subject_ids"):
                    subject["data"][field] = value
                self.store.put(subject)
                self.engine.ensure_study_content(subject)
                self.assertEqual(5, calculate(self.engine)["reviews"]["ready"])
                detail = self.engine.details(2)
                self.assertEqual([], detail["audio"])
                self.assertEqual([], detail["images"])
                self.assertEqual([], detail["components"])
                self.assertEqual([], detail["related"])
                self.assertTrue(next(item for item in catalogue(self.engine, group="learned")["items"] if item["id"] == 2)["ready"])

    def test_malformed_required_radical_images_are_missing_on_every_surface(self):
        original = self.store.subject(1)
        for value in (None, "broken", False, {}, [None, {"url": []}]):
            with self.subTest(value=value):
                radical = copy.deepcopy(original)
                radical["data"]["characters"] = None
                radical["data"]["character_images"] = value
                self.store.put(radical)
                with self.assertRaises(UserError) as error:
                    self.engine.ensure_study_content(radical)
                self.assertEqual("content_unavailable", error.exception.code)
                readiness = calculate(self.engine)["reviews"]
                self.assertEqual((4, 0, 1), tuple(readiness[key] for key in ("ready", "missing_text", "missing_images")))
                row = next(item for item in catalogue(self.engine, group="learned")["items"] if item["id"] == 1)
                self.assertFalse(row["ready"])
                self.assertIn("radical image", row["cache_note"])
                self.assertEqual([], self.engine.details(1)["images"])

    def test_corrupted_content_keeps_partial_session_and_answer_counts_durable(self):
        self.engine.start("practice", 1, [2])
        self.engine.draft("mount")
        subject = self.store.subject(2)
        subject["data"]["meanings"] = [False]
        self.store.put(subject)
        before = list(self.store.db.iterdump())
        self.assertEqual("mount", self.engine.session_view()["draft"])
        with self.assertRaises(UserError) as error:
            self.engine.answer("mountain")
        self.assertEqual("content_unavailable", error.exception.code)
        self.assertEqual(before, list(self.store.db.iterdump()))

    def test_unused_radical_readings_remain_optional_across_surfaces(self):
        radical = self.store.subject(1)
        radical["data"]["readings"] = "unused malformed field"
        self.store.put(radical)
        self.engine.ensure_study_content(radical)
        self.assertEqual(5, calculate(self.engine)["reviews"]["ready"])
        self.assertTrue(next(item for item in catalogue(self.engine, group="learned")["items"] if item["id"] == 1)["ready"])
        self.assertEqual([], self.engine.details(1)["readings"])


if __name__ == "__main__":
    unittest.main()
