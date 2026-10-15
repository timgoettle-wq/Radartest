# Radartest – Projektzusammenfassung

Prüfstand auf dem Raspberry Pi zur Funktionsprüfung von Fahrzeug-Radarsensoren
im Rahmen der Hauptuntersuchung (HU). Grundlage der Masterarbeit.

Stand: Oktober 2026 (Repository `timgoettle-wq/Radartest`, Branch `main`)

---

## 1. Ziel

Ein Prüfer soll ohne Spezialwissen prüfen können, ob der Radarsensor eines
Fahrzeugs ein simuliertes Ziel korrekt erkennt, und zwar statisch und dynamisch
(fahrendes Ziel).

Dafür erzeugt ein Radar-Zielsimulator ein künstliches Echo. Die vom Fahrzeug
gemeldete Objektliste wird gleichzeitig über die Diagnoseschnittstelle
ausgelesen und mit dem Sollwert verglichen.

## 2. Hardware und Aufbau

| Komponente | Aufgabe | Anbindung |
|---|---|---|
| Raspberry Pi | Steuerrechner, Weboberfläche, Datenablage | – |
| R&S RadEsT | Radar-Echogenerator (Zieldistanz, RCS, Geschwindigkeit) | LAN, SCPI, `192.168.0.10:2101` |
| USB-CAN-Adapter | Fahrzeugdiagnose (UDS über ISO-TP), passives CAN-Logging | SocketCAN |
| Laptop | Bedienung über Browser bzw. SSH | WLAN/LAN zum Pi |

**Fahrzeuge in den Versuchen:**
- Mercedes-Benz E-Klasse (W213)
- Ford Mustang Mach-E
- Ford Kuga

Ein Opel Astra L ist zusätzlich in der Datenbank angelegt.

## 3. Software-Architektur

```
web/app.py (FastAPI, WebSocket)          demo_scripte/*.py (Kommandozeile)
            \                                   /
             └──────── test_controller.py ─────┘
                     /          |           \
       radest/device.py   diagnostics/vehicle.py   test_run.py / measurement_logger.py
        (SCPI RadEsT)       (UDS/ISO-TP, CAN)        (TestRun-Ordner, run.json, CSV)
                                |
                     database/radar_test.db (SQLite)
```

### Kernmodule

| Datei | Inhalt |
|---|---|
| `test_controller.py` | Zentrale Ablaufsteuerung: Verbindungen, TestRun, Quick Check, Precheck (Polarisation, Frequenz, Leistung), statische und dynamische Messung, Messschleife, Logging, RCS-Grenzen, Auswertung von `attSet` und Detektortemperatur |
| `radest/device.py` | SCPI-Kommunikation mit dem RadEsT (wird bewusst nicht verändert) |
| `diagnostics/vehicle.py` | Fahrzeugdiagnose: CAN-Konfiguration, ISO-TP-Sockets, Parameter und Signale lesen (`status`, `distance`, `angle`, `relative_speed`, `relative_acceleration`), Identifikation, Fehlerspeicher |
| `decoder.py` | Dekodierung der Diagnoseantworten |
| `database/database.py` | SQLite-Schema: `vehicles`, `ecus`, `diagnostic_parameters`, `signal_fields`, `dtc_config`, `identification_parameters`, `accepted_identification_values` |
| `test_run.py`, `measurement_logger.py` | Ablage eines Prüflaufs unter `test_runs/<Zeitstempel>_vehicle_<id>/` mit `run.json` und CSV je Messung |

### Weboberfläche (`web/`)

- **`/` – geführter Prüfablauf:**
  - Schritte: Fahrzeug → Quick Check → Precheck → Messung → Ergebnis.
  - Live-Diagramm über WebSocket. Bei einem Verbindungsabbruch verbindet es sich automatisch neu (bis zu 30 Versuche).
  - Zeigt **attSet (Start)** an.
- **`/results` – Ergebnisarchiv:** nur lesend. Zeigt TestRuns, Messdetails, Diagramme und Downloads.
- **`/database` – Datenpflege:** Fahrzeuge, Sensoren, Diagnoseparameter. Vor jedem Schreibvorgang wird eine Sicherung angelegt.
- **`/docs` – Swagger UI.**
- Die Pi-Uhrzeit wird beim Öffnen der Seite aus der Laptopzeit gesetzt.
- Alle Ressourcen liegen lokal. Es gibt keine Internetabhängigkeit und keine Anmeldung, daher nur im lokalen Prüfnetz betreiben.

### Demo-Skripte (`demo_scripte/`)

