"""
database.py
===========
Sehr einfache lokale SQLite-Datenbank für Notizen & Hausaufgaben.
Kein Server nötig -- die Datei raumradar.db wird automatisch angelegt.
"""

import sqlite3
import json
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            endpoint TEXT NOT NULL UNIQUE,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            favorite_rooms TEXT NOT NULL DEFAULT '[]',
            last_notified_free_rooms TEXT NOT NULL DEFAULT '[]',
            untis_school TEXT,
            untis_server TEXT,
            untis_session TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for column_name, definition in (
        ("favorite_rooms", "TEXT NOT NULL DEFAULT '[]'"),
        ("last_notified_free_rooms", "TEXT NOT NULL DEFAULT '[]'"),
        ("untis_school", "TEXT"),
        ("untis_server", "TEXT"),
        ("untis_session", "TEXT"),
    ):
        try:
            conn.execute(f"ALTER TABLE push_subscriptions ADD COLUMN {column_name} {definition}")
        except sqlite3.OperationalError:
            pass
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


def save_push_subscription(
    username,
    endpoint,
    p256dh,
    auth,
    favorite_rooms=None,
    untis_school=None,
    untis_server=None,
    untis_session=None,
):
    conn = get_connection()
    favorite_rooms_json = json.dumps(sorted(set(favorite_rooms or [])))
    conn.execute(
        """
        INSERT INTO push_subscriptions
            (username, endpoint, p256dh, auth, favorite_rooms, untis_school, untis_server, untis_session)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(endpoint) DO UPDATE SET
            username = excluded.username,
            p256dh = excluded.p256dh,
            auth = excluded.auth,
            favorite_rooms = excluded.favorite_rooms,
            untis_school = excluded.untis_school,
            untis_server = excluded.untis_server,
            untis_session = excluded.untis_session,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            username,
            endpoint,
            p256dh,
            auth,
            favorite_rooms_json,
            untis_school,
            untis_server,
            untis_session,
        ),
    )
    conn.commit()
    conn.close()


def delete_push_subscription(username, endpoint):
    conn = get_connection()
    conn.execute(
        "DELETE FROM push_subscriptions WHERE username = ? AND endpoint = ?",
        (username, endpoint),
    )
    conn.commit()
    conn.close()


def update_push_subscription_favorites(username, endpoint, favorite_rooms):
    conn = get_connection()
    conn.execute(
        """
        UPDATE push_subscriptions
        SET favorite_rooms = ?, updated_at = CURRENT_TIMESTAMP
        WHERE username = ? AND endpoint = ?
        """,
        (json.dumps(sorted(set(favorite_rooms))), username, endpoint),
    )
    conn.commit()
    conn.close()


def get_push_subscriptions(username):
    conn = get_connection()
    rows = conn.execute(
        """
         SELECT endpoint, p256dh, auth, favorite_rooms, last_notified_free_rooms,
             untis_school, untis_server, untis_session
        FROM push_subscriptions WHERE username = ?
        """,
        (username,),
    ).fetchall()
    conn.close()
    return rows


def get_all_push_subscriptions():
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT username, endpoint, p256dh, auth, favorite_rooms, last_notified_free_rooms,
               untis_school, untis_server, untis_session
        FROM push_subscriptions
        """
    ).fetchall()
    conn.close()
    return rows


def update_push_subscription_notification_state(endpoint, free_rooms):
    conn = get_connection()
    conn.execute(
        """
        UPDATE push_subscriptions
        SET last_notified_free_rooms = ?, updated_at = CURRENT_TIMESTAMP
        WHERE endpoint = ?
        """,
        (json.dumps(sorted(set(free_rooms))), endpoint),
    )
    conn.commit()
    conn.close()
