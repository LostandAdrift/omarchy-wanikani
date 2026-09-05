"""Deterministic grading. API acceptance flags take precedence over heuristics.

Behavior references: WaniKani Knowledge and Tsurukame AnswerChecker (Apache-2.0).
This module is an original implementation; no remote code or AI grades answers.
"""
import re
import unicodedata


def meaning(value):
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    value = re.sub(r"[’'.]", "", value)
    return re.sub(r"\s+", " ", value.replace("-", " "))


def reading(value):
    value = unicodedata.normalize("NFKC", value).strip()
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in value)


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


def grade(subject, part, answer, material=None):
    data = subject["data"]
    raw = str(answer).strip()
    if not raw:
        return result("retry", "Type an answer first.")
    if len(raw) > 300:
        return result("retry", "Please give one short answer.")
    if part == "reading":
        answer = reading(raw)
        accepted = [reading(r["reading"]) for r in data.get("readings", []) if r.get("accepted_answer", False)]
        if not re.fullmatch(r"[ぁ-ゖゝゞー]+", answer):
            return result("retry", "Use kana for the reading.")
        if answer in accepted:
            return result("correct", "Correct", accepted)
        if subject["object"] == "kanji" and answer in [reading(r["reading"]) for r in data.get("readings", [])]:
            return result("retry", "That is another reading. Try the reading taught with this kanji.")
        return result("incorrect", "Not quite. Review the reading, then try again.", accepted)

    answer = meaning(raw)
    accepted = [m["meaning"] for m in data.get("meanings", []) if m.get("accepted_answer", False)]
    accepted += [m["meaning"] for m in data.get("auxiliary_meanings", []) if m.get("type") == "whitelist"]
    excluded = [meaning(m["meaning"]) for m in data.get("auxiliary_meanings", []) if m.get("type") == "blacklist"]
    accepted += (material or {}).get("meaning_synonyms", [])
    normalized = [meaning(m) for m in accepted]
    # Explicit exclusions win over local synonyms and spelling tolerance.
    if answer in excluded:
        return result("incorrect", "This meaning is specifically excluded.", accepted)
    if answer in normalized:
        return result("correct", "Correct", accepted)
    if re.search(r"[ぁ-ヿ一-鿿]", answer):
        return result("retry", "This question asks for the English meaning.")
    if any(m.startswith("to ") and m[3:] == answer for m in normalized):
        return result("retry", "Include ‘to’ for a verb.")
    # Deliberately conservative: one edit on words >=4, two only on long phrases.
    # Never forgive a short answer, an excluded near-match, or a changed number.
    if len(answer) >= 4 and not any(distance(answer, x) <= 1 for x in excluded):
        for target in normalized:
            limit = 0 if len(target) < 4 else 1 if len(target) < 10 else 2
            if re.findall(r"\d+", answer) != re.findall(r"\d+", target):
                continue
            if target.startswith("to ") and not answer.startswith("to "):
                continue
            if distance(answer, target) <= limit:
                return result("imprecise", "Accepted with a spelling difference.", accepted)
    return result("incorrect", "Not quite. Review the meaning, then try again.", accepted)
