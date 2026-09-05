"""Independently authored grading regressions; no copied account or app fixtures.

Official behavior references (retrieved 2026-09-05):
https://knowledge.wanikani.com/wanikani/common-mistakes/
https://knowledge.wanikani.com/japanese/small_characters/
https://knowledge.wanikani.com/japanese/double-n/
https://docs.api.wanikani.com/20170710/#subjects

Numeric/negation/short-word guards are deliberately conservative local policy,
not a claim that WaniKani or Tsurukame uses an identical grading algorithm.
"""
import copy
import unittest

from test_backend import Engine, EngineFixture, NOW, Store, UserError
from wanikani.grading import grade, validate_subject_answers


def item(meaning="to enter", reading="しゅう", kind="vocabulary"):
    return {"id": 990001, "object": kind, "data": {
        "characters": "架空", "level": 1,
        "meanings": [{"meaning": meaning, "accepted_answer": True, "primary": True}],
        "readings": [{"reading": reading, "accepted_answer": True, "primary": True}],
        "auxiliary_meanings": [],
    }}


class GradingParityTests(unittest.TestCase):
    def test_numeric_value_sign_decimal_and_operator_changes_are_rejected(self):
        fixtures = [
            ("1.5 meters", "15 meters"),
            ("temperature -10", "temperature 10"),
            ("temperature 10", "temperature -10"),
            ("temperature +10", "temperature 10"),
            (".5 meters", "5 meters"),
            ("3/4 length", "34 length"),
            ("75% humidity", "75 humidity"),
            ("$20 allowance", "€20 allowance"),
            ("1,000 units", "1000 units"),
        ]
        for expected, entered in fixtures:
            with self.subTest(expected=expected, entered=entered):
                self.assertEqual("incorrect", grade(item(expected), "meaning", entered)["kind"])

    def test_numeric_normalization_preserves_equivalent_input_forms(self):
        for expected, entered in (("temperature -10", "temperature −10"), ("1.5 meters", "１．５ meters"), ("level 12", "level 12.")):
            with self.subTest(expected=expected, entered=entered):
                self.assertEqual("correct", grade(item(expected), "meaning", entered)["kind"])

    def test_explicit_numeric_synonym_can_supply_an_alternate_representation(self):
        self.assertEqual("correct", grade(item("1,000 units"), "meaning", "1000 units", {"meaning_synonyms": ["1000 units"]})["kind"])

    def test_whitelisted_numeric_variant_does_not_weaken_other_numbers(self):
        subject = item("1.5 meters")
        subject["data"]["auxiliary_meanings"] = [{"meaning": "150 centimeters", "type": "whitelist"}]
        self.assertTrue(grade(subject, "meaning", "150 centimeters")["correct"])
        self.assertFalse(grade(subject, "meaning", "15 centimeters")["correct"])

    def test_negation_changes_cannot_hide_inside_typo_tolerance(self):
        fixtures = [
            ("to unfasten", "to fasten"),
            ("unimportant", "important"),
            ("important", "unimportant"),
            ("non functional", "functional"),
            ("unconditional", "nonconditional"),
            ("nonconditional", "unconditional"),
            ("never late", "ever late"),
            ("not so heavy", "now so heavy"),
            ("no exception", "an exception"),
        ]
        for expected, entered in fixtures:
            with self.subTest(expected=expected, entered=entered):
                self.assertEqual("incorrect", grade(item(expected), "meaning", entered)["kind"])

    def test_long_phrase_does_not_grant_multiple_edits_to_a_short_word(self):
        for expected, entered in (("a quiet cat", "a quiet car"), ("to take part", "to take pair")):
            with self.subTest(expected=expected, entered=entered):
                self.assertEqual("incorrect", grade(item(expected), "meaning", entered)["kind"])
        self.assertEqual("imprecise", grade(item("to enter"), "meaning", "to entr")["kind"])
        self.assertEqual("imprecise", grade(item("to enter room"), "meaning", "to entter room")["kind"])

    def test_article_changes_require_an_explicit_accepted_variant(self):
        self.assertEqual("incorrect", grade(item("a book"), "meaning", "book")["kind"])
        self.assertEqual("correct", grade(item("a book"), "meaning", "book", {"meaning_synonyms": ["book"]})["kind"])

    def test_word_punctuation_normalization_does_not_change_numeric_policy(self):
        self.assertEqual("correct", grade(item("sun-dried"), "meaning", "sun dried")["kind"])
        self.assertEqual("correct", grade(item("traveler's bag"), "meaning", "traveler’s bag.")["kind"])
        self.assertEqual("retry", grade(item(), "meaning", "...")["kind"])

    def test_nonaccepted_meaning_cannot_return_through_fuzzy_matching(self):
        subject = item("stone")
        subject["data"]["meanings"].append({"meaning": "stove", "accepted_answer": False})
        self.assertEqual("incorrect", grade(subject, "meaning", "stove")["kind"])
        self.assertEqual("correct", grade(subject, "meaning", "stove", {"meaning_synonyms": ["stove"]})["kind"])
        subject["data"]["auxiliary_meanings"] = [{"meaning": "stove", "type": "blacklist"}]
        self.assertEqual("incorrect", grade(subject, "meaning", "stove", {"meaning_synonyms": ["stove"]})["kind"])

    def test_only_exact_small_combination_size_mistakes_receive_retry(self):
        for expected, entered in (("しゅう", "しゆう"), ("にゃく", "にやく"), ("きょか", "きよか"), ("しゆう", "しゅう")):
            with self.subTest(expected=expected, entered=entered):
                result = grade(item(reading=expected), "reading", entered)
                self.assertEqual("retry", result["kind"])
                self.assertFalse(result["correct"])
                self.assertEqual([], result["accepted"])
        for expected, entered in (("しゅう", "しゆお"), ("かって", "かつて"), ("が", "か")):
            with self.subTest(expected=expected, entered=entered):
                self.assertEqual("incorrect", grade(item(reading=expected), "reading", entered)["kind"])

    def test_missing_internal_n_retry_is_limited_to_the_ime_vowel_pattern(self):
        for expected, entered in (("かんい", "かに"), ("しんおう", "しのう"), ("かんえん", "かねん")):
            with self.subTest(expected=expected, entered=entered):
                result = grade(item(reading=expected), "reading", entered)
                self.assertEqual("retry", result["kind"])
                self.assertFalse(result["correct"])
                self.assertEqual([], result["accepted"])
        for expected, entered in (("かんたん", "かたん"), ("かんい", "かい"), ("かんい", "かの"), ("かん", "か")):
            with self.subTest(expected=expected, entered=entered):
                self.assertEqual("incorrect", grade(item(reading=expected), "reading", entered)["kind"])

    def test_exact_direct_kana_is_preserved_without_long_vowel_expansion(self):
        for expected, entered in (("が", "か\u3099"), ("はいる", "ﾊｲﾙ"), ("こーと", "コート"), ("ゔぁ", "ヴァ")):
            with self.subTest(expected=expected, entered=entered):
                self.assertEqual("correct", grade(item(reading=expected), "reading", entered)["kind"])
        self.assertEqual("incorrect", grade(item(reading="こーと"), "reading", "こおと")["kind"])
        self.assertEqual("retry", grade(item(reading="こーと"), "reading", "こーと、こと")["kind"])

    def test_accepted_flags_and_alternate_kanji_readings_stay_distinct(self):
        subject = item(reading="せい", kind="kanji")
        subject["data"]["readings"].append({"reading": "いき", "accepted_answer": False})
        self.assertEqual("retry", grade(subject, "reading", "イキ")["kind"])
        subject["object"] = "vocabulary"
        self.assertEqual("incorrect", grade(subject, "reading", "いき")["kind"])

    def test_unknown_parts_and_nontext_answers_do_not_grade(self):
        for part in (None, "", "meaning_typo", "reading ", 1):
            with self.subTest(part=part), self.assertRaises(UserError) as failure:
                grade(item(), part, "to enter")
            self.assertEqual("invalid_request", failure.exception.code)
        with self.assertRaises(UserError):
            grade(item("123"), "meaning", 123)

    def test_malformed_acceptance_flags_fail_closed(self):
        for field, key in (("meanings", "meaning"), ("readings", "reading")):
            for flag in ("false", "true", 0, 1, None, [], {}):
                with self.subTest(field=field, flag=flag), self.assertRaises(UserError) as failure:
                    subject = item()
                    subject["data"][field] = [{key: "bad" if field == "meanings" else "ばど", "accepted_answer": flag}]
                    grade(subject, "meaning", "bad")
                self.assertEqual("content_unavailable", failure.exception.code)

    def test_malformed_resources_and_synonyms_have_explicit_errors(self):
        for field in ("meanings", "readings", "auxiliary_meanings"):
            for invalid in (None, "fabricated", {}, [None], ["fabricated"]):
                with self.subTest(field=field, invalid=invalid), self.assertRaises(UserError) as failure:
                    subject = item()
                    subject["data"][field] = invalid
                    validate_subject_answers(subject)
                self.assertEqual("content_unavailable", failure.exception.code)
        for invalid in ("ridge", [None], [""], [123], None):
            with self.subTest(synonyms=invalid), self.assertRaises(UserError) as failure:
                grade(item(), "meaning", "r", {"meaning_synonyms": invalid})
            self.assertEqual("content_unavailable", failure.exception.code)

    def test_empty_or_non_kana_accepted_readings_are_unavailable(self):
        for readings in ([], [{"reading": "shuu", "accepted_answer": True}], [{"reading": "", "accepted_answer": True}], [{"reading": "しゅう", "accepted_answer": False}]):
            with self.subTest(readings=readings), self.assertRaises(UserError):
                subject = item()
                subject["data"]["readings"] = readings
                validate_subject_answers(subject)

    def test_radicals_and_kana_vocabulary_do_not_require_unused_readings(self):
        for kind in ("radical", "kana_vocabulary"):
            subject = item("greeting", kind=kind)
            subject["data"]["readings"] = "unused malformed field"
            self.assertEqual("correct", grade(subject, "meaning", "greeting")["kind"])
            with self.assertRaises(UserError) as failure:
                grade(subject, "reading", "しゅう")
            self.assertEqual("invalid_request", failure.exception.code)

    def test_validation_never_modifies_subject_or_personal_synonyms(self):
        subject = item()
        material = {"meaning_synonyms": ["arrive"]}
        before = copy.deepcopy((subject, material))
        prepared = validate_subject_answers(subject, material)
        prepared["meanings"].append("not part of the resource")
        self.assertEqual(before, (subject, material))


