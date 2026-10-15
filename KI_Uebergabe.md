# Übergabe an eine andere KI – Projekt „Radartest“

Dieses Dokument fasst ein langes Arbeitsgespräch (Ende September bis Oktober 2026)
zwischen dem Nutzer und einer KI zusammen. Es ist so geschrieben, dass eine neue
KI ohne Vorwissen nahtlos weiterarbeiten kann. Eine kürzere, eher
projektbezogene Zusammenfassung steht in `Projektzusammenfassung.md`.

---

## 1. Wer, was, wozu

- Der Nutzer schreibt eine **Masterarbeit** über die Prüfung von **Fahrzeug-Radarsensoren im Rahmen der Hauptuntersuchung (HU)**.
- Der Prüfstand läuft auf einem **Raspberry Pi**:
  - **R&S RadEsT** (Radar-Echogenerator) über LAN/SCPI: `192.168.0.10:2101`
  - **USB-CAN-Adapter** für Fahrzeugdiagnose: UDS über ISO-TP, SocketCAN
  - **FastAPI-Weboberfläche** für den geführten Prüfablauf
- Repository: `timgoettle-wq/Radartest` (GitHub, Branch `main`).
- **Versuchsfahrzeuge:**
  - Mercedes-Benz E-Klasse W213 (DB-ID 1)
  - Ford Mustang Mach-E (DB-ID 2)
  - Ford Kuga
  - Opel Astra L (DB-ID 3, angelegt)

## 2. Arbeitsregeln des Nutzers (bitte unbedingt einhalten)

- **Immer auf Deutsch antworten.** Kurz, direkt, ohne Floskeln.
- **Nur bauen, wenn ausdrücklich verlangt.** Sätze wie „baue nichts ein“, „ich will nur diskutieren“ oder „baue noch nichts ein“ wörtlich nehmen.
- **Keine unnötige Komplexität, keine Rückfallebenen.** Zitat: „ich brauch kein rückfallebene mach nicht alles komplizierter wie es ist“.
- **`radest/device.py` nicht verändern.** Die Datei kommt so vom Hersteller.
- **Kein direkter Push auf `main`.**
  - Arbeit auf einem Feature-Branch, dann ein PR.
  - **Mergen erst nach dem ausdrücklichen „ja, mergen“** des Nutzers.
- **Der Pi bekommt Änderungen nur über `main`.** Der Nutzer hat einen Befehl, der den Pi mit einem Hotspot verbindet und `git pull` auf `main` ausführt.
- Der Nutzer committet manchmal selbst.
- Ergebnisse kommen als **ZIP der TestRun-Ordner**. Die erwartete Antwort ist eine Auswertung mit Mustern, Zahlen und gegebenenfalls Grafiken in Masterarbeitsqualität.
- Bei Grafiken: matplotlib, ruhige und einheitliche Palette (Blau `#2a78d6`, Orange `#eb6834`), deutsche Beschriftung, keine überlappenden Labels.

## 3. Software-Architektur (Stand `main`)

```
web/app.py (FastAPI, WebSocket)          demo_scripte/*.py (Kommandozeile)
            \                                   /
             └──────── test_controller.py ─────┘
                     /          |           \
       radest/device.py   diagnostics/vehicle.py   test_run.py / measurement_logger.py
        (SCPI RadEsT)       (UDS/ISO-TP, CAN)        (test_runs/<zeit>_vehicle_<id>/run.json + CSV)
                                |
                     database/radar_test.db (SQLite)
```

- **`test_controller.py`:**
  - Verbindungen, TestRun, Quick Check, Precheck (Polarisation, Frequenz, Leistung) bzw. `skip_precheck()`
  - statische und dynamische Messung, Messschleife, Logging
  - RCS-Grenzen, Parsen der RCS-Antwort (`_parse_rcs_setting`), Detektortemperatur (`_read_radest_temperature`)
