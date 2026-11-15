"""SQLite storage for the vocabulary notebook."""
import re
import sqlite3
import unicodedata
from typing import Optional

from app.core import srs
from app.services.translation import Entry

SCHEMA = """
CREATE TABLE IF NOT EXISTS vocab_words (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    key              TEXT NOT NULL UNIQUE,      -- normalized word, so each word is stored once
    word             TEXT NOT NULL,
    lang             TEXT NOT NULL DEFAULT '',
    phonetic         TEXT NOT NULL DEFAULT '',
    pos              TEXT NOT NULL DEFAULT '',
    meaning          TEXT NOT NULL,
    example          TEXT NOT NULL DEFAULT '',
    example_zh       TEXT NOT NULL DEFAULT '',
    source           TEXT NOT NULL DEFAULT '',  -- provider that translated it, or 'manual'
    stage            INTEGER NOT NULL DEFAULT 0,
    due_at           INTEGER,                   -- ms since epoch; NULL once mastered
    added_at         INTEGER NOT NULL,
    last_reviewed_at INTEGER,
    reviews          INTEGER NOT NULL DEFAULT 0,
    lapses           INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS vocab_reviews (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id      INTEGER NOT NULL REFERENCES vocab_words(id) ON DELETE CASCADE,
    reviewed_at  INTEGER NOT NULL,
    grade        TEXT NOT NULL,
    stage_before INTEGER NOT NULL,
    stage_after  INTEGER NOT NULL
);
"""


def word_key(word: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", word)).strip().lower()


def to_json(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "word": row["word"], "lang": row["lang"], "phonetic": row["phonetic"],
        "pos": row["pos"], "meaning": row["meaning"], "example": row["example"],
        "exampleZh": row["example_zh"], "source": row["source"], "stage": row["stage"],
        "dueAt": row["due_at"], "addedAt": row["added_at"], "lastReviewedAt": row["last_reviewed_at"],
        "reviews": row["reviews"], "lapses": row["lapses"],
    }


def all_words(db: sqlite3.Connection) -> list[dict]:
    return [to_json(r) for r in db.execute("SELECT * FROM vocab_words ORDER BY added_at DESC, id DESC")]


def get(db: sqlite3.Connection, word_id: int) -> Optional[sqlite3.Row]:
    return db.execute("SELECT * FROM vocab_words WHERE id = ?", (word_id,)).fetchone()


def find(db: sqlite3.Connection, word: str) -> Optional[sqlite3.Row]:
    return db.execute("SELECT * FROM vocab_words WHERE key = ?", (word_key(word),)).fetchone()


def add(db: sqlite3.Connection, entry: Entry, now: int) -> sqlite3.Row:
    cur = db.execute(
        "INSERT INTO vocab_words (key, word, lang, phonetic, pos, meaning, example, example_zh, source,"
        " stage, due_at, added_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
        (word_key(entry.word), entry.word, entry.lang, entry.phonetic, entry.pos, entry.meaning,
         entry.example, entry.example_zh, entry.source, srs.first_due(now), now),
    )
    db.commit()
    return get(db, cur.lastrowid)


def update_entry(db: sqlite3.Connection, word_id: int, entry: Entry) -> sqlite3.Row:
    """Replace the dictionary content of a word, keeping its review progress."""
    db.execute(
        "UPDATE vocab_words SET lang = ?, phonetic = ?, pos = ?, meaning = ?, example = ?, example_zh = ?,"
        " source = ? WHERE id = ?",
        (entry.lang, entry.phonetic, entry.pos, entry.meaning, entry.example, entry.example_zh, entry.source, word_id),
    )
    db.commit()
    return get(db, word_id)


def review(db: sqlite3.Connection, row: sqlite3.Row, result: str, now: int) -> sqlite3.Row:
    outcome = srs.grade(row["stage"], result, now)
    db.execute(
        "UPDATE vocab_words SET stage = ?, due_at = ?, last_reviewed_at = ?, reviews = reviews + 1,"
        " lapses = lapses + ? WHERE id = ?",
        (outcome.stage, outcome.due_at, now, int(outcome.lapsed), row["id"]),
    )
    db.execute(
        "INSERT INTO vocab_reviews (word_id, reviewed_at, grade, stage_before, stage_after) VALUES (?, ?, ?, ?, ?)",
        (row["id"], now, result, row["stage"], outcome.stage),
    )
    db.commit()
    return get(db, row["id"])


def study_batch(db: sqlite3.Connection, count: int) -> list[dict]:
    """Words for an on-demand study session: due ones first, then the soonest due, mastered last."""
    rows = db.execute("SELECT * FROM vocab_words ORDER BY due_at IS NULL, due_at ASC, id ASC LIMIT ?", (count,))
    return [to_json(r) for r in rows]


def study_review(db: sqlite3.Connection, row: sqlite3.Row, result: str, now: int) -> tuple[sqlite3.Row, bool]:
    """Record an answer given in an on-demand session. Returns (word, schedule_changed).

    A word that is due is graded as a normal review. A word studied ahead of time
    keeps its schedule, unless it was forgotten: then it starts over.
    """
    if result not in srs.GRADES:
        raise ValueError(f"unknown grade: {result}")
    mastered = row["stage"] >= srs.MASTERED
    if not mastered and row["due_at"] <= now:
        return review(db, row, result, now), True
    changed = result == "forgot"
    if changed:
        db.execute(
            "UPDATE vocab_words SET stage = 0, due_at = ?, last_reviewed_at = ?, lapses = lapses + 1 WHERE id = ?",
            (srs.first_due(now), now, row["id"]),
        )
    db.execute(
        "INSERT INTO vocab_reviews (word_id, reviewed_at, grade, stage_before, stage_after) VALUES (?, ?, ?, ?, ?)",
        (row["id"], now, "study:" + result, row["stage"], 0 if changed else row["stage"]),
    )
    db.commit()
    return get(db, row["id"]), changed


def reset(db: sqlite3.Connection, word_id: int, now: int) -> sqlite3.Row:
    db.execute("UPDATE vocab_words SET stage = 0, due_at = ? WHERE id = ?", (srs.first_due(now), word_id))
    db.commit()
    return get(db, word_id)


def delete(db: sqlite3.Connection, word_id: int) -> None:
    db.execute("DELETE FROM vocab_words WHERE id = ?", (word_id,))
    db.commit()


def status(db: sqlite3.Connection) -> str:
    """One line for the home page."""
    total = db.execute("SELECT COUNT(*) FROM vocab_words").fetchone()[0]
    due = db.execute(
        "SELECT COUNT(*) FROM vocab_words WHERE due_at IS NOT NULL AND due_at <= ?", (srs.now_ms(),)
    ).fetchone()[0]
    if due:
        return f"{due} 个词该复习了 · 共 {total} 词"
    return f"共 {total} 词" if total else "还没有单词"
