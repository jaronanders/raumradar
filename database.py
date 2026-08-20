"""
database.py
===========
Sehr einfache lokale SQLite-Datenbank für Notizen & Hausaufgaben.
Kein Server nötig -- die Datei raumradar.db wird automatisch angelegt.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "raumradar.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
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