- **`diagnostics/vehicle.py`:** Signale `status`, `distance`, `angle`, `relative_speed`, `relative_acceleration`, Identifikation, DTCs.
- **`web/`:**
  - `/` geführter Ablauf mit Live-Diagramm per WebSocket und Auto-Reconnect; zeigt „attSet (Start)“ an
  - `/results` Archiv
  - `/database` Datenpflege
  - `/docs`
- **Tests:** `python -m unittest discover -s tests`. Braucht fastapi und httpx. `test_mustang_placeholders_run_without_values` schlug bereits vorher fehl und stammt nicht aus diesem Gespräch.

### Demo-Skripte, die in diesem Gespräch entstanden sind

| Skript | PR | Inhalt |
|---|---|---|
| Logging attSet/txValue | #2 | RCS-Antwort des RadEsT pro Test in `run.json` speichern |
| Detektortemperatur | #3 | `MEASURE:GET:RXDETTEMP?` vor jedem Test |
| `geister_testreihe.py` | #7 | Blöcke A–E, Kalibrierung (Referenz-attSet bei 15 m / 0 dBsm), RCS aus Ziel-attSet, Reset nach jedem Geist, Übersichts-CSV, ZIP. Enthält die wiederverwendbaren Bausteine `run_static`, `run_dynamic`, `summarize_samples`, `rcs_for_attset`, `current_attset`, `Testreihe` |
| `pendel_test.py` | #8 | Ziel pendelt zwischen zwei Distanzen. Jede Teilstrecke ist ein eigenes Szenario, das Fahrzeug wird durchgehend geloggt. Für den Mercedes |
| attSet in der Web-UI | #10 | Messstatus, Ergebnis und Archiv zeigen attSet (Start) |
| `vergleichsreihe.py` | #12 | Identischer Plan für den Fahrzeugvergleich: K1 (15 m, attSet 5→1), S50 (50 m, 6→2), G (Modus 0, 15→100 m, attSet 6/5/4/3), ST (Start 30/40 m, attSet 4), M1 (Modus 1, attSet 5/4/3/2), H (hinfahrend 90→15 m, Modus 0/1), K2. Optionen `--name`, `--wiederholungen` |
| WebSocket-Fix | #13 | Weboberfläche fror nach einem Verbindungsabbruch ein („Cannot call send once a close message has been sent“). Lösung: Server fängt `WebSocketDisconnect` ab, Client verbindet sich neu |
| `temperaturreihe.py` | #14 | Alle 5 min eine Referenz plus statische Leiter bei 15 m (attSet 6→0,5), optional `--dynamisch`. Ende bei ΔT < 0,3 °C über 3 Zyklen oder `--max-minuten` (Standard 240, 0 = unbegrenzt). Gegenprobe: Sleep für `--abkuehl-minuten` (30), dann 2 Zyklen; abschaltbar mit `--ohne-gegenprobe`. Zündung aus wird erkannt: Nutzer wird aufgefordert, die Zündung einzuschalten, und der Test wird wiederholt |

Die PRs #9 und #15–#18 (Pi-Uhrzeit, AEB-Prüfstand) stammen aus anderen Sitzungen.

Alle Reihen-Skripte speichern ihre Daten auch bei **Ctrl+C** und erzeugen ein ZIP. Bei einem Abbruch im Sleep weckt das nächste `connect()` den RadEsT wieder auf (`SYSTEM:SLEEP 0`).

## 4. Hardware- und Protokollwissen

- **RadEsT-SCPI:**
  - `SCEN:DIST:STAR/END`, `SCEN:VEL`, `SCEN:RCS:CONST` (Modus 0 = RCS konstant, also geregelte Dämpfung; Modus 1 = feste Dämpfung), `SCEN:RCS:LIM?`, `SCEN:RCS`, `SCEN:TRIG`, `TARGET:SET:DISTANCE/RCS`, `MEASURE:GET:RXDETTEMP?`, `SYSTem:SLEep`
  - `SCEN:TRIG` blockiert bis zum Szenarioende.
- **Ein laufendes dynamisches Szenario lässt sich über LAN nicht abbrechen.** Während des Szenarios nimmt der RadEsT keine TCP-Verbindung an. Der Nutzer hat beim Hersteller nachgefragt. VXI-11 `device_abort` wurde nicht getestet.
- **Antwort auf die RCS-Einstellung** (undokumentiert), z. B.:
  `setRCS = 41.80, maxRCS = …, minRCS = …, currentEIRP = …, currentTx = 6, txValue = 10.50, attSet = 2.75, uiIdx = 53, …`
  - `uiIdx = 42 + 4·attSet`
  - txValue bleibt pro Sitzung konstant. Der Pegel wird nur über **attSet** gestellt (Raster 0,25, 1 attSet ≈ 4 dB).
- **Datenblatt:** Dämpfung > 60 dB, Distanz 3–250 m, 30 min Aufwärmzeit, Frequency-Monitor-Ausgang (ZF 3,2–8,2 GHz).
- **Antennen:** Der Nutzer stellt manuell 7 bzw. 6 ein, passend für vertikal bzw. horizontal polarisierte Sensoren.
- **Ford-Diagnose** (ECU 0x764/0x76C):
  - `0xA223` Distanz uint16·0,1, effektiv 1 m Auflösung, **200 = kein Objekt**
  - `0xA225` Winkel int8·0,1
  - `0xA224` Relativgeschwindigkeit uint16·0,1. **Das ist ein Fehler, richtig wäre int16**, denn 6552,6 bedeutet −1,0 m/s. Noch nicht behoben.
- **Mercedes-Diagnose** (ECU 0x741/0x721, DID `0x0201`):
  - Distanz float32, **0 = kein Objekt**
  - Die Geschwindigkeit ist tatsächlich in m/s, obwohl in der DB km/h steht.
  - Das Statusbyte wird nicht geloggt.
  - Verhalten wie eine ACC-Zielauswahl: wegfahrend nur im Fenster ca. 15–36 m, Erfassung nach ca. 1 s Bewegung, hinfahrend nie, statisch nur bis ≤ ca. 13 m und nur mit starkem RCS.
  - Dynamisch werden Objekte nur bis ca. 38 m erkannt. Dafür entstand der Pendeltest.
- **Kuga:** Ab ca. 40 m kommen abwechselnd „200“-Werte (kein Objekt). Diese in der Auswertung **filtern**, nicht als Verlust zählen.

## 5. Messerkenntnisse (Kern der Masterarbeit)

### 5.1 Das „Geister“-Phänomen

- Das Fahrzeug meldet **Distanz UND Geschwindigkeit** exakt als ½, ¼, ⅛ oder 1/16 des Sollwerts. Der Winkel bleibt unverändert.
- Die Ursache liegt im RadEsT, denn das Phänomen tritt bei allen Fahrzeugen auf.
- Abhängig ist es von:
  - der Aussteuerung (Pegel bzw. attSet)
  - dem Modus (vor allem Modus 0)
  - der **Ausrichtung/Geometrie**
  - der **Temperatur**
- Arbeitshypothese: Rückreflexion zwischen den parallelen Frontflächen von RadEsT und Fahrzeug erzeugt RadEsT-interne Störprodukte.
- **Ausrichtung:** Am 1.10. gab es bei 0,7° Winkel Geister, bei 1,1–1,45° war alles sauber, bei gleicher Temperatur und EIRP. „Weniger Grad ist nicht unbedingt besser.“
- **Übertrag:** Ein Geisterzustand kann in den nächsten Test hinüberwirken. Deshalb folgt nach jedem Geist ein Reset bei 15 m / 0 dBsm.
- Precheck und EIRP sind als Driftursache ausgeschlossen.

### 5.2 Frühere Faustformeln (Ford, Ende September; inzwischen durch 5.3 abgelöst)

- Echopegel `S0 = RCS − 40·log10(Start)`
- Wegfahrend ½-Geist bei `R½ ≈ 0,58·Start²·10^(−RCS/32)`, ¼-Geist bei `R¼ ≈ 0,27·Start³·10^(−RCS/20)`
- Hinfahrend (Modus 0) Objektverlust bei `≈ 0,0058·Start²·10^(−RCS/29)`
- RCS-Grenzen: `rcs_min ≈ 40·log10(fern) − 76,4`, Fenster ≈ `60 − 40·log10(End/Start)`
- Die Sitzungsdrift betrug 5–11 dB.

### 5.3 Aktuelles Modell über attSet (fahrzeugunabhängig)

- **attSet** hängt ab von RCS, Distanz und Fahrzeug-EIRP:
  `attSet ≈ (57,8 − EIRP − RCS + 40·log10(d/15)) / 4`
- **RCS für ein gewünschtes Ziel-attSet:**
  `RCS = 4·(Ref − attSet_Ziel) + 40·log10(d/15)`
  - Ref = attSet bei 15 m / 0 dBsm: Mustang ≈ 7,25–7,75, Kuga ≈ 8,25.
  - So wird jedes Fahrzeug gleich ausgesteuert.
- **Statische Geisterschwelle:** hängt von attSet und Distanz ab und verschiebt sich mit Sitzung und Temperatur. Wiederholbarkeit ±0,5 attSet (±2 dB).
- **Dynamisch, Modus 0, wegfahrend:** Ein Geist entsteht, sobald `4·attSet_Start − 20·log10(d) < C_dyn`.
  - C_dyn liegt je nach Sitzung zwischen −15 und −25.
  - Pro attSet-Stufe wächst der Geisterbeginn um den Faktor 1,35–1,4.
  - **Die Startdistanz ist egal** (mehrfach bestätigt).
  - Wiederholbarkeit ±1,5 dB.
- **Vorhersage aus dem statischen Test:** `C_dyn ≈ 4·(statische Schwelle bei 15 m) − 29`, genau auf ±2 dB.
- **Modus 1:** keine Geister bei attSet 2–5 (Kuga, Mustang ×2).
- **Modus 0 hinfahrend** verliert das Objekt unterhalb von ca. 30 m. Modus 1 tut das nicht.
- **Mustang:** ¾-Produkt bei 50 m nahe der Schwelle.

### 5.4 Temperaturreihe Mustang (8.10.)

- 24 Zyklen in 118 min, Detektortemperatur 18,7 → 36,8 °C, gleicher Aufbau.

| Temperatur | statisch 15 m sauber / Geist (attSet) | Geisterbeginn Modus 0, attSet 4 |
|---|---|---|
| 19–20 °C | 5,5 / 5,0 | 17 m |
| 27 °C | 4,5 / 4,0 | 26 m |
| 30 °C | 4,0 / 3,5 | 23 m |
| 32 °C | 3,5 / 3,0 | 27 m |
| 35–37 °C | 3,0 / 2,5 | 36–49 m |

- Ergebnis: **≈ 0,55 dB/°C**. Wärmer ist günstiger.
- **Ab ca. 75 min (≥ 35 °C) stabil.** Das ist die empfohlene Aufwärmzeit.
- Dynamisch und statisch verschieben sich gleich.
- **Zusätzlicher Sitzungsfaktor:** Bei gleicher Temperatur lag die Schwelle am 6.10. bei 1,25, der Geisterbeginn bei 83–99 m. Das sind etwa 6 dB Unterschied. Mögliche Ursachen: Ausrichtung, kalte Halle, Bauteiltemperatur ≠ Fühlertemperatur.
- Frühere Mustang-Schwellen bei 15 m:

| Datum | Temperatur | Schwelle (attSet) |
|---|---|---|
| 5.10. früh | 23,5 °C | 3,5 |
| 2.10. vormittags | 33,5 °C | 2,5 |
| 2.10. nachmittags | 38 °C | 1,5 |
| 6.10. | 35,6 / 37,6 °C | 1,25 |