| Skript | Zweck |
|---|---|
| `controller_demo.py`, `system_demo.py`, `diagnostic_demo.py`, `dtc_demo.py` | Grundfunktionen einzeln testen |
| `static_doppler_test.py`, `dynamic_test_demo.py`, `polarization_test.py` | Einzelversuche statisch/dynamisch/Polarisation |
| `attenuation_threshold_test.py` | Erkennungsgrenze über die Dämpfung |
| `aeb_pruefstand_test.py`, `aeb_pruefstand_web.py` | AEB-Versuche auf dem Rollenprüfstand. ESP-/Bremswerte kommen aus Fahrzeugprofilen (`fahrzeugprofile/`), dazu ein passives CAN-Log |
| `geister_testreihe.py` | Automatische Geister-Testreihe (Blöcke A–E, Kalibrierung, RCS aus Ziel-attSet, Reset nach jedem Geist, Übersichts-CSV, ZIP) |
| `pendel_test.py` | Ziel pendelt zwischen zwei Distanzen (Mercedes: dynamische Erkennung nur bis ca. 38 m) |
| `vergleichsreihe.py` | Identischer Plan für den Fahrzeugvergleich: K1, S50, G, ST, M1, H, K2; `--name`, `--wiederholungen` |
| `temperaturreihe.py` | Aufwärmverlauf: alle 5 min eine statische Leiter bei 15 m, optional eine dynamische Probe. Ende bei stabiler Temperatur oder nach `--max-minuten` (Standard 240, 0 = unbegrenzt). Danach eine Gegenprobe nach dem Sleep. Die Zündung wird überwacht. |

Alle Reihen-Skripte schreiben ihre Ergebnisse auch bei einem Abbruch mit
**Ctrl+C** und packen sie als ZIP.

### Tests

`python -m unittest discover -s tests`. Es gibt Tests für:
- Geister- und Temperaturreihe, Pendeltest, Vergleichsreihe
- WebSocket-Abbruch, RCS-Einstellung, Ergebnis-API
- Datenbank-Editor, Fahrzeugprofile, AEB, Systemzeit

## 4. Zentrale Begriffe

- **RCS (dBsm):** simulierter Radarquerschnitt des Ziels.
- **attSet:** Dämpfungseinstellung des RadEsT. Der Wert wird in der Antwort auf die RCS-Einstellung zurückgemeldet (`setRCS=…, attSet=…, txValue=…, currentEIRP=…`).
  - Raster 0,25.
  - 1 attSet ≈ 4 dB.
  - Kleineres attSet bedeutet stärkere Aussteuerung.
- **Geist:** Das Fahrzeug meldet einen Bruchteil der Solldistanz (½, ¼, ⅛, 1/16), statt der echten Distanz.
- **Modus 0 / Modus 1:**
  - Modus 0 hält das RCS während der dynamischen Fahrt konstant.
  - Modus 1 führt die Dämpfung abstandsabhängig nach.

## 5. Erkenntnisse aus den Messungen

### 5.1 attSet als fahrzeugunabhängige Größe

attSet hängt von RCS, Distanz und Sendeleistung (EIRP) des Fahrzeugs ab:

```
attSet ≈ (57,8 − EIRP − RCS + 40·log10(d / 15 m)) / 4
```

Umgekehrt lässt sich das RCS für ein gewünschtes Ziel-attSet berechnen:

```
RCS = 4·(Ref − attSet_Ziel) + 40·log10(d / 15 m)
```

`Ref` ist das attSet bei 15 m / 0 dBsm. Gemessen wurden:

| Fahrzeug | Ref (attSet bei 15 m / 0 dBsm) |
|---|---|
| Mustang | ≈ 7,25–7,75 |
| Kuga | ≈ 8,25 |

**Folgerung:** Wer Tests über das Ziel-attSet statt über das RCS festlegt,
steuert den RadEsT bei jedem Fahrzeug gleich aus. Das macht Fahrzeuge
vergleichbar.

### 5.2 Geister statisch

- Ob ein Geist auftritt, hängt von **attSet** (Aussteuerung) und Distanz ab.
- Die Schwelle verschiebt sich mit **Sitzung** und **Temperatur**.
- Wiederholbarkeit innerhalb einer Sitzung: ±0,5 attSet (±2 dB).

### 5.3 Geister dynamisch (Modus 0, wegfahrend)

Ein Geist entsteht, sobald

```
4·attSet_Start − 20·log10(d) < C_dyn
```

- **C_dyn** liegt je nach Sitzung zwischen −15 und −25.
- Pro attSet-Stufe wächst der Geisterbeginn innerhalb einer Sitzung um den Faktor 1,35–1,4 (≈ 30 dB/Dekade).
- **Die Startdistanz spielt keine Rolle.** Das ist mehrfach bestätigt: Starts bei 15, 30 und 40 m ergeben denselben Geisterbeginn.
- **Vorhersage aus dem statischen Test:** `C_dyn ≈ 4·(statische Schwelle bei 15 m) − 29`, genau auf ±2 dB.
- Wiederholbarkeit des Geisterbeginns: ±1,5 dB.

### 5.4 Modus 1 und hinfahrendes Ziel