class StrictMeaningTests(unittest.TestCase):
    def test_strict_mode_only_disables_fuzzy_meaning_acceptance(self):
        subject = item("to enter")
        self.assertEqual("imprecise", grade(subject, "meaning", "to entr")["kind"])
        self.assertEqual("incorrect", grade(subject, "meaning", "to entr", strict_meanings=True)["kind"])
        self.assertEqual("correct", grade(subject, "meaning", " TO ENTER. ", strict_meanings=True)["kind"])

    def test_exact_synonyms_whitelists_and_blacklists_keep_their_precedence(self):
        subject = item("to enter")
        subject["data"]["auxiliary_meanings"] = [{"meaning": "go inside", "type": "whitelist"}, {"meaning": "exit", "type": "blacklist"}]
        material = {"meaning_synonyms": ["arrive", "exit"]}
        for answer in ("arrive", "GO INSIDE."):
            self.assertEqual("correct", grade(subject, "meaning", answer, material, strict_meanings=True)["kind"])
        for answer in ("arriv", "go insid", "exit"):
            self.assertEqual("incorrect", grade(subject, "meaning", answer, material, strict_meanings=True)["kind"])

    def test_retry_mistakes_and_reading_grading_are_identical_in_both_modes(self):
        subject = item("to enter", "しゅう", "kanji")
        subject["data"]["readings"].append({"reading": "あつ", "accepted_answer": False})
        for part, answer in (("meaning", "enter"), ("meaning", "しゅう"), ("meaning", ""),
                ("reading", "しゆう"), ("reading", "あつ"), ("reading", "シュウ"), ("reading", "しゅお")):
            with self.subTest(part=part, answer=answer):
                self.assertEqual(grade(subject, part, answer), grade(subject, part, answer, strict_meanings=True))

    def test_strict_means_normalized_exact_for_all_subject_types(self):
        for kind in ("radical", "kanji", "vocabulary", "kana_vocabulary"):
            with self.subTest(kind=kind):
                subject = item("sun-dried", kind=kind)
                self.assertEqual("correct", grade(subject, "meaning", "Sun Dried.", strict_meanings=True)["kind"])
                self.assertEqual("incorrect", grade(subject, "meaning", "sun drid", strict_meanings=True)["kind"])

    def test_non_boolean_grading_mode_is_not_silently_interpreted(self):
        for invalid in ("false", "true", 0, 1, None):
            with self.subTest(invalid=invalid), self.assertRaises(UserError):
                grade(item(), "meaning", "to enter", strict_meanings=invalid)