- Die Zündungspause nach 50 min (17 s) wurde korrekt behandelt.
- **Die Gegenprobe nach dem Sleep hat keine Daten geliefert.** Die Ursache ist unklar. Die Konsolenausgabe beim Nutzer ist noch nicht angefragt bzw. ausgewertet.

### 5.5 Empfohlener Prüfablauf (Diskussionsstand, nicht umgesetzt)

1. RadEsT warmlaufen lassen (≥ 35 °C, ca. 75 min). Danach den Aufbau nicht mehr anfassen.
2. Kurzer **statischer Check bei 15 m**. Er liefert das Referenz-attSet und die Sitzungsschwelle, daraus folgt C_dyn.
3. Alle Szenarien über das **Ziel-attSet** parametrieren.
4. Dynamische Szenarien in **Modus 1**.

Der Nutzer will das **fahrzeugunabhängig**. Werte pro Fahrzeug lehnt er ab, weil das „enormer Arbeitsaufwand“ wäre.

Ein früher diskutierter „Aufbau-Check“ ist nicht umgesetzt:
- Justiermodus
- statisch 10 m / 10 dBsm
- Plausibilität (Winkelstreuung < 0,3°)
- RCS-Rampe zur Bestimmung der Geisterschwelle
- Freigabelogik

## 6. Grafiken für die Arbeit

Die Grafiken liegen bisher nur in der KI-Sitzung, nicht im Repo:

1. bis 4. Fahrzeugvergleich Kuga / Mustang: statische Leitern, Geisterbeginn über attSet, Startdistanz egal, Modus 1
5. Wiederholbarkeit
6. Geisterschwelle und Geisterbeginn über der Temperatur
7. Aufwärmverlauf über der Zeit

Für die Auswertung wichtig:
- Kuga-„200“ und Mercedes-„0“ als „kein Objekt“ filtern.
- Geister über das Verhältnis gemeldet/Soll klassifizieren (1, ½, ¼, ⅛, 1/16, sonstige).

## 7. Betrieb und Arbeitsumgebung des Nutzers

- **Zugriff:** Laptop (Windows, PowerShell, VS Code Remote-SSH) per SSH auf den Pi. Anmeldung per Schlüssel, `sudo` ohne Passwort.
- **VS Code ohne Internet am Pi:**
  - `update.mode: none`
  - `extensions.autoUpdate: false`
  - **kein** `remote.SSH.localServerDownload: always`
  - Weboberfläche alternativ per normalem `ssh` mit LocalForward auf `localhost:8000`
- **Webserver als systemd-Dienst `radartest`.** Beim Start im PowerShell-Terminal ruckelte die Live-Anzeige wegen des Rückstaus der Terminalausgabe.
- **Lange Reihen in `tmux` starten.** Dann darf der Laptop SSH trennen oder gesperrt werden (Win+L).
- **Hersteller-Software am Windows-Laptop:** RadEsT-IP `192.168.0.10`, Laptop braucht eine statische IP im selben Netz (192.168.0.x). Der Nutzer hatte sich einmal als „192.169…“ vertippt.

## 8. Offene Punkte

- [ ] Ursache der fehlgeschlagenen Gegenprobe der Temperaturreihe klären (Konsolenausgabe des Nutzers).
- [ ] Vorzeichen der Ford-Geschwindigkeit: `int16` statt `uint16`.
- [ ] Geisterversuche und Vergleichsreihe am Mercedes.
- [ ] Sitzungsfaktor (~6 dB) eingrenzen: Ausrichtung, Hallentemperatur, Aufwärmzeit.
- [ ] Optional, nur auf Wunsch:
  - `--nur-gegenprobe` für die Temperaturreihe
  - `--precheck` für die Vergleichsreihe
  - Mercedes-Statusbyte loggen
  - Aufbau-Check in der Weboberfläche
- [ ] `Projektzusammenfassung.md` und diese Datei liegen auf dem Branch `claude/festive-lovelace-r2uh0s` und sind noch nicht in `main`.
