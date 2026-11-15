"""Ebbinghaus spaced-repetition schedule, shared by any tool that reviews items.

An item has a `stage`: the number of reviews it has passed. The item is due
INTERVALS_MS[stage] after it was added or last reviewed. After the last review
it is mastered and has no due time. All times are milliseconds since the epoch.
"""
import time
from dataclasses import dataclass
from typing import Optional

MIN = 60_000
HOUR = 60 * MIN
DAY = 24 * HOUR

# (wait before the review, full label, short label)
STEPS = [
    (5 * MIN, "5 分钟", "5分"),
    (30 * MIN, "30 分钟", "30分"),
    (12 * HOUR, "12 小时", "12时"),
    (1 * DAY, "1 天", "1天"),
    (2 * DAY, "2 天", "2天"),
    (4 * DAY, "4 天", "4天"),
    (7 * DAY, "7 天", "7天"),
    (15 * DAY, "15 天", "15天"),
]
INTERVALS_MS = [step[0] for step in STEPS]
MASTERED = len(STEPS)
GRADES = ("forgot", "fuzzy", "got")


def now_ms() -> int:
    return int(time.time() * 1000)


def first_due(now: int) -> int:
    return now + INTERVALS_MS[0]


@dataclass(frozen=True)
class Outcome:
    stage: int
    due_at: Optional[int]   # None once mastered
    lapsed: bool


def grade(stage: int, result: str, now: int) -> Outcome:
    """Apply one review.

    got    -> next stage (mastered after the last one)
    fuzzy  -> same stage, wait the same interval again
    forgot -> back to the start
    """
    if result not in GRADES:
        raise ValueError(f"unknown grade: {result}")
    if not 0 <= stage < MASTERED:
        raise ValueError("item is not in review")
    if result == "got":
        nxt = stage + 1
        return Outcome(nxt, None if nxt >= MASTERED else now + INTERVALS_MS[nxt], False)
    if result == "fuzzy":
        return Outcome(stage, now + INTERVALS_MS[stage], False)
    return Outcome(0, now + INTERVALS_MS[0], True)


def steps_json() -> list[dict]:
    return [{"ms": ms, "label": label, "short": short} for ms, label, short in STEPS]
