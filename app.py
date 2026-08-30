"""
app.py
======
RaumRadar - lokale Testversion als Flask-Webanwendung.

Starten:
    python app.py

Dann im Browser öffnen:
    http://127.0.0.1:5000
"""

from config import *
from datetime import datetime, date, time as uhrzeit, timedelta
import os
import asyncio
import secrets
import time
import logging
from threading import Lock, Thread

logging.basicConfig(level=logging.INFO)

from flask import Flask, jsonify, render_template, request, redirect, url_for, send_file, session, flash, abort
from flask_session import Session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from untis_client import UntisClient, UntisError
import database
from notifications import notify_free_favorite_rooms
from scheduler import run_reminder_scheduler, run_room_scheduler, run_lesson_scheduler, run_timetable_scheduler

app = Flask(__name__)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per 5 minutes", "500 per hour", "1000 per day"]
)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = os.path.join(app.instance_path, "flask_session")
app.config["MAINTENANCE_MODE"] = (os.getenv("MAINTENANCE_MODE", "false").lower() == "true")
os.makedirs(app.config["SESSION_FILE_DIR"], exist_ok=True)
Session(app)

asyncio.run(database.init_db())

ADMINS = ("GundLutw", "AndeJaro")

ROOM_DATA_CACHE = {}
ROOM_DATA_CACHE_SECONDS = 120
ROOM_DATA_CACHE_LOCK = Lock()
ROOM_DATA_REFRESH_LOCK = Lock()
TIMETABLE_CACHE = {}
TIMETABLE_CACHE_SECONDS = 300
TIMETABLE_CACHE_LOCK = Lock()
TIMETABLE_REFRESH_LOCK = Lock()
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


@app.template_filter("format_homework_date")
def format_homework_date(value, include_time=False):
    if not value:
        return value
    try:
        parsed_value = datetime.fromisoformat(value) if include_time else date.fromisoformat(value)
    except (TypeError, ValueError):
        return value
    return parsed_value.strftime("%d.%m.%y %H:%M Uhr" if include_time else "%d.%m.%y")


@app.before_request
def maintenance_check():
    if (app.config["MAINTENANCE_MODE"] and not request.path.startswith("/static/") and request.path not in
        ("/maintenance", "/database", "/login", "/impressum", "/datenschutzerklärung")):
        if session:
            session.clear()

        return render_template("maintenance.html"), 503


@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404


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
async def login():
    if request.method == "POST":
        school = request.form["school"]
        server = request.form["server"]
        username = request.form["username"]
        password = request.form["password"]

        client = UntisClient(school, server, username)
        try:
            await client.login(username, password)
        except UntisError as e:
            flash(f"Login fehlgeschlagen: {e}")
            return redirect(url_for("login"))
        except Exception:
            flash("Login fehlgeschlagen: Verbindungsfehler")
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
async def logout():
    if session.get("untis_session"):
        client = UntisClient(session["untis_school"], session["untis_server"], session["untis_username"])
        client.session_id = session["untis_session"]
        await client.logout()
    session.clear()
    return redirect(url_for("login"))


@app.route("/impressum")
def legal_notice():
    return render_template("legal_notice.html")


