"""
untis_client.py
================
Kapselt die Kommunikation mit der WebUntis JSON-RPC-API.
Wird von app.py genutzt, um sich einzuloggen, Räume/Klassen zu holen
und Stundenpläne abzufragen.
"""

import requests
from datetime import date
from database import update_push_subscription_session, save_untis_password, delete_untis_password, get_untis_password


class UntisError(Exception):
    """Wird geworfen, wenn Untis einen Fehler zurückgibt (z.B. falsches Passwort)."""
    def __init__(self, message):
        super().__init__(message)
        self.message = message

    def __str__(self):
        if "bad credentials" in self.message:
            return "Falsche Anmeldedaten"
        elif "not authenticated" in self.message:
            return "Sitzung abgelaufen"
        else:
            return "Unbekannter Fehler"


class UntisClient:
    def __init__(self, school, server, username=None):
        self.school = school
        self.server = server
        self.base_url = f"https://{server}/WebUntis/jsonrpc.do?school={school}"
        self.session = requests.Session()
        self.username = username
        self.session_id = None
        self.person_id = None
        self.person_type = 5

    async def _rpc(self, method, params, retry=True):
        payload = {"id": "req", "method": method, "params": params, "jsonrpc": "2.0"}
        cookies = {"JSESSIONID": self.session_id} if self.session_id else {}
        resp = self.session.post(self.base_url, json=payload, cookies=cookies, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            message = data["error"].get("message", str(data["error"]))

            # Re-authenticate with password
            if retry and self.session_id and "not authenticated" in message:
                self.session_id = None

                if self.username is None:
                    raise UntisError(message)

                password = await get_untis_password(self.username)

                if not password:
                    raise UntisError(message)

                await self.login(self.username, password)

                return await self._rpc(method, params, retry=False)

            raise UntisError(message)
        return data["result"]

    async def login(self, username, password):
        result = await self._rpc("authenticate", {
            "user": username,
            "password": password,
            "client": "RaumRadar",
        })
        self.username = username
        self.session_id = result["sessionId"]
        self.person_id = result.get("personId")
        self.person_type = result.get("personType", 5)

        await save_untis_password(username, password)

        """When a user's session id expires, their room refresh does not work in the scheduler, therefore polling and their notifications stop working
        This updates the session id after re-authentication"""
        await update_push_subscription_session(username, result["sessionId"])

        return result

    async def logout(self):
        if self.username:
            await delete_untis_password(self.username)
        if self.session_id:
            try:
                await self._rpc("logout", {})
            except UntisError:
                pass
            self.session_id = None

    async def get_rooms(self):
        """Gibt alle Räume der Schule zurück: [{id, name, longName}, ...]"""
        return await self._rpc("getRooms", {})

    async def get_klassen(self):
        """Gibt alle Klassen der Schule zurück: [{id, name}, ...]"""
        result = await self._rpc("getKlassen", {})
        if isinstance(result, dict):
            return result.get("data") or result.get("klassen") or result.get("classes") or []
        return result

    async def get_timetable_for_student(self, student_id, days: list = None):
        """Stundenplan eines einzelnen Schülers für einen oder mehrere Tage (default: heute)."""
        if not days:
            start = end = int(date.today().strftime("%Y%m%d"))
        else:
            start = int(days[0].strftime("%Y%m%d"))
            end = int(days[-1].strftime("%Y%m%d"))
        result = await self._rpc("getTimetable", {
            "id": student_id,
            "type": 5,  # 5 = Schüler
            "startDate": start,
            "endDate": end,
        })
        if isinstance(result, dict):
            return result.get("data") or result.get("timetable") or result.get("lessons") or []
        return result


    async def get_lesson_details(self, date, retry=True):
        """Holt Detaildaten zu den Unterrichtsstunden eines Tages."""

        response = self.session.get(
            f"https://{self.server}/WebUntis/api/public/period/info",
            params={
                "school": self.school,
                "date": date,
                "starttime": 0,
                "endtime": 2359,
                "elemid": self.person_id,
                "elemtype": self.person_type
            },
            cookies={"JSESSIONID": self.session_id} if self.session_id else {},
            timeout=15,
        )
        if response.status_code == 403:
            message = "not authenticated"
        else:
            response.raise_for_status()
            data = response.json()

            if "error" not in data:
                return data.get("data", data)

            message = data["error"].get("message", str(data["error"]))
            
        # Re-authenticate with password
        if retry and self.session_id and "not authenticated" in message:
            self.session_id = None

            if self.username is None:
                raise UntisError(message)

            password = await get_untis_password(self.username)

            if not password:
                raise UntisError(message)

            await self.login(self.username, password)

            return await self.get_lesson_details(date, retry=False)

        raise UntisError(message)


    async def get_timetable_for_klasse(self, klasse_id, day=None):
        """Stundenplan einer einzelnen Klasse für einen Tag (default: heute)."""
        day = day or date.today()
        day_int = int(day.strftime("%Y%m%d"))
        result = await self._rpc("getTimetable", {
            "id": klasse_id,
            "type": 1,  # 1 = Klasse
            "startDate": day_int,
            "endDate": day_int,
        })
        if isinstance(result, dict):
            return result.get("data") or result.get("timetable") or result.get("lessons") or []
        return result

    async def get_full_timetable(self, day=None):
        """
        Holt den Stundenplan ALLER Klassen für einen Tag.
        Gibt eine flache Liste aller Unterrichtsstunden zurück.
        Achtung: das ist ein Aufruf pro Klasse -> kann bei vielen Klassen dauern.
        """
        klassen = await self.get_klassen()
        async def fetch_for_klasse(klasse):
            try:
                lessons = await self.get_timetable_for_klasse(klasse["id"], day)
                for lesson in lessons:
                    lesson["_klasse_name"] = klasse.get("name")
                return lessons
            except (UntisError, KeyError, TypeError):
                # Einzelne Klassen können ohne Berechtigung oder Daten sein.
                return []

        # Die API-Anfragen warten überwiegend auf Netzwerkantworten. Parallel
        # ist die Laufzeit dadurch ungefähr die langsamste Einzelanfrage statt
        # der Summe aller Klassenanfragen.
        lesson_groups = []
        for klasse in klassen:
            lesson_groups.append(await fetch_for_klasse(klasse))

        all_lessons = []
        for lessons in lesson_groups:
            all_lessons.extend(lessons)
        return all_lessons