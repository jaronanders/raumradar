"""
database.py
===========
Sehr einfache lokale SQLite-Datenbank für Notizen & Hausaufgaben.
Kein Server nötig -- die Datei raumradar.db wird automatisch angelegt.
"""

import sqlite3
from pathlib import Path
import shutil

INSTANCE_DIR = Path(__file__).parent / "instance"
DB_PATH = INSTANCE_DIR / "raumradar.db"
LEGACY_DB_PATH = Path(__file__).parent / "raumradar.db"


def prepare_db_path():
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    if LEGACY_DB_PATH.exists() and not DB_PATH.exists():
        shutil.move(str(LEGACY_DB_PATH), str(DB_PATH))


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    prepare_db_path()
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS homework (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            subject TEXT NOT NULL,
            content TEXT NOT NULL,
            due_date TEXT,
            done INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS game_scores (
            username TEXT PRIMARY KEY,
            high_score REAL NOT NULL DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def add_homework(username, subject, content, due_date):
    conn = get_connection()
    conn.execute(
        "INSERT INTO homework (username, subject, content, due_date) VALUES (?, ?, ?, ?)",
        (username, subject, content, due_date),
    )
    conn.commit()
    conn.close()


def get_homework(username):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM homework WHERE username = ? ORDER BY due_date IS NULL, due_date ASC",
        (username,),
    ).fetchall()
    conn.close()
    return rows


def toggle_homework_done(homework_id, username):
    conn = get_connection()
    conn.execute(
        "UPDATE homework SET done = NOT done WHERE id = ? AND username = ?",
        (homework_id, username),
    )
    conn.commit()
    conn.close()


def delete_homework(homework_id, username):
    conn = get_connection()
    conn.execute("DELETE FROM homework WHERE id = ? AND username = ?", (homework_id, username))
    conn.commit()
    conn.close()


def submit_game_score(username, score):
    """Speichert den Score nur, wenn er höher als der bisherige Highscore ist."""
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO game_scores (username, high_score, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(username) DO UPDATE SET
            updated_at = CASE
                WHEN excluded.high_score > game_scores.high_score
                THEN CURRENT_TIMESTAMP
                ELSE game_scores.updated_at
            END,
            high_score = MAX(game_scores.high_score, excluded.high_score)
        """,
        (username, score),
    )
    conn.commit()
    conn.close()


def get_leaderboard(limit=20):
    conn = get_connection()
    rows = conn.execute(
        "SELECT username, high_score FROM game_scores ORDER BY high_score DESC, updated_at ASC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return rows
