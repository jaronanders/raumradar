"""
app.py
======
RaumRadar - lokale Testversion als Flask-Webanwendung.

Starten:
    python app.py

Dann im Browser öffnen:
    http://127.0.0.1:5000
"""

from datetime import datetime, date
import os
import secrets
import time
from zoneinfo import ZoneInfo
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_session import Session

from untis_client import UntisClient, UntisError
import database

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = os.path.join(app.instance_path, "flask_session")
os.makedirs(app.config["SESSION_FILE_DIR"], exist_ok=True)
Session(app)

database.init_db()

ROOM_DATA_CACHE = {}
ROOM_DATA_CACHE_SECONDS = 30
ALLOWED_ROOM_NAMES = {
    "101", "102", "103", "104", "105", "106", "107", "108", "114", "115",
    "120", "121", "125", "126", "127", "128", "129", "130", "131", "136",
    "137", "201", "203", "204", "206", "207", "208", "214", "220", "221",
    "225", "226", "227", "228", "229", "230", "231", "236", "237", "240",
    "A01", "A02", "A03", "A04", "A05", "A06", "A07", "A08", "A09", "A10",
    "A11", "B01", "B02", "B03", "B04", "B05", "E01", "E03", "E27", "E29",
    "E31",
}
LOCAL_TIMEZONE = ZoneInfo("Europe/Berlin")


def get_current_stunde_zeit():
    """Grobe Hilfsfunktion: aktuelle Uhrzeit als HHMM-Zahl (Untis-Format)."""
    now = datetime.now(LOCAL_TIMEZONE)
    return now.hour * 100 + now.minute


def get_local_date():
    return datetime.now(LOCAL_TIMEZONE).date()


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

        client = UntisClient(school, server)
        try:
            client.login(username, password)
        except UntisError as e:
            flash(f"Login fehlgeschlagen: {e}")
            return redirect(url_for("login"))
        except Exception as e:
            flash(f"Verbindungsfehler: {e}")
            return redirect(url_for("login"))

        # Nur die kurzfristige Untis-Session-ID kommt in den Browser-Cookie.
        session["untis_school"] = school
        session["untis_server"] = server
        session["untis_username"] = username
        session["untis_session"] = client.session_id

        flash("Erfolgreich eingeloggt!")
        return redirect(url_for("free_rooms"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    if session.get("untis_session"):
        client = UntisClient(session["untis_school"], session["untis_server"])
        client.session_id = session["untis_session"]
        client.logout()
    session.clear()
    return redirect(url_for("login"))


def get_client_from_session():
    """Baut aus der Browser-Session einen UntisClient ohne Passwort auf."""
    client = UntisClient(session["untis_school"], session["untis_server"])
    client.session_id = session["untis_session"]
    return client


def get_room_data(client):
    cache_key = (
        session["untis_school"],
        session["untis_server"],
        session["untis_username"],
        get_local_date(),
    )
    cached = ROOM_DATA_CACHE.get(cache_key)
    if cached and time.monotonic() - cached["created"] < ROOM_DATA_CACHE_SECONDS:
        return cached["rooms"], cached["lessons"]

    rooms = client.get_rooms()
    lessons = client.get_full_timetable(day=get_local_date())
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

    current_time = get_current_stunde_zeit()

    # Räume herausfinden, die JETZT laut Stundenplan belegt sind
    occupied_room_names = set()
    for lesson in lessons:
        start = lesson.get("startTime", 0)
        end = lesson.get("endTime", 0)
        if start <= current_time <= end:
            for room in lesson.get("ro", []):
                occupied_room_names.add(room.get("name"))

    all_room_names = {r.get("name") for r in rooms} & ALLOWED_ROOM_NAMES
    free_room_names = sorted(all_room_names - occupied_room_names)
    occupied_sorted = sorted(occupied_room_names & ALLOWED_ROOM_NAMES)

    next_lessons = {room_name: None for room_name in all_room_names}
    for lesson in lessons:
        start = lesson.get("startTime", 0)
        if start < current_time:
            continue
        for room in lesson.get("ro", []):
            room_name = room.get("name")
            if room_name not in next_lessons:
                continue
            current_next = next_lessons[room_name]
            if current_next is None or start < current_next["start_time"]:
                next_lessons[room_name] = {
                    "start_time": start,
                    "start": f"{start // 100:02d}:{start % 100:02d}",
                    "end": f"{lesson.get('endTime', 0) // 100:02d}:{lesson.get('endTime', 0) % 100:02d}",
                    "subject": ", ".join(
                        subject.get("name", "")
                        for subject in lesson.get("su", [])
                        if subject.get("name")
                    ) or "Unterricht",
                }

    return render_template(
        "free_rooms.html",
        free_rooms=free_room_names,
        occupied_rooms=occupied_sorted,
        next_lessons=next_lessons,
        total_rooms=len(all_room_names),
        current_time=datetime.now(LOCAL_TIMEZONE).strftime("%H:%M"),
    )


@app.route("/homework", methods=["GET", "POST"])
def homework():
    if "untis_session" not in session:
        return redirect(url_for("login"))

    username = session["untis_username"]

    if request.method == "POST":
        subject = request.form["subject"]
        content = request.form["content"]
        due_date = request.form.get("due_date") or None
        database.add_homework(username, subject, content, due_date)
        flash("Hausaufgabe hinzugefügt!")
        return redirect(url_for("homework"))

    items = database.get_homework(username)
    return render_template("homework.html", items=items)


@app.route("/homework/<int:homework_id>/toggle", methods=["POST"])
def toggle_homework(homework_id):
    database.toggle_homework_done(homework_id, session["untis_username"])
    return redirect(url_for("homework"))


@app.route("/homework/<int:homework_id>/delete", methods=["POST"])
def delete_homework(homework_id):
    database.delete_homework(homework_id, session["untis_username"])
    return redirect(url_for("homework"))


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