@app.route("/datenschutzerklärung")
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
async def push_subscribe():
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
    await database.save_push_subscription(
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
async def push_unsubscribe():
    unauthorized = require_login_json()
    if unauthorized:
        return unauthorized
    subscription = request.get_json(silent=True) or {}
    endpoint = subscription.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint:
        return jsonify(error="Endpoint fehlt."), 400
    await database.delete_push_subscription(session["untis_username"], endpoint)
    return jsonify(ok=True)


@app.post("/api/push/favorites")
async def push_favorites():
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
    await database.update_push_subscription_favorites(
        session["untis_username"], subscription_endpoint, favorite_rooms
    )
    return jsonify(ok=True)


async def get_client_from_session():
    """Baut aus der Browser-Session einen UntisClient ohne Passwort auf."""
    if not session.get("created_at") or datetime.now(LOCAL_TIMEZONE) - datetime.fromisoformat(session["created_at"]) > timedelta(weeks=1):
        await database.delete_untis_password(session["untis_username"])
        session.clear()
        raise UntisError("not authenticated")

    client = UntisClient(session["untis_school"], session["untis_server"], session["untis_username"])
    client.session_id = session["untis_session"]
    client.person_id = session.get("untis_person_id")
    return client


async def get_room_data(client):
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

        rooms = await client.get_rooms()
        lessons = await client.get_full_timetable(day=get_local_date())
        with ROOM_DATA_CACHE_LOCK:
            ROOM_DATA_CACHE[cache_key] = {
                "created": time.monotonic(),
                "rooms": rooms,
                "lessons": lessons,
            }
        return rooms, lessons


@app.route("/freie-räume")
async def free_rooms():
    if "untis_session" not in session:
        return redirect(url_for("login"))

    try:
        client = await get_client_from_session()
        rooms, lessons = await get_room_data(client)
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
        await notify_free_favorite_rooms(session["untis_username"], free_room_names)

    return render_template(
        "free_rooms.html",
        free_rooms=free_room_names,
        occupied_rooms=occupied_sorted,
        next_lessons=next_lessons,
        data_available=bool(lessons),
        total_rooms=total_rooms,
        current_time=f"{current_time // 100:02d}:{current_time % 100:02d}",
    )


@app.route("/hausaufgaben", methods=["GET", "POST"])
async def homework():
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
        await database.add_homework(username, subject, content, due_date, reminder)
        flash("Hausaufgabe hinzugefügt!")
        return redirect(url_for("homework"))

    items = await database.get_homework(username)
    now, minimum_due_date, maximum_due_date, minimum_reminder = homework_date_limits()
    return render_template(
        "homework.html",
        items=items,
        minimum_due_date=minimum_due_date.isoformat(),
        maximum_due_date=maximum_due_date.isoformat(),
        minimum_reminder=minimum_reminder.strftime("%Y-%m-%dT%H:%M"),
        maximum_reminder=maximum_due_date.isoformat() + "T23:59",
    )


async def get_timetable(client, timetable_dates, days, today=get_local_date()):
    person_id = client.person_id

    cache_key = (
        person_id,
        today,
    )
    with TIMETABLE_CACHE_LOCK:
        cached = TIMETABLE_CACHE.get(cache_key)
        if cached and time.monotonic() - cached["created"] < TIMETABLE_CACHE_SECONDS:
            return cached["student"], cached["timetable_days"]

    with TIMETABLE_REFRESH_LOCK:
        with TIMETABLE_CACHE_LOCK:
            cached = TIMETABLE_CACHE.get(cache_key)
            if cached and time.monotonic() - cached["created"] < TIMETABLE_CACHE_SECONDS:
                return cached["student"], cached["timetable_days"]

        student, timetable_days = await build_timetable(client, timetable_dates, days, today)
        with TIMETABLE_CACHE_LOCK:
            TIMETABLE_CACHE[cache_key] = {
                "created": time.monotonic(),
                "student": student,
                "timetable_days": timetable_days
            }
        return student, timetable_days


async def build_timetable(client, timetable_dates, timetable_days, today):
    student = None
    current_time = get_current_stunde_zeit()
    
    for timetable_date in timetable_dates:
        lessons = await client.get_lesson_details(timetable_date.strftime("%Y%m%d"))

        if not student:
            student = lessons.get("elementName")
        for block in lessons["blocks"]:
            lesson = block[0]

            if not isinstance(lesson, dict):
                continue
            if timetable_date.weekday() >= 5:
                continue
            lesson_date = timetable_date.isoformat()

            period = lesson["periods"][0]
            start_time = normalize_time(period.get("startTime", 0))
            end_time = normalize_time(period.get("endTime", 0))
            subject = lesson["subjectNameLong"] if lesson.get("subjectNameLong") and len(lesson["subjectNameLong"]) <= 15 else lesson.get("subjectName")
            student_info = (lesson.get("periodInfo") or {}).get("text") or ""
            full_info = lesson.get("lessonInfo") or ""
            info = (
                full_info
                if len(full_info) < 35
                else full_info[:32] + "..."
            ) if full_info else None
            full_substitute_text = period.get("substText") or ""
            substitute_text = (
                full_substitute_text
                if len(full_substitute_text) < 13
                else full_substitute_text[:10] + "..."
            ) if full_substitute_text else None

            rooms = period.get("rooms")
            teachers = [teacher["name"] for teacher in period.get("teachers")]

            room_changes = []
            for substitution in lesson.get("roomSubstitutions", []):
                org_room = substitution.get("orgRoom")
                cur_room = substitution.get("curRoom")

                if org_room and cur_room and org_room.get("id") != cur_room.get("id"):
                    room_changes.append({
                        "original_room": org_room.get("name") or "",
                        "new_room": cur_room.get("name") or ""
                    })

            if full_substitute_text or room_changes:

                substitution = {
                    "text": substitute_text,
                    "full_text": full_substitute_text,
                    "original_room": ", ".join(change["original_room"] for change in room_changes),
                    "new_room": ", ".join(change["new_room"] for change in room_changes)
                }

            else:
                substitution = None

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
                "teacher": ", ".join(teachers),
                "status": status,
                "info": info or "",
                "full_info": full_info,
                "student_info": student_info,
                "substitution": substitution
            })

    return student, timetable_days


