# RaumRadar – lokale Testversion

Eine erste lauffähige Version zum Testen: Login mit deinem Untis-Account,
Anzeige der gerade freien Räume, und ein einfaches Hausaufgaben-Modul.

## Setup in VS Code

1. Diesen Ordner in VS Code öffnen (`Datei > Ordner öffnen`)
2. Terminal in VS Code öffnen (`Strg+ö` bzw. `Terminal > Neues Terminal`)
3. (Empfohlen) Virtuelle Umgebung anlegen:
   ```
   python -m venv venv
   ```
   Aktivieren:
   - Windows: `venv\Scripts\activate`
   - Mac/Linux: `source venv/bin/activate`
4. Abhängigkeiten installieren:
   ```
   pip install -r requirements.txt
   ```
5. App starten:
   ```
   python app.py
   ```
6. Im Browser öffnen: **http://127.0.0.1:5000**

`app.py` startet den Scheduler automatisch als eigenen Hintergrundprozess.

## Login-Daten

Du brauchst:
- **Schulname** – wie in deiner Untis-Login-URL (z.B. `?school=dein-schulname`)
- **Server** – der Teil der URL vor `/WebUntis/` (z.B. `nessa.webuntis.com`)
- **Benutzername + Passwort** – dein normaler Untis-Login

## Online und auf dem Handy nutzen

Für die Nutzung außerhalb deines Heimnetzwerks muss die App bei einem Hosting-
Dienst veröffentlicht werden, zum Beispiel Render, Railway oder PythonAnywhere.
Der Startbefehl für einen Produktionsserver ist:

```text
gunicorn app:app
```

Für Push-Benachrichtigungen bei geschlossenem Browser muss zusätzlich der
Hintergrund-Scheduler dauerhaft laufen:

```text
python scheduler.py
```

Bei einem direkten Start mit `python app.py` ist dieser separate Befehl nicht
nötig. Der separate Worker ist für Produktionsplattformen gedacht, die Web- und
Hintergrundprozesse getrennt verwalten.

Der Scheduler aktualisiert alle Nutzer mit einem gespeicherten Untis-Login und
prüft ihre favorisierten Räume. Das Intervall ist standardmäßig 120 Sekunden
und kann mit `SCHEDULER_INTERVAL_SECONDS` angepasst werden. Auf Plattformen mit
separaten Worker-Prozessen entspricht der Prozessname `scheduler` dem Eintrag
im `Procfile`. Der Scheduler speichert keine Passwörter und kann nur eine noch
gültige Untis-Session wiederverwenden; nach Ablauf muss sich der Nutzer erneut
einloggen und Push wieder aktivieren.

Im Hosting-Dienst muss die Umgebungsvariable `SECRET_KEY` auf einen langen,
zufälligen Wert gesetzt werden. Nach dem ersten Aufruf kann die Seite auf dem
Handy über das Browser-Menü zum Startbildschirm hinzugefügt werden. Die Adresse
der veröffentlichten Seite kann zusätzlich als QR-Code in der Schule geteilt
werden.

## Was funktioniert schon

- ✅ Login gegen die echte WebUntis-API
- ✅ Freie Räume für die aktuelle Uhrzeit berechnen (heutiger Tag)
- ✅ Hausaufgaben/Notizen anlegen, erledigt markieren, löschen (lokal gespeichert in `raumradar.db`)
- ✅ Browser-Push-Abonnements speichern und Benachrichtigungen über VAPID versenden

## Push-Benachrichtigungen einrichten

Push funktioniert nur über HTTPS (außer auf `localhost`). Erzeuge einmal ein VAPID-Schlüsselpaar
mit einem geeigneten VAPID-Generator und hinterlege die Werte als Umgebungsvariablen:

```text
VAPID_PUBLIC_KEY=...
VAPID_PRIVATE_KEY=...
VAPID_SUBJECT=mailto:deine-adresse@example.com
```

Nach dem Login kann ein Browser über **Benachrichtigungen aktivieren** ein Abonnement anlegen.
Die Daten werden pro Untis-Benutzer in `raumradar.db` gespeichert. Die Anwendung kann später
aus einem Scheduler oder einer Hintergrundaufgabe heraus Benachrichtigungen senden:

```python
from app import send_push_notification

send_push_notification(
  username="dein-untis-benutzername",
  title="Stundenausfall",
  body="Die 3. Stunde in Raum 203 fällt aus.",
  url="/timetable",
)
```

Abgelaufene Browser-Abonnements werden beim Versand automatisch entfernt. Für einen produktiven
Scheduler sollte die Aufgabe in einem separaten Prozess laufen, da der Webserver selbst nicht
dauerhaft pollt.

## Was noch fehlt (nächste Schritte)

- ❌ Push-Benachrichtigungen bei Stundenausfall (braucht einen dauerhaft laufenden Server, der
  regelmäßig pollt – aktuell holt die App die Daten nur, wenn du die Seite aufrufst)
- ❌ Push-Benachrichtigungen für Hausaufgaben-Fristen
- ❌ Raum-Claim-Feature (Abo)
- ❌ Echte mobile App (das hier ist eine Webanwendung – für iOS/Android bräuchte man
  React Native/Flutter, oder man packt diese Web-App später als PWA)
- ❌ Mehrtägige Ansicht des Stundenplans (aktuell nur "heute")

## To Do

- Von Flask auf FastAPI o. ä. wechseln
- Falls Performance nicht ausreicht, auf async Syntax umsteigen (asyncio, aiosqlite, ...)

## Wichtiger Sicherheitshinweis

Für eine echte, veröffentlichte App muss HTTPS aktiviert sein und `SECRET_KEY`
als Umgebungsvariable gesetzt werden. Untis-Passwörter werden von RaumRadar
nicht dauerhaft gespeichert; die kurzfristigen Sitzungsdaten werden serverseitig
verwaltet.

## Falls beim ersten Start Fehler kommen

Am wahrscheinlichsten:
- **Login schlägt fehl** → Schulname/Server falsch geschrieben, oder eure Schule hat
  bestimmte API-Zugriffe eingeschränkt
- **Keine Räume/Klassen gefunden** → euer Account hat evtl. nicht die Berechtigung,
  alle Klassen zu sehen (das hattest du aber schon als "geht bei uns" bestätigt)
- **`ModuleNotFoundError`** → `pip install -r requirements.txt` nochmal ausführen,
  ggf. mit `pip3` statt `pip`

Meld dich einfach mit der genauen Fehlermeldung, dann schauen wir uns das zusammen an.