- **Modus 1 erzeugt bei attSet 2–5 keine Geister.** Das gilt für den Kuga und den Mustang (Mustang in 2 Läufen).
- Modus 0 hinfahrend verliert das Objekt unterhalb von ca. 30 m. Modus 1 tut das nicht.
- **Empfehlung für die Prüfung:** dynamische Szenarien in Modus 1 fahren.

### 5.5 Fahrzeugbesonderheiten

- **Kuga:** Ab ca. 40 m kommen abwechselnd Werte von „200“ (kein Objekt). Sie werden in der Auswertung herausgefiltert und nicht als Verlust gezählt.
- **Mustang:** Bei 50 m ist ein ¾-Produkt nahe an der Schwelle zu sehen.
- **Mercedes:** In dynamischen Szenarien werden Objekte nur bis ca. 38 m erkannt. Untersucht wurde das mit dem Pendeltest.

### 5.6 Temperatureinfluss (Temperaturreihe Mustang, 8.10.)

Über 24 Zyklen in 118 min stieg die Detektortemperatur von 18,7 auf 36,8 °C. Der Aufbau blieb unverändert.

| Temperatur | statisch sauber / Geist (attSet) | Geisterbeginn dynamisch (attSet 4) |
|---|---|---|
| 19–20 °C | 5,5 / 5,0 | 17 m |
| 27 °C | 4,5 / 4,0 | 26 m |
| 30 °C | 4,0 / 3,5 | 23 m |
| 32 °C | 3,5 / 3,0 | 27 m |
| 35–37 °C | 3,0 / 2,5 | 36–49 m |

- Die Schwelle fällt um 2,5 attSet (≈ 10 dB), also **≈ 0,55 dB/°C**. Ein wärmerer RadEsT ist günstiger.
- **Ab ca. 75 min (≥ 35 °C) bleibt die Schwelle stabil.** Das ist die empfohlene Aufwärmzeit.
- Der dynamische Geisterbeginn folgt der statischen Schwelle. Beide haben also dieselbe Ursache.
- **Zusätzlicher Sitzungsfaktor:** Bei gleicher Temperatur lag die Schwelle am 6.10. bei 1,25 attSet mit einem Geisterbeginn von 83–99 m. Das sind rund 6 dB mehr als am 8.10. Mögliche Ursachen:
  - Aufbau/Ausrichtung
  - kalte Halle
  - Bauteiltemperatur, die der Fühlertemperatur hinterherläuft
- Die Gegenprobe nach dem Sleep hat am 8.10. keine Daten geliefert. Die Ursache ist noch offen.

## 6. Empfohlener Prüfablauf (Diskussionsstand)

1. RadEsT warmlaufen lassen (Detektor ≥ 35 °C, ca. 75 min). Danach den Aufbau nicht mehr anfassen.
2. **Kurzer statischer Check bei 15 m.** Er liefert:
   - das Referenz-attSet des Fahrzeugs
   - die Geisterschwelle der aktuellen Sitzung, aus der sich C_dyn ableiten lässt
3. Alle Szenarien über das **Ziel-attSet** parametrieren, nicht über ein festes RCS.
4. Dynamische Szenarien in **Modus 1** fahren.

## 7. Betrieb und Arbeitsumgebung

- **Webserver:** als systemd-Dienst `radartest`. Der Start über PowerShell verursachte Ruckler durch den Rückstau der Terminalausgabe.
- **Lange Reihen:** in `tmux` starten. So läuft die Messung weiter, auch wenn der Laptop SSH trennt oder gesperrt wird.
- **SSH:**
  - Anmeldung per Schlüssel.
  - `sudo` ohne Passwort.
  - VS Code Remote-SSH mit abgeschalteten Auto-Updates, damit der Pi auch offline nutzbar bleibt.
- **Entwicklungsablauf:**
  - Änderungen kommen nur über `main` auf den Pi.
  - Merge nur nach Freigabe.
  - Kein direkter Push auf `main`.

## 8. Offene Punkte

- [ ] Ursache der fehlgeschlagenen Gegenprobe der Temperaturreihe klären (Konsolenausgabe).
- [ ] Vorzeichen der Geschwindigkeit: muss `int16` statt `uint16` sein (6552,6 entspricht −1,0 m/s).
- [ ] Mercedes-Geisterversuche und Vergleichsreihe für den Mercedes.
- [ ] Sitzungsfaktor eingrenzen (Ausrichtung, Hallentemperatur, Aufwärmzeit).
- [ ] Vorbekannter fehlschlagender Test: `test_mustang_placeholders_run_without_values`.

## 9. Grafiken für die Arbeit

Erzeugt aus den Mess-ZIPs:
1. bis 4. Fahrzeugvergleich Kuga / Mustang: statische Leitern, Geisterbeginn über attSet, Startdistanz, Modus 1
5. Wiederholbarkeit
6. Geisterschwelle und Geisterbeginn über der Temperatur
7. Aufwärmverlauf über der Zeit