@app.route("/stundenplan")
async def timetable():
    if "untis_session" not in session:
        return redirect(url_for("login"))

    today = get_local_date()
    timetable_dates = get_next_weekdays(today, 5)
    try:
        client = await get_client_from_session()
    except UntisError as e:
        session.clear()
        flash(f"Fehler beim Abrufen der Daten: {e}")
        return redirect(url_for("login"))

    days = {day.isoformat(): [] for day in timetable_dates}

    student, timetable_days = await get_timetable(client, timetable_dates, days, today)

    time_slots = sorted({
        (lesson["start"], lesson["end"])
        for day_lessons in timetable_days.values()
        for lesson in day_lessons
    })
    for day_lessons in timetable_days.values():
        day_lessons.sort(key=lambda lesson: (lesson["start"], lesson["subject"]))

    timetable_days = [
        {
            "date": WEEKDAYS[date.fromisoformat(day).weekday()],
            "is_today": day == today.isoformat(),
            "lessons": day_lessons,
            "rows": [
                {
                    "start": start,
                    "end": end,
                    "lesson": next(
                        (
                            lesson for lesson in day_lessons
                            if lesson["start"] == start and lesson["end"] == end
                        ),
                        None,
                    ),
                }
                for start, end in time_slots
            ],
        }
        for day, day_lessons in sorted(timetable_days.items())
    ]
    return render_template(
        "timetable.html",
        student=student,
        timetable_days=timetable_days,
        time_slots=time_slots,
        timetable_date=f"{WEEKDAYS[today.weekday()]}, " + today.strftime("%d.%m.%Y"),
    )


@app.route("/homework/<int:homework_id>/toggle", methods=["POST"])
async def toggle_homework(homework_id):
    await database.toggle_homework_done(homework_id, session["untis_username"])
    return redirect(url_for("homework"))


@app.route("/homework/<int:homework_id>/delete", methods=["POST"])
async def delete_homework(homework_id):
    await database.delete_homework(homework_id, session["untis_username"])
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


@app.route("/maintenance")
def toggle_maintenance():
    if "untis_session" not in session:
        return redirect(url_for("login"))

    if session["untis_username"] not in ADMINS:
        abort(403)

    app.config["MAINTENANCE_MODE"] = not app.config["MAINTENANCE_MODE"]
    return jsonify({"maintenance": app.config["MAINTENANCE_MODE"]}), 200


@app.route("/api/game-score", methods=["POST"])
async def submit_game_score():
    """Nimmt den aktuellen Punktestand des Freistunden-Jäger-Easter-Eggs entgegen
    und speichert ihn nur, wenn er der neue persönliche Highscore ist."""
    if "untis_session" not in session:
        return jsonify({"error": "not logged in"}), 401

    data = request.get_json(silent=True) or {}
    score = data.get("score")

    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return jsonify({"error": "invalid score"}), 400
    if score < 0 or score != score:  # score != score -> NaN
        return jsonify({"error": "invalid score"}), 400
    await database.submit_game_score(session["untis_username"], score)
    return jsonify({"ok": True})


@app.route("/api/game-leaderboard")
async def game_leaderboard():
    if "untis_session" not in session:
        return jsonify({"error": "not logged in"}), 401

    rows = await database.get_leaderboard(limit=20)
    leaderboard = [
        {"username": row["username"], "score": row["high_score"]}
        for row in rows
    ]
    return jsonify({"leaderboard": leaderboard})


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