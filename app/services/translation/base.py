"""Shared types for dictionary providers."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Entry:
    """One looked-up word, ready to store."""
    word: str
    meaning: str
    lang: str = ""         # BCP 47 code of the word's language, e.g. "en"
    phonetic: str = ""
    pos: str = ""          # "n.", "v.", "phr." ...
    example: str = ""
    example_zh: str = ""
    source: str = ""       # provider name that produced it


class TranslationError(Exception):
    """Lookup failed. The message is shown to the user, so it is written for them."""


class Provider:
    name = ""
    label = ""

    def lookup(self, words: list[str]) -> list[Optional[Entry]]:
        """Return one Entry (or None when a word could not be looked up) per input word, in order."""
        raise NotImplementedError
