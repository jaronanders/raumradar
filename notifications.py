"""Push notification delivery independent of Flask."""

import json
import logging
import os

from pywebpush import WebPushException, webpush

import database
from config import normalize_room_name

LOGGER = logging.getLogger("raumradar.notifications")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_CLAIMS = {"sub": os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com")}


def send_push_to_subscription(subscription, title, body, url="/"):
    push_subscription = {
        "endpoint": subscription["endpoint"],
        "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
    }
    webpush(
        subscription_info=push_subscription,
        data=json.dumps({"title": title, "body": body, "url": url}),
        vapid_private_key=VAPID_PRIVATE_KEY,
        vapid_claims=VAPID_CLAIMS,
    )


def send_push_notification(username, title, body, url="/"):
    """Send a notification to all of a user's registered browsers."""
    if not VAPID_PRIVATE_KEY:
        raise RuntimeError("VAPID_PRIVATE_KEY ist nicht konfiguriert.")

    sent = 0
    for subscription in database.get_push_subscriptions(username):
        try:
            send_push_to_subscription(subscription, title, body, url)
            sent += 1
        except WebPushException as error:
            status_code = getattr(getattr(error, "response", None), "status_code", None)
            if status_code in (401, 403, 404, 410):
                database.delete_push_subscription(username, subscription["endpoint"])
            else:
                LOGGER.warning("Push-Versand fehlgeschlagen: %s", error)
    return sent


def notify_free_favorite_rooms(username, free_room_names):
    """Notify a user once when one of their favorites becomes free."""
    free_rooms = {normalize_room_name(room) for room in free_room_names}
    for subscription in database.get_push_subscriptions(username):
        favorite_rooms = set(json.loads(subscription["favorite_rooms"] or "[]"))
        previously_free = set(json.loads(subscription["last_notified_free_rooms"] or "[]"))
        newly_free = (favorite_rooms & free_rooms) - previously_free
        try:
            for room in sorted(newly_free):
                send_push_to_subscription(
                    subscription,
                    "Dein favorisierter Raum ist frei",
                    f"Raum {room} ist jetzt leer.",
                    "/free-rooms",
                )
        except WebPushException as error:
            status_code = getattr(getattr(error, "response", None), "status_code", None)
            if status_code in (401, 403, 404, 410):
                database.delete_push_subscription(username, subscription["endpoint"])
            else:
                LOGGER.warning("Push-Versand fehlgeschlagen: %s", error)
        database.update_push_subscription_notification_state(subscription["endpoint"], free_rooms)


def notify_homework(homework):
    username = homework["username"]
    subject = homework["subject"]
    content = homework["content"]

    from datetime import date

    time_left = date.fromisoformat(homework["due_date"]) - date.today()
    due_in = "morgen" if time_left.days <= 1 else f"in {time_left.days} Tagen"

    database.delete_reminder(homework["id"], username)

    for subscription in database.get_push_subscriptions(username):
        try:
            send_push_to_subscription(
                subscription,
                f"Deine Hausaufgabe für {subject} ist {due_in} fällig",
                content,
                "/homework",
            )
        except WebPushException as error:
            status_code = getattr(getattr(error, "response", None), "status_code", None)
            if status_code in (401, 403, 404, 410):
                database.delete_push_subscription(username, subscription["endpoint"])
            else:
                LOGGER.warning("Push-Versand fehlgeschlagen: %s", error)
