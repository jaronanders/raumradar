# Put constants or shared functions here

from zoneinfo import ZoneInfo
import os
from calendar import monthrange
from datetime import datetime, date, time as uhrzeit, timedelta

LOCAL_TIMEZONE = ZoneInfo("Europe/Berlin")
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

def get_current_stunde_zeit():
    """Grobe Hilfsfunktion: aktuelle Uhrzeit als HHMM-Zahl (Untis-Format)."""
    test_time = os.environ.get("TEST_TIME")
    if test_time:
        return normalize_time(test_time)
    now = datetime.now(LOCAL_TIMEZONE)
    return now.hour * 100 + now.minute


def get_local_date():
    return datetime.now(LOCAL_TIMEZONE).date()


def normalize_time(value):
    if isinstance(value, int):
        return value
    digits = "".join(character for character in str(value) if character.isdigit())
    if not digits:
        return 0
    if len(digits) <= 2:
        return int(digits) * 100
    return int(digits[-4:])


def go_to_next_lesson(current_time):
    # Pausen überspringen (ausgenommen Mittagspause)
    for start, end in BREAKS:
        if start <= current_time < end:
            return end
    return current_time


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

def normalize_room_name(value):
    if value is None:
        return ""
    return str(value).strip().upper()


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