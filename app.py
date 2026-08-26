"""
app.py
======
RaumRadar - lokale Testversion als Flask-Webanwendung.

Starten:
    python app.py

Dann im Browser öffnen:
    http://127.0.0.1:5000
"""

from config import LOCAL_TIMEZONE
from calendar import monthrange
from datetime import datetime, date, time as uhrzeit, timedelta
import logging
import json
import os
import secrets
import time
from threading import Lock, Thread
from flask import Flask, jsonify, render_template, request, redirect, url_for, send_file, session, flash, abort
from flask_session import Session
from pywebpush import WebPushException, webpush

from untis_client import UntisClient, UntisError
import database

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = os.path.join(app.instance_path, "flask_session")
os.makedirs(app.config["SESSION_FILE_DIR"], exist_ok=True)
Session(app)

database.init_db()

ADMINS = ("GundLutw", "AndeJaro")

ROOM_DATA_CACHE = {}
ROOM_DATA_CACHE_SECONDS = 120
ROOM_DATA_CACHE_LOCK = Lock()
ROOM_DATA_REFRESH_LOCK = Lock()
TIMETABLE_CACHE = {}
TIMETABLE_CACHE_SECONDS = 300
TIMETABLE_CACHE_LOCK = Lock()
TIMETABLE_REFRESH_LOCK = Lock()
ALLOWED_ROOM_NAMES = {
    "101", "102", "103", "104", "105", "106", "107", "108", "114", "115",
    "120", "121", "125", "126", "127", "128", "129", "130", "131", "136",
    "137", "201", "203", "204", "206", "207", "208", "214", "220", "221",
    "225", "226", "227", "228", "229", "230", "231", "236", "237", "240",
    "A01", "A02", "A03", "A04", "A05", "A06", "A07", "A08", "A09", "A10",
    "A11", "B01", "B02", "B03", "B04", "B05", "E01", "E03", "E27", "E29",
    "E31",
}
BREAKS = ((830, 840), (940, 1000), (1100, 1110), (1250, 1300), (1400, 1410))
BELEGTE_RAEUME_MITTAGSPAUSE = [
    {"138"}, # Junior-SV
    {"138"}, # SV
    {"236"}, # MUN
    {""},
    {""}
]
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_CLAIMS = {"sub": os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com")}

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def get_current_stunde_zeit():
    """Grobe Hilfsfunktion: aktuelle Uhrzeit als HHMM-Zahl (Untis-Format)."""
    test_time = os.environ.get("TEST_TIME")
    if test_time:
        return normalize_time(test_time)
    now = datetime.now(LOCAL_TIMEZONE)
    return now.hour * 100 + now.minute


def go_to_next_lesson(current_time):
    # Pausen überspringen (ausgenommen Mittagspause)
    for start, end in BREAKS:
        if start <= current_time < end:
            return end
    return current_time

def get_local_date():
    return datetime.now(LOCAL_TIMEZONE).date()


def get_next_weekdays(start_day, count):
    weekdays = []
    current_day = start_day
    while len(weekdays) < count:
        if current_day.weekday() < 5:
            weekdays.append(current_day)
        current_day += timedelta(days=1)
    return weekdays


def add_one_month(value):
    month = value.month % 12 + 1
    year = value.year + (value.month == 12)
    return value.replace(year=year, month=month, day=min(value.day, monthrange(year, month)[1]))


def homework_date_limits():
    now = datetime.now(LOCAL_TIMEZONE)
    return now, now.date(), add_one_month(now.date()), now + timedelta(minutes=1)


@app.template_filter("format_homework_date")
def format_homework_date(value, include_time=False):
    if not value:
        return value
    try:
        parsed_value = datetime.fromisoformat(value) if include_time else date.fromisoformat(value)
    except (TypeError, ValueError):
        return value
    return parsed_value.strftime("%d.%m.%y %H:%M Uhr" if include_time else "%d.%m.%y")


def normalize_room_name(value):
    if value is None:
        return ""
    return str(value).strip().upper()


def normalize_time(value):
    if isinstance(value, int):
        return value
    digits = "".join(character for character in str(value) if character.isdigit())
    if not digits:
        return 0
    if len(digits) <= 2:
        return int(digits) * 100
    return int(digits[-4:])


def normalize_timetable_date(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    value = str(value or "").strip()
    if len(value) == 8 and value.isdigit():
        return datetime.strptime(value, "%Y%m%d").date().isoformat()
    for date_format in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[:10], date_format).date().isoformat()
        except ValueError:
            continue
    return None


def lesson_rooms(lesson):
    rooms = lesson.get("ro") or lesson.get("rooms") or []
    if isinstance(rooms, dict):
        rooms = [rooms]
    return rooms


def room_lookup(rooms):
    names_by_id = {}
    names_by_name = {}
    for room in rooms:
        if not isinstance(room, dict) or not room.get("name"):
            continue
        display_name = room["name"]
        normalized_name = normalize_room_name(display_name)
        names_by_name[normalized_name] = display_name
        if room.get("id") is not None:
            names_by_id[str(room["id"])] = display_name
    return names_by_id, names_by_name


def lesson_room_names(lesson, names_by_id):
    names = []
    for room in lesson_rooms(lesson):
        if isinstance(room, dict):
            name = room.get("name") or room.get("longName")
            if not name and room.get("id") is not None:
                name = names_by_id.get(str(room["id"]))
        else:
            name = room
        normalized_name = normalize_room_name(name)
        if normalized_name:
            names.append(normalized_name)
    return names


@app.route("/")
def index():
    if "untis_session" not in session:
        return redirect(url_for("login"))
    return redirect(url_for("free_rooms"))


@app.route("/service-worker.js")
def service_worker():
    response = app.send_static_file("service-worker.js")
    response.headers["Service-Worker-Allowed"] = "/"
    return response


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        school = request.form["school"]
        server = request.form["server"]
        username = request.form["username"]
        password = request.form["password"]

        client = UntisClient(school, server, username)
        try:
            client.login(username, password)
        except UntisError as e:
            flash(f"Login fehlgeschlagen: {e}")
            return redirect(url_for("login"))
        except Exception as e:
            flash(f"Verbindungsfehler: {e}")
            return redirect(url_for("login"))

        # Nur die kurzfristige Untis-Session-ID kommt in den Browser-Cookie.
        session["created_at"] = datetime.now(LOCAL_TIMEZONE).isoformat()
        session["untis_school"] = school
        session["untis_server"] = server
        session["untis_username"] = username
        session["untis_session"] = client.session_id
        session["untis_person_id"] = client.person_id

        flash("Erfolgreich eingeloggt!")
        return redirect(url_for("free_rooms"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    if session.get("untis_session"):
        client = UntisClient(session["untis_school"], session["untis_server"], session["untis_username"])
        client.session_id = session["untis_session"]
        client.logout()
    session.clear()
    return redirect(url_for("login"))


@app.route("/legal-notice")
def legal_notice():
    return render_template("legal_notice.html")


@app.route("/privacy-policy")
def privacy_policy():
    return render_template("privacy_policy.html")


def require_login_json():
    if "untis_session" not in session:
        return jsonify(error="Nicht eingeloggt."), 401
    return None


@app.get("/api/push/vapid-public-key")
def push_vapid_public_key():
    unauthorized = require_login_json()
    if unauthorized:
        return unauthorized
    if not VAPID_PUBLIC_KEY:
        return jsonify(error="Push-Benachrichtigungen sind noch nicht konfiguriert."), 503
    return jsonify(publicKey=VAPID_PUBLIC_KEY)


@app.post("/api/push/subscribe")
def push_subscribe():
    unauthorized = require_login_json()
    if unauthorized:
        return unauthorized
    subscription = request.get_json(silent=True) or {}
    keys = subscription.get("keys") or {}
    endpoint = subscription.get("endpoint")
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")
    if not all(isinstance(value, str) and value for value in (endpoint, p256dh, auth)):
        return jsonify(error="Ungültiges Push-Abonnement."), 400
    favorite_rooms = subscription.get("favoriteRooms", [])
    if not isinstance(favorite_rooms, list):
        return jsonify(error="Ungültige Favoritenliste."), 400
    favorite_rooms = [
        normalize_room_name(room)
        for room in favorite_rooms
        if normalize_room_name(room) in ALLOWED_ROOM_NAMES
    ]
    database.save_push_subscription(
        session["untis_username"],
        endpoint,
        p256dh,
        auth,
        favorite_rooms,
        session["untis_school"],
        session["untis_server"],
        session["untis_session"],
    )
    return jsonify(ok=True), 201


@app.post("/api/push/unsubscribe")
def push_unsubscribe():
    unauthorized = require_login_json()
    if unauthorized:
        return unauthorized
    subscription = request.get_json(silent=True) or {}
    endpoint = subscription.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint:
        return jsonify(error="Endpoint fehlt."), 400
    database.delete_push_subscription(session["untis_username"], endpoint)
    return jsonify(ok=True)


@app.post("/api/push/favorites")
def push_favorites():
    unauthorized = require_login_json()
    if unauthorized:
        return unauthorized
    payload = request.get_json(silent=True) or {}
    favorite_rooms = payload.get("favoriteRooms", [])
    if not isinstance(favorite_rooms, list):
        return jsonify(error="Ungültige Favoritenliste."), 400
    favorite_rooms = [
        normalize_room_name(room)
        for room in favorite_rooms
        if normalize_room_name(room) in ALLOWED_ROOM_NAMES
    ]
    subscription_endpoint = payload.get("endpoint")
    if not isinstance(subscription_endpoint, str) or not subscription_endpoint:
        return jsonify(error="Endpoint fehlt."), 400
    database.update_push_subscription_favorites(
        session["untis_username"], subscription_endpoint, favorite_rooms
    )
    return jsonify(ok=True)


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
            status_code = getattr(error.response, "status_code", None)
            if status_code in (401, 403, 404, 410):
                database.delete_push_subscription(username, subscription["endpoint"])
            else:
                app.logger.warning("Push-Versand fehlgeschlagen: %s", error)
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
                app.logger.warning("Push-Versand fehlgeschlagen: %s", error)
        database.update_push_subscription_notification_state(subscription["endpoint"], free_rooms)


def notify_homework(homework):
    username = homework["username"]
    subject = homework["subject"]
    content = homework["content"]

    time_left = date.fromisoformat(homework["due_date"]) - date.today()
    due_in = f"morgen" if time_left.days <= 1 else f"in {time_left.days} Tagen"

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
                app.logger.warning("Push-Versand fehlgeschlagen: %s", error)


def get_client_from_session():
    """Baut aus der Browser-Session einen UntisClient ohne Passwort auf."""
    if not session.get("created_at") or datetime.now(LOCAL_TIMEZONE) - datetime.fromisoformat(session["created_at"]) > timedelta(weeks=1):
        raise UntisError("Sitzung abgelaufen")

    client = UntisClient(session["untis_school"], session["untis_server"], session["untis_username"])
    client.session_id = session["untis_session"]
    client.person_id = session.get("untis_person_id")
    return client


def calculate_room_status(rooms, lessons, current_time):
    room_names_by_id, room_display_names = room_lookup(rooms)

    occupied_room_names = set()
    for lesson in lessons:
        start = normalize_time(lesson.get("startTime", 0))
        end = normalize_time(lesson.get("endTime", 0))
        if start <= current_time <= end:
            occupied_room_names.update(lesson_room_names(lesson, room_names_by_id))

    now = datetime.now(LOCAL_TIMEZONE).time()
    if uhrzeit(12, 10) <= now < uhrzeit(13, 0):
        occupied_room_names.update(BELEGTE_RAEUME_MITTAGSPAUSE[date.today().weekday()])

    allowed_room_names = {normalize_room_name(room_name) for room_name in ALLOWED_ROOM_NAMES}
    all_room_names = set(room_display_names) & allowed_room_names
    free_names = sorted(
        all_room_names - occupied_room_names,
        key=lambda room_name: room_display_names[room_name],
    )
    occupied_names = sorted(
        occupied_room_names & all_room_names,
        key=lambda room_name: room_display_names[room_name],
    )
    free_room_names = [room_display_names[name] for name in free_names]
    occupied_room_names = [room_display_names[name] for name in occupied_names]

    next_lessons = {room_display_names[room_name]: None for room_name in all_room_names}
    for lesson in lessons:
        start = normalize_time(lesson.get("startTime", 0))
        if start < current_time:
            continue
        for room_name in lesson_room_names(lesson, room_names_by_id):
            if room_name not in next_lessons:
                continue
            display_room_name = room_display_names[room_name]
            current_next = next_lessons[display_room_name]
            if current_next is None or start < current_next["start_time"]:
                end = normalize_time(lesson.get("endTime", 0))
                next_lessons[display_room_name] = {
                    "start_time": start,
                    "start": f"{start // 100:02d}:{start % 100:02d}",
                    "end": f"{end // 100:02d}:{end % 100:02d}",
                    "subject": ", ".join(
                        subject.get("name", "")
                        for subject in lesson.get("su", [])
                        if subject.get("name")
                    ) or "Unterricht",
                }

    return free_room_names, occupied_room_names, next_lessons, len(all_room_names)


def get_room_data(client):
    cache_key = (
        session["untis_school"],
        session["untis_server"],
        get_local_date(),
    )
    with ROOM_DATA_CACHE_LOCK:
        cached = ROOM_DATA_CACHE.get(cache_key)
        if cached and time.monotonic() - cached["created"] < ROOM_DATA_CACHE_SECONDS:
            return cached["rooms"], cached["lessons"]

    with ROOM_DATA_REFRESH_LOCK:
        with ROOM_DATA_CACHE_LOCK:
            cached = ROOM_DATA_CACHE.get(cache_key)
            if cached and time.monotonic() - cached["created"] < ROOM_DATA_CACHE_SECONDS:
                return cached["rooms"], cached["lessons"]

        rooms = client.get_rooms()
        lessons = client.get_full_timetable(day=get_local_date())
        with ROOM_DATA_CACHE_LOCK:
            ROOM_DATA_CACHE[cache_key] = {
                "created": time.monotonic(),
                "rooms": rooms,
                "lessons": lessons,
            }
        return rooms, lessons


@app.route("/free-rooms")
def free_rooms():
    if "untis_session" not in session:
        return redirect(url_for("login"))

    try:
        client = get_client_from_session()
        rooms, lessons = get_room_data(client)
    except UntisError as e:
        session.clear()
        flash(f"Fehler beim Abrufen der Daten: {e}")
        return redirect(url_for("login"))

    current_time = go_to_next_lesson(get_current_stunde_zeit())

    if not lessons:
        flash("Untis hat für heute keine Stundenplandaten geliefert. Die Raumbelegung ist deshalb nicht sicher bestimmbar.")

    free_room_names, occupied_sorted, next_lessons, total_rooms = calculate_room_status(
        rooms, lessons, current_time
    )
    if lessons:
        notify_free_favorite_rooms(session["untis_username"], free_room_names)

    return render_template(
        "free_rooms.html",
        free_rooms=free_room_names,
        occupied_rooms=occupied_sorted,
        next_lessons=next_lessons,
        data_available=bool(lessons),
        total_rooms=total_rooms,
        current_time=f"{current_time // 100:02d}:{current_time % 100:02d}",
    )


@app.route("/homework", methods=["GET", "POST"])
def homework():
    if "untis_session" not in session:
        return redirect(url_for("login"))

    username = session["untis_username"]

    if request.method == "POST":
        subject = request.form["subject"]
        content = request.form["content"]
        due_date_input = request.form.get("due_date") or None
        reminder_input = request.form.get("reminder") or None
        now, minimum_due_date, maximum_due_date, minimum_reminder = homework_date_limits()

        try:
            due_date_value = date.fromisoformat(due_date_input) if due_date_input else None
            reminder_value = (
                datetime.fromisoformat(reminder_input).replace(tzinfo=LOCAL_TIMEZONE)
                if reminder_input else None
            )
        except ValueError:
            flash("Ungültiges Datum oder ungültige Erinnerung.")
            return redirect(url_for("homework"))

        if due_date_value and not minimum_due_date <= due_date_value <= maximum_due_date:
            flash("Die Frist muss heute oder innerhalb des nächsten Monats liegen.")
            return redirect(url_for("homework"))
        if reminder_value and not due_date_value:
            flash("Eine Erinnerung ist nur mit einer Frist möglich.")
            return redirect(url_for("homework"))
        if reminder_value:
            due_date_end = datetime.combine(due_date_value, uhrzeit.max, tzinfo=LOCAL_TIMEZONE)
            maximum_reminder = datetime.combine(maximum_due_date, uhrzeit.max, tzinfo=LOCAL_TIMEZONE)
            if not minimum_reminder <= reminder_value <= maximum_reminder or reminder_value > due_date_end:
                flash("Die Erinnerung muss mindestens 1 Minute vorausliegen und vor der Frist liegen.")
                return redirect(url_for("homework"))

        due_date = due_date_value.isoformat() if due_date_value else None
        reminder = reminder_value.isoformat() if reminder_value else None
        database.add_homework(username, subject, content, due_date, reminder)
        flash("Hausaufgabe hinzugefügt!")
        return redirect(url_for("homework"))

    items = database.get_homework(username)
    now, minimum_due_date, maximum_due_date, minimum_reminder = homework_date_limits()
    return render_template(
        "homework.html",
        items=items,
        minimum_due_date=minimum_due_date.isoformat(),
        maximum_due_date=maximum_due_date.isoformat(),
        minimum_reminder=minimum_reminder.strftime("%Y-%m-%dT%H:%M"),
        maximum_reminder=maximum_due_date.isoformat() + "T23:59",
    )


def get_timetable(client, days):
    person_id = client.person_id

    cache_key = (
        person_id,
        get_local_date(),
    )
    with TIMETABLE_CACHE_LOCK:
        cached = TIMETABLE_CACHE.get(cache_key)
        if cached and time.monotonic() - cached["created"] < TIMETABLE_CACHE_SECONDS:
            return cached["lessons"]

    with TIMETABLE_REFRESH_LOCK:
        with TIMETABLE_CACHE_LOCK:
            cached = TIMETABLE_CACHE.get(cache_key)
            if cached and time.monotonic() - cached["created"] < TIMETABLE_CACHE_SECONDS:
                return cached["lessons"]

        lessons = client.get_timetable_for_student(person_id, days=days)
        with TIMETABLE_CACHE_LOCK:
            TIMETABLE_CACHE[cache_key] = {
                "created": time.monotonic(),
                "lessons": lessons,
            }
        return lessons


@app.route("/timetable")
def timetable():
    if "untis_session" not in session:
        return redirect(url_for("login"))

    today = get_local_date()
    timetable_dates = get_next_weekdays(today, 5)
    try:
        client = get_client_from_session()
        lessons = get_timetable(client, days=timetable_dates)
    except UntisError as error:
        session.clear()
        flash(f"Fehler beim Abrufen der Daten: {error}")
        return redirect(url_for("login"))

    current_time = get_current_stunde_zeit()
    timetable_days = {day.isoformat(): [] for day in timetable_dates}
    for lesson in lessons or []:
        if not isinstance(lesson, dict):
            continue
        lesson_date = normalize_timetable_date(lesson.get("date"))
        if lesson_date is None:
            lesson_date = today.isoformat()
        if date.fromisoformat(lesson_date).weekday() >= 5:
            continue
        start_time = normalize_time(lesson.get("startTime", 0))
        end_time = normalize_time(lesson.get("endTime", 0))

        element = client.get_lesson_details(lesson)
        details = element["blocks"][0][0]
        period = details["periods"][0]
        student = element.get("elementName")
        subject = details["subjectNameLong"] if details.get("subjectNameLong") and len(details["subjectNameLong"]) <= 15 else details.get("subjectName")
        info = (inf if (inf := details.get("lessonInfo")) and len(inf) < 35 else inf[:32] + "..." if inf else None)
        substitute_text = (subst_text if (subst_text := period.get("substText")) and len(subst_text) < 13 else None)

        room_changes = []
        for substitution in details.get("roomSubstitutions", []):
            org_room = substitution.get("orgRoom")
            cur_room = substitution.get("curRoom")

            if org_room and cur_room and org_room.get("id") != cur_room.get("id"):
                room_changes.append({
                    "original_room": org_room.get("name") or "",
                    "new_room": cur_room.get("name") or ""
                })

        if substitute_text or room_changes:
            rooms = []

            substitution = {
                "text": substitute_text,
                "original_room": ", ".join(change["original_room"] for change in room_changes),
                "new_room": ", ".join(change["new_room"] for change in room_changes)
            }
        else:
            substitution = None
            rooms = period.get("rooms")
            teachers = [teacher["name"] for teacher in period.get("teachers")]

        if period["isCancelled"]:
            status = "ausgefallen"
        elif lesson_date <= today.isoformat() and end_time <= current_time:
            status = "vorbei"
        elif lesson_date == today.isoformat() and start_time <= current_time < end_time:
            status = "läuft gerade"
        elif substitution or not any(teachers) or not any(rooms):
            status = "geändert"
        else:
            status = ""

        timetable_days.setdefault(lesson_date, []).append({
            "date": lesson_date,
            "subject": subject or "Unterricht",
            "start": f"{start_time // 100:02d}:{start_time % 100:02d}",
            "end": f"{end_time // 100:02d}:{end_time % 100:02d}",
            "room": ", ".join(
                room.get("name") if isinstance(room, dict) else str(room)
                for room in rooms
            ) if any(rooms) else "",
            "teacher": ", ".join(teachers) if any(teachers) else "",
            "status": status,
            "info": info or "",
            "substitution": substitution
        })

    for day_lessons in timetable_days.values():
        day_lessons.sort(key=lambda lesson: (lesson["start"], lesson["subject"]))

    timetable_days = [
        {
            "date": WEEKDAYS[date.fromisoformat(day).weekday()],
            "is_today": day == today.isoformat(),
            "lessons": day_lessons,
        }
        for day, day_lessons in sorted(timetable_days.items())
    ]
    return render_template(
        "timetable.html",
        student=student,
        timetable_days=timetable_days,
        timetable_date=f"{WEEKDAYS[today.weekday()]}, " + today.strftime("%d.%m.%Y"),
    )


@app.route("/homework/<int:homework_id>/toggle", methods=["POST"])
def toggle_homework(homework_id):
    database.toggle_homework_done(homework_id, session["untis_username"])
    return redirect(url_for("homework"))


@app.route("/homework/<int:homework_id>/delete", methods=["POST"])
def delete_homework(homework_id):
    database.delete_homework(homework_id, session["untis_username"])
    return redirect(url_for("homework"))


@app.route("/database")
def send_database():
    if "untis_session" not in session:
        return redirect(url_for("login"))

    if session["untis_username"] not in ADMINS:
        abort(403)

    try:
        return send_file("raumradar.db")

    except FileNotFoundError:
        return jsonify({
            "error": "Database file not found"
        }), 404


"""
Scheduler
===========
Hintergrundprozess für Raumaktualisierungen, Hausaufgaben-Erinnerungen
und Push-Benachrichtigungen für bevorzugte Räume.
"""

LOGGER = logging.getLogger("raumradar.scheduler")
ROOM_INTERVAL_SECONDS = max(30, int(os.environ.get("ROOM_INTERVAL_SECONDS", "120")))
REMINDER_INTERVAL_SECONDS = max(30, int(os.environ.get("REMINDER_INTERVAL_SECONDS", "60")))
LESSON_INTERVAL_SECONDS = max(300, int(os.environ.get("LESSON_INTERVAL_SECONDS", "600")))
TIMETABLE_INTERVAL_SECONDS = max(900, int(os.environ.get("TIMETABLE_INTERVAL_SECONDS", "1800")))


def refresh_subscribed_users():
    """Refresh each user's timetable and notify newly free favorite rooms."""
    subscriptions = database.get_all_push_subscriptions()
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
            rooms = client.get_rooms()
            lessons = client.get_full_timetable(day=get_local_date())
            if not lessons:
                LOGGER.warning("Keine Stundenplandaten für %s erhalten", username)
                continue
            free_rooms, _occupied_rooms, _next_lessons, _total_rooms = calculate_room_status(
                rooms, lessons, get_current_stunde_zeit()
            )
            notify_free_favorite_rooms(username, free_rooms)
            refreshed += 1
        except Exception as error:
            LOGGER.warning("Raum-Refresh für %s fehlgeschlagen: %s", username, error)

    return refreshed


def send_homework_reminders():
    homeworks = database.get_all_homework_reminders()

    for homework in homeworks:
        notify_homework(homework)
    return len(homeworks)


def run_room_scheduler():
    LOGGER.info("Raum-Scheduler gestartet, Intervall: %s Sekunden", ROOM_INTERVAL_SECONDS)
    while True:
        try:
            refreshed = refresh_subscribed_users()
            LOGGER.info("Raum-Scheduler: %s Benutzer aktualisiert", refreshed)
        except Exception as error:
            LOGGER.exception("Unerwarteter Fehler im Raum Scheduler-Zyklus: %s", error)

        time.sleep(ROOM_INTERVAL_SECONDS)


def run_reminder_scheduler():
    LOGGER.info("Erinnerungen-Scheduler gestartet, Intervall: %s Sekunden", REMINDER_INTERVAL_SECONDS)
    while True:
        try:
            reminders = send_homework_reminders()
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


def start_background_scheduler():
    if os.environ.get("START_SCHEDULER", "1") == "0":
        return
    debug = os.environ.get("FLASK_DEBUG") == "1"
    if debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return

    # Thread(target=run_lesson_scheduler, daemon=True).start()
    # Thread(target=run_timetable_scheduler, daemon=True).start()
    Thread(target=run_room_scheduler, daemon=True).start()
    Thread(target=run_reminder_scheduler, daemon=True).start()

start_background_scheduler()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )