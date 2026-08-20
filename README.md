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

Im Hosting-Dienst muss die Umgebungsvariable `SECRET_KEY` auf einen langen,
zufälligen Wert gesetzt werden. Nach dem ersten Aufruf kann die Seite auf dem
Handy über das Browser-Menü zum Startbildschirm hinzugefügt werden. Die Adresse
der veröffentlichten Seite kann zusätzlich als QR-Code in der Schule geteilt
werden.

## Was funktioniert schon

- ✅ Login gegen die echte WebUntis-API
- ✅ Freie Räume für die aktuelle Uhrzeit berechnen (heutiger Tag)
- ✅ Hausaufgaben/Notizen anlegen, erledigt markieren, löschen (lokal gespeichert in `raumradar.db`)

## Was noch fehlt (nächste Schritte)

- ❌ Push-Benachrichtigungen bei Stundenausfall (braucht einen dauerhaft laufenden Server, der
  regelmäßig pollt – aktuell holt die App die Daten nur, wenn du die Seite aufrufst)
- ❌ Push-Benachrichtigungen für Hausaufgaben-Fristen
- ❌ Raum-Claim-Feature (Abo)
- ❌ Echte mobile App (das hier ist eine Webanwendung – für iOS/Android bräuchte man
  React Native/Flutter, oder man packt diese Web-App später als PWA)
- ❌ Mehrtägige Ansicht des Stundenplans (aktuell nur "heute")

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
