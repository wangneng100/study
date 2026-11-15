"""Vocabulary notebook: the page and its JSON API (mounted at /vocab/)."""
import re

from flask import Blueprint, current_app, jsonify, render_template, request

from app.core import srs
from app.core.db import get_db
from app.services import translation
from app.services.translation import Entry, TranslationError

from . import store

bp = Blueprint("vocab", __name__, template_folder="templates", static_folder="static")

MAX_BATCH = 20
SPLIT = re.compile(r"[\n,，、;；]+")


def parse_entries(text: str) -> list[str]:
    """Split pasted input into distinct words or phrases."""
    seen, out = set(), []
    for part in SPLIT.split(text):
        word = re.sub(r"\s+", " ", part).strip()[:80]
        key = store.word_key(word)
        if word and key not in seen:
            seen.add(key)
            out.append(word)
    return out[:MAX_BATCH]


def do_lookup(words: list[str]):
    """Tests replace the real providers through app.config['LOOKUP']."""
    fn = current_app.config.get("LOOKUP") or translation.lookup
    return fn(words, current_app.config)


def error(message: str, status: int, **extra):
    return jsonify({"error": message, **extra}), status


@bp.get("/")
def index():
    return render_template("vocab/index.html")


@bp.get("/api/words")
def list_words():
    return jsonify({
        "words": store.all_words(get_db()),
        "steps": srs.steps_json(),
        "translator": translation.describe(current_app.config),
    })


@bp.post("/api/words")
def add_words():
    data = request.get_json(silent=True) or {}
    db = get_db()
    now = srs.now_ms()

    # The user typed the meaning themselves: store one word without a lookup.
    if isinstance(data.get("meaning"), str) and data["meaning"].strip():
        word = re.sub(r"\s+", " ", str(data.get("word", ""))).strip()[:80]
        if not word:
            return error("先输入一个单词。", 400)
        row = store.find(db, word)
        if row:
            return jsonify({"added": [], "existing": [store.to_json(row)], "failed": [], "notice": ""})
        row = store.add(db, Entry(word=word, meaning=data["meaning"].strip()[:400], source="manual"), now)
        return jsonify({"added": [store.to_json(row)], "existing": [], "failed": [], "notice": ""})

    words = parse_entries(str(data.get("text", "")))
    if not words:
        return error("先输入一个单词。", 400)
    existing = [row for row in (store.find(db, w) for w in words) if row]
    known = {row["key"] for row in existing}
    fresh = [w for w in words if store.word_key(w) not in known]

    added, failed, notice = [], [], ""
    if fresh:
        try:
            result = do_lookup(fresh)
        except TranslationError as e:
            # `manual` tells the page to offer typing the meaning by hand.
            return error(str(e), 502, manual=True)
        notice = result.notice
        for word, entry in zip(fresh, result.entries):
            if entry is None:
                failed.append(word)
                continue
            row = store.find(db, entry.word)   # the provider may have corrected the spelling
            if row:
                if row["key"] not in known:
                    known.add(row["key"])
                    existing.append(row)
                continue
            added.append(store.add(db, entry, now))
    return jsonify({
        "added": [store.to_json(r) for r in added],
        "existing": [store.to_json(r) for r in existing],
        "failed": failed,
        "notice": notice,
    })


@bp.post("/api/words/<int:word_id>/review")
def review_word(word_id: int):
    db = get_db()
    row = store.get(db, word_id)
    if row is None:
        return error("这个词已经不在单词本里了。", 404)
    result = (request.get_json(silent=True) or {}).get("grade")
    if result not in srs.GRADES or row["stage"] >= srs.MASTERED:
        return error("这次复习没法记录。", 400)
    return jsonify({"word": store.to_json(store.review(db, row, result, srs.now_ms()))})


@bp.post("/api/words/<int:word_id>/reset")
def reset_word(word_id: int):
    db = get_db()
    if store.get(db, word_id) is None:
        return error("这个词已经不在单词本里了。", 404)
    return jsonify({"word": store.to_json(store.reset(db, word_id, srs.now_ms()))})


@bp.post("/api/words/<int:word_id>/refresh")
def refresh_word(word_id: int):
    """Look the word up again, e.g. after switching provider. Review progress is kept."""
    db = get_db()
    row = store.get(db, word_id)
    if row is None:
        return error("这个词已经不在单词本里了。", 404)
    try:
        entry = do_lookup([row["word"]]).entries[0]
    except TranslationError as e:
        return error(str(e), 502)
    if entry is None:
        return error("没查到这个词。", 502)
    return jsonify({"word": store.to_json(store.update_entry(db, word_id, entry))})


@bp.delete("/api/words/<int:word_id>")
def delete_word(word_id: int):
    store.delete(get_db(), word_id)
    return jsonify({"ok": True})
