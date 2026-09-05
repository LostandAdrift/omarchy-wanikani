"""Deterministic grading. API acceptance flags take precedence over heuristics.

Behavior references:
https://knowledge.wanikani.com/wanikani/common-mistakes/
https://knowledge.wanikani.com/japanese/double-n/
https://docs.api.wanikani.com/20170710/#subjects
Tsurukame AnswerChecker, Apache-2.0, reviewed at commit
0d686f43c5189ea488cd744bca2320746fdbc706 (2025-05-19).
This module and its fixtures are independently authored; no reference source
code is bundled or translated. Numeric and typo guards deliberately favor
conservative acceptance rather than mirroring a third-party tolerance curve.
"""
import re
import unicodedata
from .common import UserError


SUBJECT_TYPES = ("radical", "kanji", "vocabulary", "kana_vocabulary")
READING_TYPES = ("kanji", "vocabulary")
KANA = re.compile(r"[ぁ-ゖゝゞー]+")
SMALL_COMBINATIONS = str.maketrans({"ゃ": "や", "ゅ": "ゆ", "ょ": "よ"})
NUMBER = re.compile(r"[$¥€£]?[+\-]?(?:\d+(?:[.,/]\d+)*|\.\d+)%?")


def meaning(value):
    value = unicodedata.normalize("NFKC", value).casefold().strip().replace("−", "-")
    value = re.sub(r"[’']", "", value)
    # Periods before a digit and signs immediately before numbers carry meaning.
    # Removing them would turn 1.5 into 15, or -10 into 10, before exact matching.
    value = re.sub(r"\.(?!\d)", "", value)
    value = re.sub(r"-(?!\d)", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def reading(value):
    value = unicodedata.normalize("NFKC", value).strip()
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in value)


def _bad_content():
    raise UserError("Accepted answers are incomplete or malformed. Refresh the subject before continuing; your saved answers are retained.", "content_unavailable")


def _entries(data, name, value_key, optional=False):
    entries = data.get(name, [] if optional else None)
    if not isinstance(entries, list):
        _bad_content()
    for entry in entries:
        if not isinstance(entry, dict):
            _bad_content()
        value = entry.get(value_key)
        if not isinstance(value, str) or not value.strip() or len(value) > 300:
            _bad_content()
        if name != "auxiliary_meanings" and not isinstance(entry.get("accepted_answer"), bool):
            _bad_content()
    return entries


def validate_subject_answers(subject, material=None):
    """Validate gradeable subject data without I/O or mutation.

    Raise UserError(content_unavailable) for malformed resources. Only kanji
    and vocabulary require reading data. The returned dictionary contains
    raw meaning strings and normalized reading strings; callers which only
    check readiness can ignore it. Access and image availability are separate.
    """
    if not isinstance(subject, dict) or subject.get("object") not in SUBJECT_TYPES or not isinstance(subject.get("data"), dict):
        _bad_content()
    data = subject["data"]
    meanings = _entries(data, "meanings", "meaning")
    auxiliary = _entries(data, "auxiliary_meanings", "meaning", optional=True)
    accepted = [item["meaning"] for item in meanings if item["accepted_answer"] is True]
    unaccepted = [item["meaning"] for item in meanings if item["accepted_answer"] is False]
    excluded = []
    for item in auxiliary:
        if item.get("type") == "whitelist":
            accepted.append(item["meaning"])
        elif item.get("type") == "blacklist":
            excluded.append(item["meaning"])
        else:
            _bad_content()
    if material is not None and not isinstance(material, dict):
        _bad_content()
    synonyms = (material or {}).get("meaning_synonyms", [])
    if not isinstance(synonyms, list) or any(not isinstance(value, str) or not value.strip() or len(value) > 300 for value in synonyms):
        _bad_content()
    accepted += synonyms
    if not accepted or any(not meaning(value) for value in accepted + excluded + unaccepted):
        _bad_content()
    accepted_readings, alternate_readings = [], []
    if subject["object"] in READING_TYPES:
        for item in _entries(data, "readings", "reading"):
            value = reading(item["reading"])
            if not KANA.fullmatch(value):
                _bad_content()
            (accepted_readings if item["accepted_answer"] else alternate_readings).append(value)
        if not accepted_readings:
            _bad_content()
    return {"meanings": accepted, "excluded_meanings": excluded, "unaccepted_meanings": unaccepted,
        "readings": accepted_readings, "alternate_readings": alternate_readings}


def _numbers(value):
    value = unicodedata.normalize("NFKC", value).replace("−", "-")
    return NUMBER.findall(value)


def _typing_hint(answer, accepted):
    # Only a pure や/ゆ/よ size mismatch receives this retry. It never makes an
    # answer correct, and does not forgive other kana substitutions or vowels.
    if any(answer.translate(SMALL_COMBINATIONS) == target.translate(SMALL_COMBINATIONS) for target in accepted):
        return "Check the small ゃ, ゅ, or ょ. Type combinations such as shu or kyu, then try again."
    # A single n before a vowel becomes な/に/ぬ/ね/の in an IME. Recognize only
    # that exact lost-n pattern at an internal position, not arbitrary deletion
    # of ん or a general phonetic near-match. Terminal n is handled by WanaKana.
    contractions = {"あ": "な", "い": "に", "う": "ぬ", "え": "ね", "お": "の"}
    for target in accepted:
        for index in range(1, len(target) - 1):
            if target[index] == "ん" and target[index + 1] in contractions:
                entered = target[:index] + contractions[target[index + 1]] + target[index + 2:]
                if answer == entered:
                    return "Check the internal ん. Type nn or n' before the vowel, then try again."
    return None


