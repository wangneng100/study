"""Word lookup with interchangeable providers.

Usage:  result = lookup(["serendipity"], app.config)
Add a provider by subclassing Provider and listing it in `providers()`.
"""
from dataclasses import dataclass, field
from typing import Optional

from .base import Entry, Provider, TranslationError
from .google import GoogleTranslate
from .onemin import OneMinAI

__all__ = ["Entry", "Provider", "TranslationError", "LookupResult", "lookup", "providers", "describe"]


@dataclass
class LookupResult:
    entries: list[Optional[Entry]]
    notice: str = ""                       # shown to the user when a fallback was used
    used: list[str] = field(default_factory=list)


def providers(config) -> list[Provider]:
    """The providers to try, in order, for the configured mode."""
    mode = config.get("TRANSLATOR", "auto")
    onemin = OneMinAI(config.get("ONEMIN_API_KEY", ""), config.get("ONEMIN_MODEL", ""))
    if mode == "onemin":
        return [onemin]
    if mode == "google":
        return [GoogleTranslate()]
    return ([onemin] if onemin.api_key else []) + [GoogleTranslate()]


def describe(config) -> dict:
    """What the page tells the user about where translations come from."""
    chain = providers(config)
    return {
        "active": chain[0].name,
        "label": chain[0].label,
        "hasOneMinKey": bool(config.get("ONEMIN_API_KEY")),
        "mode": config.get("TRANSLATOR", "auto"),
    }


def lookup(words: list[str], config) -> LookupResult:
    """Look every word up. Later providers fill in what earlier ones failed on."""
    entries: list[Optional[Entry]] = [None] * len(words)
    problems: list[str] = []
    used: list[str] = []
    chain = providers(config)
    for provider in chain:
        missing = [i for i, entry in enumerate(entries) if entry is None]
        if not missing:
            break
        try:
            found = provider.lookup([words[i] for i in missing])
        except TranslationError as e:
            problems.append(str(e))
            continue
        for i, entry in zip(missing, found):
            entries[i] = entry
        if any(found):
            used.append(provider.label)
    if not any(entries) and problems:
        raise TranslationError(" ".join(problems))
    notice = ""
    if problems and used:
        notice = f"{problems[0]} 这次用了{used[-1]}。"
    return LookupResult(entries, notice, used)
