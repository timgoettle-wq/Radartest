# Weboberfläche

- `/`: bestehender Prüfablauf; HTML, CSS und JavaScript sind getrennt.
- `/database`: Pflege der sieben Konfigurationstabellen.
- `/docs`: Swagger UI.

Alle Ressourcen werden lokal geladen; keine CDN- oder Internetabhängigkeit.
Die Anwendung ist für das vertrauenswürdige lokale Prüfnetz gedacht und
besitzt keine Benutzeranmeldung. Nicht öffentlich ins Internet stellen.

Vor Änderungen das Testsystem über die Testseite trennen.
Der Editor sperrt Schreibzugriffe bei vorhandenem Controller.
Beim erneuten Verbinden wird die Diagnosekonfiguration neu geladen.
IDs sind unveränderlich. Kopieren kopiert nur den ausgewählten Datensatz,
nicht dessen untergeordnete Konfigurationen.

Hexwerte mit `0x` eingeben; ohne Präfix werden Zahlen dezimal interpretiert.
CAN-IDs sind aktuell auf Standard-11-Bit-IDs beschränkt.
`required` kennzeichnet einen Identifikationsparameter, erzwingt aber
noch keinen Abbruch des Prüfablaufs.

Vor jedem Schreibvorgang entsteht eine SQLite-Sicherung unter
`database/backups/`. Sicherungen werden nicht automatisch gelöscht.
Abhängige Einträge müssen vor dem Eltern-Datensatz entfernt werden.
Die bestehende SQLite-Datei wird durch dieses Update nicht ersetzt.

Tests (benötigen FastAPI und httpx):
`python -m unittest discover -s tests`
