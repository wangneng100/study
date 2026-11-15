"""One SQLite file shared by every tool. Each tool owns its own tables."""
import os
import sqlite3

from flask import current_app, g


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db() -> sqlite3.Connection:
    """The connection for the current request."""
    if "db" not in g:
        g.db = connect(current_app.config["DB_PATH"])
    return g.db


def close_db(_exc=None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db(path: str, schemas: list[str]) -> None:
    """Create the database file and run every tool's CREATE TABLE IF NOT EXISTS script."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = connect(path)
    try:
        for schema in schemas:
            if schema:
                conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()
