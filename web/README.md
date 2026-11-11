# Weboberfläche

- `/`: geführter Prüfablauf mit Fahrzeug, Quick Check, Precheck, Messung und
  Ergebnis; HTML, CSS und JavaScript sind getrennt.
- `/results`: read-only Ergebnisarchiv mit TestRun-Übersicht,
  Messungsdetails, CSV-Diagramm und Downloads der Rohdateien.
- `/database`: fahrzeugzentrierte Pflege von Fahrzeugen, Radarsensoren,
  HW-/SW-Kennungen, Referenzwerten und Diagnoseparametern.
- `/docs`: Swagger UI.

Alle Ressourcen werden lokal geladen; keine CDN- oder Internetabhängigkeit.
`GET /api/status` liefert den aktuellen Controller-/TestRun-Zustand, damit die
Prüfoberfläche nach einem Browser-Neuladen wieder an der passenden Stelle
einsteigen kann. Ergebniskennwerte im Browser werden aus den während der
aktuellen Messung empfangenen Live-Punkten berechnet. Der vollständige
Distanzverlauf dieser Punkte bleibt auf dem Ergebnis-Screen sichtbar.
Prüfablauf, Ergebnisarchiv und Datenpflege verwenden denselben lokalen App-Header.
Das Ergebnisarchiv liest direkt aus `test_runs/*/run.json` und den dort
referenzierten CSV-Dateien. Es verändert keine Prüfergebnisse.
Die Anwendung ist für das vertrauenswürdige lokale Prüfnetz gedacht und
besitzt keine Benutzeranmeldung. Nicht öffentlich ins Internet stellen.

Vor Änderungen das Testsystem über die Testseite trennen.
Der Editor sperrt Schreibzugriffe bei vorhandenem Controller.
Beim erneuten Verbinden wird die Diagnosekonfiguration neu geladen.
Interne IDs sind unveränderlich. Die Oberfläche ordnet Einträge automatisch
dem geöffneten Fahrzeug, Sensor oder Diagnoseparameter zu.

Hexwerte mit `0x` eingeben; ohne Präfix werden Zahlen dezimal interpretiert.
CAN-IDs sind aktuell auf Standard-11-Bit-IDs beschränkt.
Signalfelder verwenden die fest definierten Namen `status`, `distance`,
`angle`, `relative_speed` und `relative_acceleration`.
`required` kennzeichnet einen Identifikationsparameter, erzwingt aber
noch keinen Abbruch des Prüfablaufs.

Vor jedem Schreibvorgang entsteht eine SQLite-Sicherung unter
`database/backups/`. Sicherungen werden nicht automatisch gelöscht.
Abhängige Einträge müssen vor dem Eltern-Datensatz entfernt werden.
Die bestehende SQLite-Datei wird durch dieses Update nicht ersetzt.

Tests (benötigen FastAPI und httpx):
`python -m unittest discover -s tests`

## Starten und Beenden

`python -m web.app` startet die Prüfoberfläche auf Port 8000. Strg+C wartet
dann höchstens 3 s auf hängende Anfragen und trennt RadEsT und CAN sauber.
Wer weiter `uvicorn web.app:app --host 0.0.0.0` nutzt, sollte
`--timeout-graceful-shutdown 3` anhängen.

## Wenn die Oberfläche hängt

1. Im Terminal des Servers einmal Strg+C. Kommt nach ein paar Sekunden keine
   Eingabezeile, ein zweites Mal Strg+C.
2. `bash pi_diagnose.sh` im Repo-Ordner ausführen. Die Datei unter `logs/`
   zeigt Speicher, Unterspannung, belegte Ports, RadEsT-Erreichbarkeit,
   CAN-Zustand und Kernel-Meldungen.
3. Meldet der Neustart „address already in use“: `ss -ltnp | grep 800` zeigt
   den alten Prozess, `kill <PID>` (notfalls `kill -9 <PID>`) beendet ihn.
4. Antwortet der RadEsT nicht mehr (Verbinden schlägt fehl), RadEsT aus- und
   wieder einschalten.

Ein RadEsT-Befehl wartet höchstens 60 s auf eine Antwort (Szenario-Start
300 s). Spricht gerade ein anderer Teil des Programms mit dem RadEsT, bricht
ein zweiter Befehl nach 10 s mit „RadEsT ist noch … beschäftigt“ ab, statt
die Antwort des ersten zu stehlen.
