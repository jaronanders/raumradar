"""
Scheduler
===========
Hintergrundprozess für Raumaktualisierungen, Hausaufgaben-Erinnerungen
und Push-Benachrichtigungen für bevorzugte Räume.
"""

import time
import os
import logging
import asyncio

from config import get_local_date, get_current_stunde_zeit, calculate_room_status
import database
from notifications import notify_free_favorite_rooms, notify_homework
from untis_client import UntisClient

LOGGER = logging.getLogger("raumradar.scheduler")
ROOM_INTERVAL_SECONDS = max(30, int(os.environ.get("ROOM_INTERVAL_SECONDS", "120")))
REMINDER_INTERVAL_SECONDS = max(30, int(os.environ.get("REMINDER_INTERVAL_SECONDS", "60")))
LESSON_INTERVAL_SECONDS = max(300, int(os.environ.get("LESSON_INTERVAL_SECONDS", "600")))
TIMETABLE_INTERVAL_SECONDS = max(900, int(os.environ.get("TIMETABLE_INTERVAL_SECONDS", "1800")))


async def refresh_subscribed_users():
    """Refresh each user's timetable and notify newly free favorite rooms."""
    subscriptions = await database.get_all_push_subscriptions()
    users = {}
    for subscription in subscriptions:
        key = (
            subscription["username"],
            subscription["untis_school"],
            subscription["untis_server"],
            subscription["untis_session"],
        )
        users[key] = subscription

    refreshed = 0
    for (username, school, server, session_id), _subscription in users.items():
        if not all((school, server, session_id)):
            LOGGER.info("Überspringe %s: keine aktuelle Untis-Session gespeichert", username)
            continue

        client = UntisClient(school, server, username)
        client.session_id = session_id
        try:
            rooms = await client.get_rooms()
            lessons = await client.get_full_timetable(day=get_local_date())
            if not lessons:
                LOGGER.warning("Keine Stundenplandaten für %s erhalten", username)
                continue
            free_rooms, _occupied_rooms, _next_lessons, _total_rooms = calculate_room_status(
                rooms, lessons, get_current_stunde_zeit()
            )
            await notify_free_favorite_rooms(username, free_rooms)
            refreshed += 1
        except Exception as error:
            LOGGER.warning("Raum-Refresh für %s fehlgeschlagen: %s", username, error)

    return refreshed


async def send_homework_reminders():
    homeworks = await database.get_all_homework_reminders()

    for homework in homeworks:
        await notify_homework(homework)
    return len(homeworks)


def run_room_scheduler():
    LOGGER.info("Raum-Scheduler gestartet, Intervall: %s Sekunden", ROOM_INTERVAL_SECONDS)
    while True:
        try:
            refreshed = asyncio.run(refresh_subscribed_users())
            LOGGER.info("Raum-Scheduler: %s Benutzer aktualisiert", refreshed)
        except Exception as error:
            LOGGER.exception("Unerwarteter Fehler im Raum Scheduler-Zyklus: %s", error)

        time.sleep(ROOM_INTERVAL_SECONDS)


def run_reminder_scheduler():
    LOGGER.info("Erinnerungen-Scheduler gestartet, Intervall: %s Sekunden", REMINDER_INTERVAL_SECONDS)
    while True:
        try:
            reminders = asyncio.run(send_homework_reminders())
            LOGGER.info("Erinnerungen-Scheduler: %s Erinnerungen gesendet", reminders)
        except Exception as error:
            LOGGER.exception("Unerwarteter Fehler im Erinnerungen Scheduler-Zyklus: %s", error)

        time.sleep(REMINDER_INTERVAL_SECONDS)


def run_lesson_scheduler():
    LOGGER.info("Unterrichtsstunden-Scheduler gestartet, Intervall: %s Sekunden", )
    while True:
        try:
            pass
        except Exception as error:
            LOGGER.exception("Unerwarteter Fehler im Unterrichtsstunden Scheduler-Zyklus: %s", error)

        time.sleep(LESSON_INTERVAL_SECONDS)


def run_timetable_scheduler():
    LOGGER.info("Stundenplan-Scheduler gestartet, Intervall: %s Sekunden", )
    while True:
        try:
            pass
        except Exception as error:
            LOGGER.exception("Unerwarteter Fehler im Stundenplan Scheduler-Zyklus: %s", error)

        time.sleep(TIMETABLE_INTERVAL_SECONDS)