def _same_negation(answer_words, target_words):
    negations = {"not", "no", "never"}
    if [(i, word) for i, word in enumerate(answer_words) if word in negations] != [(i, word) for i, word in enumerate(target_words) if word in negations]:
        return False
    for answer, target in zip(answer_words, target_words):
        for prefix in ("un", "non"):
            if answer == prefix + target or target == prefix + answer:
                return False
        # Do not call a different literal negating prefix a spelling mistake.
        # Any genuinely accepted alternative can still be supplied explicitly.
        if ((answer.startswith("un") and target.startswith("non") and answer[2:] == target[3:])
                or (answer.startswith("non") and target.startswith("un") and answer[3:] == target[2:])):
            return False
    return True


def _safe_typo(answer, target):
    answer_words, target_words = answer.split(), target.split()
    if len(answer_words) != len(target_words) or not _same_negation(answer_words, target_words):
        return False
    # A long phrase must not grant extra edits to one short word (cat/car or
    # part/pair). Bound each word as well as the complete answer.
    for actual, expected in zip(answer_words, target_words):
        limit = 0 if len(expected) < 4 else 1 if len(expected) < 10 else 2
        if distance(actual, expected) > limit:
            return False
    limit = 0 if len(target) < 4 else 1 if len(target) < 10 else 2
    return distance(answer, target) <= limit


def distance(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        row = [i]
        for j, y in enumerate(b, 1):
            row.append(min(row[-1] + 1, prev[j] + 1, prev[j - 1] + (x != y)))
        prev = row
    return prev[-1]


def result(kind, message, accepted=None):
    return {"kind": kind, "correct": kind in ("correct", "imprecise"), "retry": kind == "retry", "message": message, "accepted": accepted or []}


def grade(subject, part, answer, material=None, *, strict_meanings=False):
    if not isinstance(strict_meanings, bool):
        raise UserError("Expected an on/off meaning grading preference.", "invalid_request")
    if part not in ("meaning", "reading"):
        raise UserError("Unknown question part. Resume the saved session before answering.", "invalid_request")
    prepared = validate_subject_answers(subject, material)
    if part == "reading" and subject["object"] not in READING_TYPES:
        raise UserError("This subject has no reading question.", "invalid_request")
    if not isinstance(answer, str):
        raise UserError("Type a text answer.", "invalid_request")
    raw = answer.strip()
    if not raw:
        return result("retry", "Type an answer first.")
    if len(raw) > 300:
        return result("retry", "Please give one short answer.")
    if part == "reading":
        answer = reading(raw)
        accepted = prepared["readings"]
        if not KANA.fullmatch(answer):
            return result("retry", "Use kana for the reading.")
        if answer in accepted:
            return result("correct", "Correct", accepted)
        if subject["object"] == "kanji" and answer in prepared["alternate_readings"]:
            return result("retry", "That is another reading. Try the reading taught with this kanji.")
        hint = _typing_hint(answer, accepted)
        if hint:
            return result("retry", hint)
        return result("incorrect", "Not quite. Review the reading, then try again.", accepted)

    answer = meaning(raw)
    if not answer:
        return result("retry", "Type an answer first.")
    accepted = prepared["meanings"]
    excluded = [meaning(value) for value in prepared["excluded_meanings"]]
    normalized = [meaning(m) for m in accepted]
    answer_numbers = _numbers(raw)
    # Explicit exclusions win over local synonyms and spelling tolerance.
    if answer in excluded:
        return result("incorrect", "This meaning is specifically excluded.", accepted)
    if any(answer == target and answer_numbers == _numbers(original) for original, target in zip(accepted, normalized)):
        return result("correct", "Correct", accepted)
    if re.search(r"[ぁ-ヿ一-鿿]", answer):
        return result("retry", "This question asks for the English meaning.")
    if any(m.startswith("to ") and m[3:] == answer for m in normalized):
        return result("retry", "Include ‘to’ for a verb.")
    if answer in [meaning(value) for value in prepared["unaccepted_meanings"]]:
        return result("incorrect", "This meaning is not accepted for this subject.", accepted)
    # Deliberately conservative: one edit on words >=4, two only on long phrases.
    # Never forgive a short answer, an excluded near-match, or a changed number.
    if not strict_meanings and len(answer) >= 4 and not any(distance(answer, x) <= 1 for x in excluded):
        for original, target in zip(accepted, normalized):
            if answer_numbers != _numbers(original):
                continue
            if target.startswith("to ") and not answer.startswith("to "):
                continue
            if _safe_typo(answer, target):
                return result("imprecise", "Accepted with a spelling difference.", accepted)
    return result("incorrect", "Not quite. Review the meaning, then try again.", accepted)
