"""
untis_client.py
================
Kapselt die Kommunikation mit der WebUntis JSON-RPC-API.
Wird von app.py genutzt, um sich einzuloggen, Räume/Klassen zu holen
und Stundenpläne abzufragen.
"""

import requests
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor


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
        self.user_id = None

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
        user_data = self._rpc("getUserData", {})
        self.user_id = user_data.get("personId") or user_data.get("userId")
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
        return self._rpc("getKlassen", {})

    def get_own_timetable(self, day=None):
        """Gibt den persönlichen Stundenplan für eine Woche zurück."""
        day = day or date.today()
        monday = day - timedelta(days=day.weekday())
        friday = monday + timedelta(days=4)
        if self.user_id is None:
            raise UntisError("Die Benutzer-ID wurde von WebUntis nicht geliefert.")
        result = self._rpc("getTimetable", {
            "id": self.user_id,
            "type": 4,
            "startDate": int(monday.strftime("%Y%m%d")),
            "endDate": int(friday.strftime("%Y%m%d")),
        })
        if isinstance(result, dict):
            return result.get("data") or result.get("timetable") or result.get("lessons") or []
        return result

    def get_timetable_for_klasse(self, klasse_id, day=None):
        """Stundenplan einer einzelnen Klasse für einen Tag (default: heute)."""
        day = day or date.today()
        day_int = int(day.strftime("%Y%m%d"))
        return self._rpc("getTimetable", {
            "id": klasse_id,
            "type": 1,  # 1 = Klasse
            "startDate": day_int,
            "endDate": day_int,
        })

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
            except UntisError:
                # Manche Klassen könnten keine Berechtigung erlauben -> überspringen
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