class StrictMeaningPreferenceTests(EngineFixture, unittest.TestCase):
    def test_setting_defaults_locally_and_persists_through_the_command_dispatcher(self):
        self.assertIs(False, self.engine.snapshot()["settings"]["strict_meanings"])
        account = self.store.get("user")
        settings = self.engine.command("set-strict", "settings", {"strict_meanings": True})
        self.assertIs(True, settings["strict_meanings"])
        self.store.close()
        self.store = Store(self.path)
        self.engine = Engine(self.store, clock=lambda: NOW)
        self.assertIs(True, self.engine.snapshot()["settings"]["strict_meanings"])
        self.assertEqual(account, self.store.get("user"))
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))
        self.engine.command("set-tolerant", "settings", {"strict_meanings": False})
        self.assertIs(False, self.engine.settings()["strict_meanings"])

    def test_setting_validation_rejects_non_booleans_without_partial_changes(self):
        before = self.engine.settings()
        for index, invalid in enumerate(("false", "true", 0, 1, None, [], {})):
            with self.subTest(invalid=invalid), self.assertRaises(UserError):
                self.engine.command(f"invalid-strict-{index}", "settings", {"batch_size": 7, "strict_meanings": invalid})
            self.assertEqual(before, self.engine.settings())

    def test_setting_applies_to_the_next_answer_without_regrading_saved_feedback(self):
        self.engine.start("practice", 1, [2])
        tolerant = self.engine.command("tolerant-answer", "answer", {"text": "montain"})
        self.assertEqual("imprecise", tolerant["feedback"]["kind"])
        self.engine.set_settings({"strict_meanings": True})
        self.assertEqual(tolerant["feedback"], self.engine.session_view()["feedback"])
        self.assertEqual(tolerant, self.engine.command("tolerant-answer", "answer", {"text": "montain"}))
        self.engine.start("practice", 1, [2], replace_practice=True)
        strict = self.engine.answer("montain")
        self.assertEqual("incorrect", strict["feedback"]["kind"])
        self.assertEqual(1, strict["errors"])
        corrected = self.engine.correct()
        self.assertTrue(corrected["feedback"]["corrected"])
        self.assertEqual(0, corrected["errors"])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))


class GradingPersistenceTests(EngineFixture, unittest.TestCase):
    def test_retry_hint_does_not_record_an_error_or_advance_the_subject(self):
        subject = self.store.subject(2)
        subject["data"]["readings"] = [{"reading": "しゅう", "accepted_answer": True}]
        self.store.put(subject)
        self.engine.start("practice", 1, [2])
        self.engine.answer("mountain")
        self.engine.advance()
        result = self.engine.answer("しゆう")
        self.assertEqual("question", result["phase"])
        self.assertEqual(0, result["errors"])
        self.assertEqual(0, result["completed"])
        self.assertEqual("しゆう", result["draft"])
        self.assertEqual([], self.store.rows("SELECT * FROM outbox"))

    def test_malformed_synonyms_leave_the_current_answer_transaction_untouched(self):
        self.engine.start("practice", 1, [2])
        self.engine.draft("saved partial answer")
        self.store.set("material_draft_2", {"meaning_synonyms": "ridge"})
        before = list(self.store.db.iterdump())
        with self.assertRaises(UserError):
            self.engine.answer("r")
        self.assertEqual(before, list(self.store.db.iterdump()))
