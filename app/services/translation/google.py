"""Google Translate provider. Needs no API key.

It uses the free endpoint behind translate.google.com. That endpoint is not an
official, documented API: it can change or rate-limit without notice, and its
reply is positional arrays rather than named fields (indexes noted below).
Example sentences come from Google's dictionary data, so many words and nearly
all phrases have none.
"""
import html
import re
from typing import Optional

from app.core.http import HttpError, request_json

from .base import Entry, Provider, TranslationError

URL = "https://translate.googleapis.com/translate_a/single"
CJK = re.compile(r"[一-鿿]")
TAG = re.compile(r"<[^>]+>")
POS = {
    "noun": "n.", "verb": "v.", "adjective": "adj.", "adverb": "adv.", "preposition": "prep.",
    "conjunction": "conj.", "pronoun": "pron.", "interjection": "int.", "abbreviation": "abbr.",
    "article": "art.", "auxiliary verb": "aux.", "phrase": "phr.", "prefix": "pref.", "suffix": "suff.",
}


def at(data, *path):
    """data[path[0]][path[1]]... or None when any step is missing."""
    for index in path:
        if not isinstance(data, list) or not -len(data) <= index < len(data):
            return None
        data = data[index]
    return data


class GoogleTranslate(Provider):
    name = "google"
    label = "Google 翻译"

    def _call(self, text: str, target: str, parts: list[str]):
        params = [("client", "gtx"), ("sl", "auto"), ("tl", target), ("q", text)] + [("dt", p) for p in parts]
        try:
            return request_json(URL, params=params, timeout=15)
        except HttpError as e:
            if e.status == 429:
                raise TranslationError("Google 翻译请求太频繁，过一会儿再试。") from e
            raise TranslationError("连不上 Google 翻译。") from e

    def _plain(self, text: str, target: str) -> str:
        data = self._call(text, target, ["t"])
        return "".join(seg[0] for seg in (at(data, 0) or []) if isinstance(seg, list) and seg and isinstance(seg[0], str))

    def lookup(self, words: list[str]) -> list[Optional[Entry]]:
        return [self._one(word) for word in words]

    def _one(self, word: str) -> Optional[Entry]:
        to_english = bool(CJK.search(word))
        data = self._call(word, "en" if to_english else "zh-CN", ["t", "bd", "rm", "ex", "md", "qc"])

        # Check for query correction (Google suggests a spelling fix)
        corrected = at(data, 7, 1) or at(data, 7, 0)
        corrected_word = word
        if isinstance(corrected, str):
            clean = TAG.sub("", corrected).strip()
            if clean and clean.lower() != word.lower():
                corrected_word = clean

        # [0]: translated segments; the last one carries the source romanization at [3].
        segments = [seg for seg in (at(data, 0) or []) if isinstance(seg, list)]
        plain = "".join(seg[0] for seg in segments if seg and isinstance(seg[0], str)).strip()
        phonetic = next((seg[3] for seg in reversed(segments) if len(seg) > 3 and isinstance(seg[3], str) and seg[3]), "")

        # [1]: dictionary senses grouped by part of speech: [pos, [term, ...], ...].
        groups = [g for g in (at(data, 1) or []) if isinstance(g, list) and len(g) > 1 and isinstance(g[1], list)]
        senses: list[str] = []
        for i, group in enumerate(groups[:2]):
            for term in group[1][: 2 if i == 0 else 1]:
                if isinstance(term, str) and term not in senses:
                    senses.append(term)
        if plain and plain not in senses:
            senses.insert(0, plain)
        meaning = "；".join(senses[:3])
        if not meaning or meaning.lower() == word.lower() or (not to_english and not CJK.search(meaning)):
            return None   # Google echoed (or merely respelled) the input: it does not know the word.

        pos_name = at(groups, 0, 0) or at(data, 12, 0, 0) or ""
        pos = POS.get(pos_name, "") if isinstance(pos_name, str) else ""
        if not pos and " " in word.strip():
            pos = "phr."

        # [12]: definitions [pos, [[definition, id, example], ...]]; [13]: example sentences with <b> marks.
        example = at(data, 12, 0, 1, 0, 2) or at(data, 13, 0, 0, 0) or ""
        example = html.unescape(TAG.sub("", example)).strip() if isinstance(example, str) else ""
        example_zh = ""
        if example:
            example = example[0].upper() + example[1:]
            if not to_english:
                try:
                    example_zh = self._plain(example, "zh-CN")
                except TranslationError:
                    example_zh = ""

        lang = at(data, 2)
        return Entry(
            word=corrected_word,
            meaning=meaning[:400],
            lang=lang if isinstance(lang, str) else "",
            phonetic=f"/{phonetic}/" if phonetic and not to_english else "",
            pos=pos,
            example=example[:400],
            example_zh=example_zh[:400],
            source=self.name,
        )
