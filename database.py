"""
database.py
===========
Lokale SQLite-Datenbank für Notizen, Hausaufgaben, Benachrichtigungen & Anmeldedaten.
Kein Server nötig -- die Datei raumradar.db wird automatisch angelegt.

Leider wird die Datenbank im Moment immer bei neuen Updates zurückgesetzt, da sie nicht auf Render gespeichert bleibt.
"""

import aiosqlite
import json
from pathlib import Path
from datetime import datetime
from config import LOCAL_TIMEZONE
# from crypto import encrypt_password, decrypt_password

DB_PATH = Path(__file__).parent / "raumradar.db"


async def get_connection():
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    return conn


async def init_db():
    conn = await get_connection()
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS homework (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            subject TEXT NOT NULL,
            content TEXT NOT NULL,
            due_date TEXT,
            reminder TEXT,
            done INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS game_scores (
            username TEXT PRIMARY KEY,
            high_score REAL NOT NULL DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS logins (
            username TEXT PRIMARY KEY NOT NULL,
            password TEXT NOT NULL
        )
    """)
    await conn.execute("""
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
            await conn.execute(f"ALTER TABLE push_subscriptions ADD COLUMN {column_name} {definition}")
        except aiosqlite.OperationalError:
            pass
    await conn.commit()
    await conn.close()


async def save_untis_password(username, password):
    return ""
    # conn = await get_connection()
    # conn.execute("""
    #     INSERT INTO logins (username, password) VALUES (?, ?)
    #     ON CONFLICT(username) DO UPDATE SET password = excluded.password
    #     """,
    #     (username, encrypt_password(password))
    # )
    # conn.commit()
    # conn.close()


async def delete_untis_password(username):
    conn = await get_connection()
    await conn.execute(
        "DELETE FROM logins WHERE username = ?",
        (username,)
    )
    await conn.commit()
    await conn.close()


async def get_untis_password(username):
    return ""
    # conn = await get_connection()
    # row = conn.execute(
    #     "SELECT password FROM logins WHERE username = ?", (username,)
    # ).fetchone()

    # if row is None:
    #     return

    # return decrypt_password(row["password"])


async def add_homework(username, subject, content, due_date, reminder):
    conn = await get_connection()
    await conn.execute(
        "INSERT INTO homework (username, subject, content, due_date, reminder) VALUES (?, ?, ?, ?, ?)",
        (username, subject, content, due_date, reminder),
    )
    await conn.commit()
    await conn.close()


async def get_homework(username):
    conn = await get_connection()
    cursor = await conn.execute(
        "SELECT * FROM homework WHERE username = ? ORDER BY due_date IS NULL, due_date ASC",
        (username,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    await conn.close()
    return rows


async def toggle_homework_done(homework_id, username):
    conn = await get_connection()
    await conn.execute(
        "UPDATE homework SET done = NOT done WHERE id = ? AND username = ?",
        (homework_id, username),
    )
    await conn.commit()
    await conn.close()


async def delete_homework(homework_id, username):
    conn = await get_connection()
    await conn.execute("DELETE FROM homework WHERE id = ? AND username = ?", (homework_id, username))
    await conn.commit()
    await conn.close()


async def delete_reminder(homework_id, username):
    conn = await get_connection()
    await conn.execute("UPDATE homework SET reminder = NULL WHERE id = ? AND username = ?", (homework_id, username))
    await conn.commit()
    await conn.close()

async def get_all_homework_reminders():
    conn = await get_connection()
    cursor = await conn.execute(
        """
        SELECT id, username, subject, content, due_date
        FROM homework
        WHERE done = FALSE AND reminder <= ?
        """,
        (datetime.now(LOCAL_TIMEZONE).isoformat(),)
    )
    rows = await cursor.fetchall()
    await cursor.close()
    await conn.close()
    return rows


async def save_push_subscription(
    username,
    endpoint,
    p256dh,
    auth,
    favorite_rooms=None,
    untis_school=None,
    untis_server=None,
    untis_session=None,
):
    conn = await get_connection()
    favorite_rooms_json = json.dumps(sorted(set(favorite_rooms or [])))
    await conn.execute(
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
    await conn.commit()
    await conn.close()


async def update_push_subscription_session(username, session_id):
    conn = await get_connection()
    await conn.execute(
        """
        UPDATE push_subscriptions SET untis_session = ?
        WHERE username = ?
        """,
        (session_id, username),
    )
    await conn.commit()
    await conn.close()


async def delete_push_subscription(username, endpoint):
    conn = await get_connection()
    await conn.execute(
        "DELETE FROM push_subscriptions WHERE username = ? AND endpoint = ?",
        (username, endpoint),
    )
    await conn.commit()
    await conn.close()


async def update_push_subscription_favorites(username, endpoint, favorite_rooms):
    conn = await get_connection()
    await conn.execute(
        """
        UPDATE push_subscriptions
        SET favorite_rooms = ?, updated_at = CURRENT_TIMESTAMP
        WHERE username = ? AND endpoint = ?
        """,
        (json.dumps(sorted(set(favorite_rooms))), username, endpoint),
    )
    await conn.commit()
    await conn.close()


async def get_push_subscriptions(username):
    conn = await get_connection()
    cursor = await conn.execute(
        """
         SELECT endpoint, p256dh, auth, favorite_rooms, last_notified_free_rooms,
             untis_school, untis_server, untis_session
        FROM push_subscriptions WHERE username = ?
        """,
        (username,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    await conn.close()
    return rows


async def get_all_push_subscriptions():
    conn = await get_connection()
    cursor = await conn.execute(
        """
        SELECT username, endpoint, p256dh, auth, favorite_rooms, last_notified_free_rooms,
               untis_school, untis_server, untis_session
        FROM push_subscriptions
        """
    )
    rows = await cursor.fetchall()
    await cursor.close()
    await conn.close()
    return rows


async def update_push_subscription_notification_state(endpoint, free_rooms):
    conn = await get_connection()
    await conn.execute(
        """
        UPDATE push_subscriptions
        SET last_notified_free_rooms = ?, updated_at = CURRENT_TIMESTAMP
        WHERE endpoint = ?
        """,
        (json.dumps(sorted(set(free_rooms))), endpoint),
    )
    await conn.commit()
    await conn.close()


async def submit_game_score(username, score):
    """Speichert den Score nur, wenn er höher als der bisherige Highscore ist."""
    conn = await get_connection()
    await conn.execute(
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
    await conn.commit()
    await conn.close()


async def get_leaderboard(limit=20):
    conn = await get_connection()
    cursor = await conn.execute(
        "SELECT username, high_score FROM game_scores ORDER BY high_score DESC, updated_at ASC LIMIT ?",
        (limit,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    await conn.close()
    return rows