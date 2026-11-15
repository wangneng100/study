"""Quiz questions for a study session, built from the notebook itself (no outside service).

Each word gets several question variants; the page asks one, and uses another
when the word comes back after a wrong answer.

Question types
  choose_meaning  see the word, pick its meaning
  choose_word     see the meaning, pick the word
  spell           see the meaning, type the word
  cloze           example sentence with the word blanked out, type it
  listen          hear the word, type it (the page skips it when the browser cannot speak)
"""
import random
import re

BLANK = "_____"


def _distractors(word: dict, pool: list[dict], field: str, rng: random.Random, count: int = 3) -> list[str]:
    """Up to `count` distinct values of `field` from other words."""
    own = word[field].strip().lower()
    seen, values = {own}, []
    for other in rng.sample(pool, len(pool)):
        value = other[field].strip()
        if other["id"] != word["id"] and value and value.lower() not in seen:
            seen.add(value.lower())
            values.append(value)
        if len(values) == count:
            break
    return values


def _choice(kind: str, right: str, wrong: list[str], rng: random.Random) -> dict:
    options = wrong + [right]
    rng.shuffle(options)
    return {"type": kind, "options": options, "answer": options.index(right)}


def _cloze(word: dict):
    """Blank the word (with any ending, e.g. 'runs') out of its example sentence."""
    example = word.get("example") or ""
    match = re.search(r"(?<!\w)" + re.escape(word["word"]) + r"\w*", example, re.IGNORECASE)
    if not match:
        return None
    accept = sorted({word["word"], match.group(0)}, key=len)
    return {
        "type": "cloze",
        "sentence": example[:match.start()] + BLANK + example[match.end():],
        "accept": accept,
    }


def build(word: dict, pool: list[dict], rng: random.Random) -> list[dict]:
    """All question variants for one word, in the order the page should use them."""
    questions = []
    meanings = _distractors(word, pool, "meaning", rng)
    if meanings:
        questions.append(_choice("choose_meaning", word["meaning"], meanings, rng))
    words = _distractors(word, pool, "word", rng)
    if words:
        questions.append(_choice("choose_word", word["word"], words, rng))
    cloze = _cloze(word)
    if cloze:
        questions.append(cloze)
    questions.append({"type": "spell", "accept": [word["word"]]})
    questions.append({"type": "listen", "accept": [word["word"]]})
    rng.shuffle(questions)
    return questions


def session(batch: list[dict], pool: list[dict], rng: random.Random = None) -> list[dict]:
    rng = rng or random.Random()
    return [{"word": word, "questions": build(word, pool, rng)} for word in batch]
