"""
untis_client.py
================
Kapselt die Kommunikation mit der WebUntis JSON-RPC-API.
Wird von app.py genutzt, um sich einzuloggen, Räume/Klassen zu holen
und Stundenpläne abzufragen.
"""

import requests
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from database import update_push_subscription_session


class UntisError(Exception):
    """Wird geworfen, wenn Untis einen Fehler zurückgibt (z.B. falsches Passwort)."""
    pass


class UntisClient:
    def __init__(self, school, server):
        self.school = school
        self.server = server
        self.base_url = f"https://{server}/WebUntis/jsonrpc.do?school={school}"
        self.session = requests.Session()
        self.session_id = None
        self.person_id = None
        self.person_type = 5

    def _rpc(self, method, params):
        payload = {"id": "req", "method": method, "params": params, "jsonrpc": "2.0"}
        cookies = {"JSESSIONID": self.session_id} if self.session_id else {}
        resp = self.session.post(self.base_url, json=payload, cookies=cookies, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise UntisError(data["error"].get("message", str(data["error"])))
        return data["result"]

    def login(self, username, password):
        result = self._rpc("authenticate", {
            "user": username,
            "password": password,
            "client": "RaumRadar",
        })
        self.session_id = result["sessionId"]
        self.person_id = result.get("personId")
        self.person_type = result.get("personType", 5)

        """When a user's session id expires, their room refresh does not work in the scheduler, therefore polling and their notifications stop working
        This function tries to fix this, but after that session also expires push subscriptions for rooms stop working entirely for that user!"""
        update_push_subscription_session(username, result["sessionId"])

        return result

    def logout(self):
        if self.session_id:
            try:
                self._rpc("logout", {})
            except UntisError:
                pass
            self.session_id = None

    def get_rooms(self):
        """Gibt alle Räume der Schule zurück: [{id, name, longName}, ...]"""
        return self._rpc("getRooms", {})

    def get_klassen(self):
        """Gibt alle Klassen der Schule zurück: [{id, name}, ...]"""
        result = self._rpc("getKlassen", {})
        if isinstance(result, dict):
            return result.get("data") or result.get("klassen") or result.get("classes") or []
        return result

    def get_timetable_for_student(self, student_id, days: list = None):
        """Stundenplan eines einzelnen Schülers für einen Tag (default: heute)."""
        if not days:
            start = end = int(date.today().strftime("%Y%m%d"))
        else:
            start = int(days[0].strftime("%Y%m%d"))
            end = int(days[-1].strftime("%Y%m%d"))
        result = self._rpc("getTimetable", {
            "id": student_id,
            "type": 5,  # 5 = Schüler
            "startDate": start,
            "endDate": end,
        })
        if isinstance(result, dict):
            return result.get("data") or result.get("timetable") or result.get("lessons") or []
        return result


    def get_lesson_details(self, lesson):
        """Holt Detaildaten zu einer Stundenplanperiode."""
        if not isinstance(lesson, dict) or lesson.get("id") is None:
            return {}

        response = self.session.get(
            f"https://{self.server}/WebUntis/api/public/period/info",
            params={
                "school": self.school,
                "date": lesson.get("date"),
                "starttime": lesson.get("startTime"),
                "endtime": lesson.get("endTime"),
                "elemid": self.person_id,
                "elemtype": self.person_type,
                "ttFmtId": 1,
                "selectedPeriodId": lesson["id"],
            },
            cookies={"JSESSIONID": self.session_id} if self.session_id else {},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise UntisError(data["error"].get("message", str(data["error"])))
        return data.get("data", data)


    def get_timetable_for_klasse(self, klasse_id, day=None):
        """Stundenplan einer einzelnen Klasse für einen Tag (default: heute)."""
        day = day or date.today()
        day_int = int(day.strftime("%Y%m%d"))
        result = self._rpc("getTimetable", {
            "id": klasse_id,
            "type": 1,  # 1 = Klasse
            "startDate": day_int,
            "endDate": day_int,
        })
        if isinstance(result, dict):
            return result.get("data") or result.get("timetable") or result.get("lessons") or []
        return result

    def get_full_timetable(self, day=None):
        """
        Holt den Stundenplan ALLER Klassen für einen Tag.
        Gibt eine flache Liste aller Unterrichtsstunden zurück.
        Achtung: das ist ein Aufruf pro Klasse -> kann bei vielen Klassen dauern.
        """
        klassen = self.get_klassen()
        def fetch_for_klasse(klasse):
            try:
                lessons = self.get_timetable_for_klasse(klasse["id"], day)
                for lesson in lessons:
                    lesson["_klasse_name"] = klasse.get("name")
                return lessons
            except (UntisError, KeyError, TypeError):
                # Einzelne Klassen können ohne Berechtigung oder Daten sein.
                return []

        # Die API-Anfragen warten überwiegend auf Netzwerkantworten. Parallel
        # ist die Laufzeit dadurch ungefähr die langsamste Einzelanfrage statt
        # der Summe aller Klassenanfragen.
        with ThreadPoolExecutor(max_workers=8) as executor:
            lesson_groups = executor.map(fetch_for_klasse, klassen)

        all_lessons = []
        for lessons in lesson_groups:
            all_lessons.extend(lessons)
        return all_lessons

