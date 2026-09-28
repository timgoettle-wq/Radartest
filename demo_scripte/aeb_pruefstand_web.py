"""Kompakte Live-Weboberflaeche fuer den AEB-Rollenpruefstandstest.

Die Anwendung verwendet die Messkomponenten aus ``aeb_pruefstand_test.py``.
Sie liest die Radar-Konfiguration des gewaehlten Fahrzeugs aus der Datenbank,
schreibt aber selbst nichts in die Datenbank.

Start aus dem Projektordner:
    python demo_scripte/aeb_pruefstand_web.py

Danach im Browser oeffnen:
    http://raspberrypi.local:8001

Wichtig: Die Software ist keine Sicherheitseinrichtung und ersetzt weder die
Pruefstandsfreigabe noch einen hardwareseitigen Not-Aus.
"""

import asyncio
import csv
import json
import math
import socket
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from database.database import get_vehicles
from demo_scripte.aeb_pruefstand_test import (
    CAN_CHANNEL,
    DIAGNOSTIC_DIDS,
    DIAGNOSTIC_ENABLED,
    DIAGNOSTIC_SIGNALS,
    RADEST_IP,
    RADEST_PORT,
    SAMPLE_INTERVAL_S,
    SIGNALS,
    DatabaseRadarMonitor,
    PassiveCanMonitor,
    RadestDevice,
    StandaloneUdsMonitor,
    configure_radest_scenario,
    create_diagram,
    expected_dynamic_distance,
    write_sample,
)


HOST = "0.0.0.0"
PORT = 8001
BRAKE_PRESSURE_THRESHOLD_BAR = 2.0
DECELERATION_THRESHOLD_MPS2 = -1.5


class TestConfig(BaseModel):
    vehicle_id: int
    can_channel: str = CAN_CHANNEL
    scenario_type: str = "dynamic"
    distance_m: float = 20.0
    duration_s: float = 15.0
    start_distance_m: float = 40.0
    end_distance_m: float = 5.0
    velocity_kmh: float = 10.0
    pre_hold_s: float = 2.0
    post_hold_s: float = 3.0
    set_attenuation: bool = False
    attenuation_db: float = 0.0


def vehicle_name(vehicle):
    if vehicle.get("name"):
        return str(vehicle["name"])
    parts = []
    for key in ("manufacturer", "brand", "make", "model", "variant", "series"):
        value = vehicle.get(key)
        if value and str(value) not in parts:
            parts.append(str(value))
    return " ".join(parts) if parts else f"Fahrzeug {vehicle['id']}"


def validate_config(config):
    if config.vehicle_id <= 0:
        raise ValueError("Bitte ein Fahrzeug auswaehlen.")
    if not config.can_channel.strip():
        raise ValueError("Der CAN-Kanal darf nicht leer sein.")
    if config.scenario_type not in {"constant", "dynamic"}:
        raise ValueError("Unbekannte Testart.")
    if config.scenario_type == "constant":
        if config.distance_m < 0.1 or config.duration_s < 0.1:
            raise ValueError("Distanz und Messdauer muessen groesser als 0 sein.")
    else:
        if config.start_distance_m < 0.1 or config.end_distance_m < 0.1:
            raise ValueError("Start- und Enddistanz muessen groesser als 0 sein.")
        if math.isclose(config.start_distance_m, config.end_distance_m, abs_tol=1e-9):
            raise ValueError("Start- und Enddistanz muessen sich bei einem dynamischen Test unterscheiden.")
        if config.velocity_kmh <= 0:
            raise ValueError("Die Relativgeschwindigkeit muss groesser als 0 sein.")
        if config.pre_hold_s < 0 or config.post_hold_s < 0:
            raise ValueError("Haltezeiten duerfen nicht negativ sein.")
    if config.set_attenuation:
        steps = config.attenuation_db * 4
        if not 0 <= config.attenuation_db <= 31.75 or not math.isclose(steps, round(steps), abs_tol=1e-8):
            raise ValueError("Die Daempfung muss zwischen 0 und 31,75 dB in 0,25-dB-Schritten liegen.")


def make_scenario(config):
    if config.scenario_type == "constant":
        return {
            "type": "constant",
            "distance_m": config.distance_m,
            "duration_s": config.duration_s,
        }
    return {
        "type": "dynamic",
        "start_distance_m": config.start_distance_m,
        "end_distance_m": config.end_distance_m,
        "velocity_kmh": config.velocity_kmh,
        "pre_hold_s": config.pre_hold_s,
        "post_hold_s": config.post_hold_s,
    }


def measurement_fieldnames():
    signal_columns = []
    for signal_name in SIGNALS:
        signal_columns.extend((signal_name, f"{signal_name}_age_s"))
    radar_columns = [
        "radar_distance",
        "radar_distance_age_s",
        "radar_relative_speed",
        "radar_relative_speed_age_s",
        "radar_diagnostic_status",
        "radar_diagnostic_error",
    ]
    diagnostic_columns = []
    for did in DIAGNOSTIC_DIDS:
        prefix = f"diagnostic_{did:04x}"
        diagnostic_columns.extend(
            (
                f"{prefix}_response_hex",
                f"{prefix}_response_age_s",
                f"{prefix}_status",
                f"{prefix}_error",
            )
        )
    diagnostic_columns.extend(name for name in DIAGNOSTIC_SIGNALS if name not in SIGNALS)
    return [
        "timestamp_unix_ns",
        "elapsed_s",
        "phase",
        "radest_target_distance_m",
        "scenario_velocity_kmh",
        *signal_columns,
        *radar_columns,
        *diagnostic_columns,
    ]


class AebWebRunner:
    def __init__(self):
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.sequence = 0
        self.history = deque(maxlen=3600)
        self.status = "bereit"
        self.message = "Konfiguration ausfuellen und Verbindungen pruefen."
        self.output_directory = None
        self.started_at = None
        self.finished_at = None
        self.brake_onset_s = None
        self.latest = None

    def snapshot(self, include_history=False):
        with self.lock:
            result = {
                "status": self.status,
                "message": self.message,
                "sequence": self.sequence,
                "running": self.thread is not None and self.thread.is_alive(),
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "output_directory": str(self.output_directory) if self.output_directory else None,
                "brake_onset_s": self.brake_onset_s,
                "latest": self.latest,
            }
            if include_history:
                result["history"] = list(self.history)
            return result

    def _set_state(self, status, message):
        with self.lock:
            self.status = status
            self.message = message
            self.sequence += 1

    def check_connections(self, config):
        validate_config(config)
        if self.thread is not None and self.thread.is_alive():
            raise RuntimeError("Waehrend eines laufenden Tests ist keine separate Verbindungspruefung moeglich.")

        result = {"radest": False, "can": False, "vehicle": False, "details": {}}
        try:
            if socket.if_nametoindex(config.can_channel.strip()) == 0:
                raise OSError(f"CAN-Interface {config.can_channel} nicht gefunden")
            result["can"] = True
            result["details"]["can"] = f"{config.can_channel} vorhanden"
        except OSError as error:
            result["details"]["can"] = str(error)

        try:
            radar = DatabaseRadarMonitor(config.vehicle_id)
            result["vehicle"] = True
            result["details"]["vehicle"] = f"Radar-Signale: {', '.join(radar.signal_names)}"
        except Exception as error:
            result["details"]["vehicle"] = str(error)

        radest = RadestDevice(RADEST_IP, RADEST_PORT)
        try:
            if not radest.connect():
                raise ConnectionError("Verbindung fehlgeschlagen")
            result["radest"] = True
            result["details"]["radest"] = f"{RADEST_IP}:{RADEST_PORT} erreichbar"
        except Exception as error:
            result["details"]["radest"] = str(error)
        finally:
            if result["radest"]:
                radest.disconnect()

        result["ok"] = result["radest"] and result["can"] and result["vehicle"]
        self._set_state(
            "bereit" if result["ok"] else "fehler",
            "Alle Verbindungen sind bereit." if result["ok"] else "Mindestens eine Verbindung ist nicht bereit.",
        )
        return result

    def start(self, config):
        validate_config(config)
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                raise RuntimeError("Es laeuft bereits ein Pruefstandstest.")
            self.stop_event.clear()
            self.sequence += 1
            self.history.clear()
            self.latest = None
            self.brake_onset_s = None
            self.finished_at = None
            self.started_at = datetime.now().isoformat(timespec="seconds")
            self.status = "startet"
            self.message = "RadEsT und Diagnose werden verbunden."
            self.thread = threading.Thread(target=self._run, args=(config,), name="AebWebTest", daemon=True)
            self.thread.start()
        return self.snapshot()

    def stop(self):
        with self.lock:
            if self.thread is None or not self.thread.is_alive():
                return self.snapshot()
            self.stop_event.set()
            self.status = "stoppt"
            self.message = "Aufzeichnung wird beendet. Ein laufendes RadEsT-Szenario muss noch auslaufen."
            self.sequence += 1
        return self.snapshot()

    def _publish_row(self, row):
        speeds = [
            row.get(name)
            for name in ("wheel_speed_fl", "wheel_speed_fr", "wheel_speed_rl", "wheel_speed_rr")
            if row.get(name) is not None
        ]
        web_row = dict(row)
        web_row["vehicle_speed_avg"] = sum(speeds) / len(speeds) if speeds else None

        if self.brake_onset_s is None:
            pressure = row.get("main_brake_pressure")
            acceleration = row.get("longitudinal_acceleration")
            if (
                pressure is not None and pressure >= BRAKE_PRESSURE_THRESHOLD_BAR
            ) or (
                acceleration is not None and acceleration <= DECELERATION_THRESHOLD_MPS2
            ):
                self.brake_onset_s = row["elapsed_s"]

        with self.lock:
            self.latest = web_row
            self.history.append(web_row)
            self.sequence += 1

    def _sample_phase(
        self,
        writer,
        file,
        rows,
        monitor,
        diagnostic_monitor,
        radar_monitor,
        origin,
        duration_s,
        phase,
        distance_function,
        velocity_kmh,
    ):
        started = time.perf_counter()
        next_sample = started
        while not self.stop_event.is_set():
            now = time.perf_counter()
            elapsed = now - started
            if elapsed >= duration_s:
                break
            target_distance = distance_function(elapsed)
            write_sample(
                writer,
                rows,
                monitor,
                diagnostic_monitor,
                radar_monitor,
                origin,
                phase,
                target_distance,
                velocity_kmh,
            )
            file.flush()
            self._publish_row(rows[-1])
            next_sample += SAMPLE_INTERVAL_S
            self.stop_event.wait(max(0.0, next_sample - time.perf_counter()))

    def _run(self, config):
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_directory = PROJECT_ROOT / "test_runs" / f"aeb_bench_{timestamp}"
        output_directory.mkdir(parents=True, exist_ok=True)
        measurement_csv = output_directory / "measurement.csv"
        raw_can_csv = output_directory / "can_raw.csv"
        diagnostic_raw_csv = output_directory / "diagnostic_raw.csv"
        diagram_file = output_directory / "measurement.png"
        config_file = output_directory / "test_config.json"

        with self.lock:
            self.output_directory = output_directory

        config_data = config.model_dump() if hasattr(config, "model_dump") else config.dict()
        config_file.write_text(
            json.dumps(config_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        scenario = make_scenario(config)
        radest = RadestDevice(RADEST_IP, RADEST_PORT)
        monitor = None
        diagnostic_monitor = None
        radar_monitor = None
        connected = False
        original_distance = None
        original_attenuation = None
        scenario_thread = None
        scenario_error = []
        rows = []
        origin = time.perf_counter()

        try:
            connected = radest.connect()
            if not connected:
                raise ConnectionError("Verbindung zum RadEsT fehlgeschlagen.")

            try:
                original_distance = radest.target_get_distance()
            except Exception:
                original_distance = None

            if config.set_attenuation:
                original_attenuation = radest.system_get_attenuation()
                radest.system_set_attenuation(config.attenuation_db)

            configure_radest_scenario(radest, scenario)
            radar_monitor = DatabaseRadarMonitor(config.vehicle_id)
            radar_monitor.start()
            monitor = PassiveCanMonitor(config.can_channel.strip(), raw_can_csv, origin)
            monitor.start()
            if DIAGNOSTIC_ENABLED:
                diagnostic_monitor = StandaloneUdsMonitor(
                    config.can_channel.strip(), diagnostic_raw_csv, origin
                )
                diagnostic_monitor.start()

            self._set_state("countdown", "Test startet in 3 Sekunden.")
            for remaining in range(3, 0, -1):
                self._set_state("countdown", f"Test startet in {remaining} Sekunden.")
                if self.stop_event.wait(1.0):
                    break

            if self.stop_event.is_set():
                self._set_state("abgebrochen", "Test wurde vor Messbeginn abgebrochen.")
                return

            origin = time.perf_counter()
            self._set_state("laeuft", "Messung laeuft.")

            with measurement_csv.open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, fieldnames=measurement_fieldnames(), delimiter=";")
                writer.writeheader()

                if scenario["type"] == "constant":
                    self._sample_phase(
                        writer, file, rows, monitor, diagnostic_monitor, radar_monitor, origin,
                        scenario["duration_s"], "constant",
                        lambda _elapsed: scenario["distance_m"], 0.0,
                    )
                else:
                    direction = (
                        "Annaeherung"
                        if scenario["end_distance_m"] < scenario["start_distance_m"]
                        else "Entfernung"
                    )
                    self._set_state(
                        "laeuft",
                        f"Haltezeit vor Bewegung: {scenario['pre_hold_s']:.1f} s.",
                    )
                    self._sample_phase(
                        writer, file, rows, monitor, diagnostic_monitor, radar_monitor, origin,
                        scenario["pre_hold_s"], "pre_hold",
                        lambda _elapsed: scenario["start_distance_m"], 0.0,
                    )

                    if not self.stop_event.is_set():
                        def trigger_scenario():
                            try:
                                radest.scenario_trigger()
                            except Exception as error:
                                scenario_error.append(error)

                        scenario_thread = threading.Thread(
                            target=trigger_scenario, name="RadestScenario", daemon=True
                        )
                        scenario_thread.start()
                        movement_duration = (
                            abs(scenario["end_distance_m"] - scenario["start_distance_m"])
                            / (scenario["velocity_kmh"] / 3.6)
                        )
                        self._set_state("laeuft", f"Dynamische {direction} laeuft.")
                        self._sample_phase(
                            writer, file, rows, monitor, diagnostic_monitor, radar_monitor, origin,
                            movement_duration, "moving",
                            lambda elapsed: expected_dynamic_distance(scenario, elapsed),
                            scenario["velocity_kmh"],
                        )

                    if scenario_thread is not None and not self.stop_event.is_set():
                        while scenario_thread.is_alive() and not self.stop_event.is_set():
                            scenario_thread.join(timeout=0.05)

                    if not self.stop_event.is_set():
                        if scenario_error:
                            raise RuntimeError(f"RadEsT-Szenariofehler: {scenario_error[0]}")
                        self._set_state(
                            "laeuft",
                            f"Haltezeit nach Bewegung: {scenario['post_hold_s']:.1f} s.",
                        )
                        self._sample_phase(
                            writer, file, rows, monitor, diagnostic_monitor, radar_monitor, origin,
                            scenario["post_hold_s"], "post_hold",
                            lambda _elapsed: scenario["end_distance_m"], 0.0,
                        )

            if scenario_thread is not None and scenario_thread.is_alive():
                self._set_state("stoppt", "Aufzeichnung beendet. Das RadEsT-Szenario laeuft noch aus.")
                while scenario_thread.is_alive():
                    scenario_thread.join(timeout=0.25)

            if scenario_error:
                raise RuntimeError(f"RadEsT-Szenariofehler: {scenario_error[0]}")
            if monitor.error is not None:
                raise RuntimeError(f"CAN-Aufzeichnung fehlgeschlagen: {monitor.error}")
            if diagnostic_monitor is not None and diagnostic_monitor.error is not None:
                raise RuntimeError(f"Diagnoseaufzeichnung fehlgeschlagen: {diagnostic_monitor.error}")
            if radar_monitor is not None and radar_monitor.error is not None:
                raise RuntimeError(f"Radar-Diagnose fehlgeschlagen: {radar_monitor.error}")

            create_diagram(rows, diagram_file)
            if self.stop_event.is_set():
                self._set_state("abgebrochen", "Test gestoppt. Vorhandene Messdaten wurden gespeichert.")
            else:
                self._set_state("abgeschlossen", "Test abgeschlossen und Dateien gespeichert.")

        except Exception as error:
            self._set_state("fehler", str(error))
        finally:
            if diagnostic_monitor is not None:
                diagnostic_monitor.stop()
            if monitor is not None:
                monitor.stop()
            if radar_monitor is not None:
                radar_monitor.stop()

            if connected and original_attenuation is not None:
                try:
                    radest.system_set_attenuation(original_attenuation)
                except Exception:
                    pass
            if connected and original_distance is not None:
                try:
                    radest.target_set_distance(original_distance)
                except Exception:
                    pass
            if connected:
                radest.disconnect()

            with self.lock:
                self.finished_at = datetime.now().isoformat(timespec="seconds")
                self.sequence += 1


runner = AebWebRunner()
app = FastAPI(title="AEB-Pruefstand Live")


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(PAGE)


@app.get("/api/config")
def get_config():
    vehicles = [
        {"id": vehicle["id"], "name": vehicle_name(vehicle)}
        for vehicle in get_vehicles()
    ]
    return {
        "vehicles": vehicles,
        "defaults": {
            "can_channel": CAN_CHANNEL,
            "radest": f"{RADEST_IP}:{RADEST_PORT}",
            "sample_interval_s": SAMPLE_INTERVAL_S,
        },
    }


@app.get("/api/status")
def get_status():
    return runner.snapshot(include_history=True)


@app.post("/api/check")
def check_connections(config: TestConfig):
    try:
        return runner.check_connections(config)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/start")
def start_test(config: TestConfig):
    try:
        return runner.start(config)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/stop")
def stop_test():
    return runner.stop()


@app.websocket("/ws")
async def websocket_status(websocket: WebSocket):
    await websocket.accept()
    last_sequence = -1
    try:
        while True:
            snapshot = runner.snapshot(include_history=last_sequence < 0)
            if snapshot["sequence"] != last_sequence:
                await websocket.send_json(snapshot)
                last_sequence = snapshot["sequence"]
            await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        pass


PAGE = r'''<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>AEB-Prüfstand Live</title>
  <style>
    :root{--green:#008143;--dark:#003b32;--pale:#edf6f1;--line:#cfe1d8;--muted:#5b7080;--red:#bc2525;--amber:#b06b00}
    *{box-sizing:border-box} body{margin:0;background:#f4f8f6;color:#002f2a;font:15px Arial,sans-serif}
    main{max-width:1500px;margin:auto;padding:22px}.head{display:flex;justify-content:space-between;gap:20px;align-items:center;margin-bottom:18px}
    h1{margin:0;font-size:30px}.sub{color:var(--muted);margin-top:5px}.safety{font-size:13px;color:#704d00;background:#fff5d8;padding:10px 14px;border-radius:6px}
    .panel{background:#fff;border:1px solid var(--line);border-radius:8px;margin-bottom:16px;overflow:hidden}.panel-title{padding:16px 18px;border-bottom:1px solid var(--line);font-size:19px;font-weight:700}
    .form{display:grid;grid-template-columns:repeat(6,minmax(140px,1fr));gap:12px;padding:16px 18px}.field{background:var(--pale);border-bottom:1px solid var(--line);padding:9px 10px}
    label{display:block;font-size:11px;font-weight:700;letter-spacing:.05em;color:var(--muted);text-transform:uppercase;margin-bottom:5px}
    input,select{width:100%;border:0;background:transparent;color:var(--dark);font:600 15px Arial;outline:none}.span2{grid-column:span 2}.hidden{display:none!important}
    .actions{display:flex;align-items:center;gap:10px;padding:0 18px 18px}.btn{border:0;border-radius:6px;padding:11px 16px;font-weight:700;cursor:pointer}.primary{background:var(--green);color:white}.secondary{background:#e5efe9;color:var(--dark)}.danger{background:#fff0f0;color:var(--red);border:1px solid #efc7c7}.btn:disabled{opacity:.45;cursor:not-allowed}
    .statusbar{display:grid;grid-template-columns:150px 1fr auto;align-items:center;gap:12px;background:var(--dark);color:white;padding:12px 18px}.badge{font-weight:800;text-transform:uppercase;letter-spacing:.04em}.statusmsg{color:#dcebe6}.timer{font-variant-numeric:tabular-nums;font-size:18px;font-weight:700}
    .checks{display:flex;gap:8px;flex-wrap:wrap;padding:12px 18px;border-top:1px solid var(--line)}.check{padding:7px 10px;border-radius:5px;background:#eef2f0;color:var(--muted)}.check.ok{background:#e0f3e8;color:#006638}.check.bad{background:#fde8e8;color:#a31616}
    .values{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;padding:14px}.value{background:var(--pale);border-bottom:1px solid var(--line);padding:12px}.value .name{font-size:11px;color:var(--muted);text-transform:uppercase}.value .number{font-size:23px;font-weight:800;margin-top:4px;font-variant-numeric:tabular-nums}.value.brake.active{background:#fff0dc;border-color:#e29a29}.value.brake.active .number{color:#a04f00}
    .charts{display:grid;grid-template-columns:1fr 1fr;gap:16px}.chart{background:#fff;border:1px solid var(--line);border-radius:8px;padding:14px}.chart h2{font-size:17px;margin:0 0 8px}.chart canvas{width:100%;height:290px;display:block}.legend{display:flex;gap:16px;font-size:12px;color:var(--muted)}.dot{display:inline-block;width:10px;height:3px;margin-right:5px;vertical-align:middle}
    .output{padding:10px 18px;color:var(--muted);font-size:13px;word-break:break-all}.switch{display:flex;align-items:center;gap:8px;padding-top:18px}.switch input{width:auto}
    @media(max-width:1050px){.form{grid-template-columns:repeat(3,1fr)}.values{grid-template-columns:repeat(3,1fr)}.charts{grid-template-columns:1fr}}
    @media(max-width:620px){main{padding:10px}.head{display:block}.safety{margin-top:10px}.form{grid-template-columns:1fr 1fr}.span2{grid-column:span 2}.values{grid-template-columns:1fr 1fr}.statusbar{grid-template-columns:1fr}.actions{flex-wrap:wrap}}
  </style>
</head>
<body><main>
  <div class="head"><div><h1>AEB-Prüfstand Live</h1><div class="sub">RadEsT-Szenario, Fahrzeugdiagnose und CAN-Aufzeichnung</div></div><div class="safety">Software-Stopp ersetzt keinen hardwareseitigen Not-Aus.</div></div>
  <section class="panel">
    <div class="panel-title">Testkonfiguration</div>
    <div class="form">
      <div class="field span2"><label>Fahrzeug</label><select id="vehicle"></select></div>
      <div class="field"><label>CAN-Kanal</label><input id="channel" value="can0"></div>
      <div class="field"><label>Testart</label><select id="type"><option value="dynamic">Dynamisch</option><option value="constant">Statisch</option></select></div>
      <div class="field dynamic"><label>Startdistanz [m]</label><input id="startDistance" type="number" min="0.1" step="0.1" value="40"></div>
      <div class="field dynamic"><label>Enddistanz [m]</label><input id="endDistance" type="number" min="0.1" step="0.1" value="5"></div>
      <div class="field dynamic"><label>Relativgeschwindigkeit [km/h]</label><input id="velocity" type="number" min="0.1" step="0.1" value="10"></div>
      <div class="field dynamic"><label>Haltezeit vorher [s]</label><input id="preHold" type="number" min="0" step="0.1" value="2"></div>
      <div class="field dynamic"><label>Haltezeit nachher [s]</label><input id="postHold" type="number" min="0" step="0.1" value="3"></div>
      <div class="field constant hidden"><label>Zielabstand [m]</label><input id="distance" type="number" min="0.1" step="0.1" value="20"></div>
      <div class="field constant hidden"><label>Messdauer [s]</label><input id="duration" type="number" min="0.1" step="0.1" value="15"></div>
      <div class="switch"><input id="setAtt" type="checkbox"><label for="setAtt" style="margin:0">Dämpfung setzen</label></div>
      <div class="field" id="attField"><label>Dämpfung [dB]</label><input id="attenuation" type="number" min="0" max="31.75" step="0.25" value="0" disabled></div>
    </div>
    <div class="actions"><button class="btn secondary" id="check">Verbindungen prüfen</button><button class="btn primary" id="start">Test starten</button><button class="btn danger" id="stop" disabled>Test stoppen</button></div>
    <div class="checks" id="checks"><span class="check">RadEsT: nicht geprüft</span><span class="check">CAN: nicht geprüft</span><span class="check">Fahrzeug: nicht geprüft</span></div>
  </section>

  <section class="panel">
    <div class="statusbar"><span class="badge" id="status">Bereit</span><span class="statusmsg" id="message">Konfiguration ausfüllen und Verbindungen prüfen.</span><span class="timer" id="timer">00:00.0</span></div>
    <div class="values">
      <div class="value"><div class="name">RadEsT-Distanz</div><div class="number" id="target">–</div></div>
      <div class="value"><div class="name">Fahrzeug-Radardistanz</div><div class="number" id="radar">–</div></div>
      <div class="value"><div class="name">Relative Geschwindigkeit</div><div class="number" id="relative">–</div></div>
      <div class="value"><div class="name">Fahrzeuggeschwindigkeit</div><div class="number" id="speed">–</div></div>
      <div class="value brake" id="brakeCard"><div class="name">Bremsdruck</div><div class="number" id="brake">–</div></div>
      <div class="value"><div class="name">Längsbeschleunigung</div><div class="number" id="accel">–</div></div>
      <div class="value"><div class="name">Lenkwinkel</div><div class="number" id="steering">–</div></div>
      <div class="value"><div class="name">Gierrate</div><div class="number" id="yaw">–</div></div>
    </div>
    <div class="output" id="output">Noch kein Ausgabeordner angelegt.</div>
  </section>

  <div class="charts">
    <section class="chart"><h2>Objekterkennung</h2><div class="legend"><span><i class="dot" style="background:#008143"></i>RadEsT Soll</span><span><i class="dot" style="background:#d58a00"></i>Fahrzeug-Radar</span></div><canvas id="distanceChart"></canvas></section>
    <section class="chart"><h2>Fahrzeugreaktion</h2><div class="legend"><span><i class="dot" style="background:#1976d2"></i>Fahrzeuggeschwindigkeit</span><span><i class="dot" style="background:#d24632"></i>Bremsdruck</span></div><canvas id="reactionChart"></canvas></section>
  </div>
</main>
<script>
const $=id=>document.getElementById(id); let rows=[]; let startedAt=null; let socket=null;
const num=id=>Number($(id).value.replace?.(',','.') ?? $(id).value);
function payload(){return {vehicle_id:Number($('vehicle').value),can_channel:$('channel').value.trim(),scenario_type:$('type').value,distance_m:num('distance'),duration_s:num('duration'),start_distance_m:num('startDistance'),end_distance_m:num('endDistance'),velocity_kmh:num('velocity'),pre_hold_s:num('preHold'),post_hold_s:num('postHold'),set_attenuation:$('setAtt').checked,attenuation_db:num('attenuation')}}
function scenarioFields(){const constant=$('type').value==='constant';document.querySelectorAll('.dynamic').forEach(e=>e.classList.toggle('hidden',constant));document.querySelectorAll('.constant').forEach(e=>e.classList.toggle('hidden',!constant))}
function fmt(value,unit,digits=2){return value===null||value===undefined||!Number.isFinite(Number(value))?'–':`${Number(value).toFixed(digits)} ${unit}`}
function setLive(r){if(!r)return;$('target').textContent=fmt(r.radest_target_distance_m,'m');$('radar').textContent=fmt(r.radar_distance,'m');$('relative').textContent=fmt(r.radar_relative_speed,'km/h');$('speed').textContent=fmt(r.vehicle_speed_avg,'km/h');$('brake').textContent=fmt(r.main_brake_pressure,'bar');$('accel').textContent=fmt(r.longitudinal_acceleration,'m/s²');$('steering').textContent=fmt(r.steering_angle,'°');$('yaw').textContent=fmt(r.yaw_rate,'°/s')}
function setState(s){$('status').textContent=s.status;$('message').textContent=s.message||'';$('output').textContent=s.output_directory?`Ausgabe: ${s.output_directory}`:'Noch kein Ausgabeordner angelegt.';const running=!!s.running;$('start').disabled=running;$('check').disabled=running;$('stop').disabled=!running;document.querySelectorAll('.form input,.form select').forEach(e=>e.disabled=running||e.id==='attenuation'&&!$('setAtt').checked);if(s.started_at&&!startedAt)startedAt=new Date(s.started_at);if(!s.running&&['abgeschlossen','abgebrochen','fehler'].includes(s.status))startedAt=null;if(s.history){rows=s.history.slice()}if(s.latest){if(!rows.length||rows.at(-1).elapsed_s!==s.latest.elapsed_s)rows.push(s.latest);if(rows.length>3600)rows.shift();setLive(s.latest)}$('brakeCard').classList.toggle('active',s.brake_onset_s!==null&&s.brake_onset_s!==undefined);drawAll()}
async function post(url){const res=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:url.endsWith('/stop')?null:JSON.stringify(payload())});const data=await res.json();if(!res.ok)throw new Error(data.detail||'Fehler');return data}
$('type').onchange=scenarioFields;$('setAtt').onchange=()=>{$('attenuation').disabled=!$('setAtt').checked};
$('check').onclick=async()=>{try{const r=await post('/api/check');$('checks').innerHTML=['radest','can','vehicle'].map(k=>`<span class="check ${r[k]?'ok':'bad'}">${k==='radest'?'RadEsT':k==='can'?'CAN':'Fahrzeug'}: ${escapeHtml(r.details[k])}</span>`).join('')}catch(e){alert(e.message)}};
$('start').onclick=async()=>{if(!confirm('Prüfstand freigegeben und hardwareseitiger Not-Aus erreichbar?'))return;try{rows=[];startedAt=null;setState(await post('/api/start'))}catch(e){alert(e.message)}};
$('stop').onclick=async()=>{try{setState(await post('/api/stop'))}catch(e){alert(e.message)}};
function escapeHtml(v){const d=document.createElement('div');d.textContent=v??'';return d.innerHTML}
function connectWs(){const protocol=location.protocol==='https:'?'wss':'ws';socket=new WebSocket(`${protocol}://${location.host}/ws`);socket.onmessage=e=>setState(JSON.parse(e.data));socket.onclose=()=>setTimeout(connectWs,1000)}
function timer(){let seconds=rows.length?Number(rows.at(-1).elapsed_s):0;$('timer').textContent=`${String(Math.floor(seconds/60)).padStart(2,'0')}:${(seconds%60).toFixed(1).padStart(4,'0')}`;requestAnimationFrame(timer)}
function prepare(canvas){const ratio=devicePixelRatio||1;const rect=canvas.getBoundingClientRect();if(canvas.width!==Math.round(rect.width*ratio)||canvas.height!==Math.round(rect.height*ratio)){canvas.width=Math.round(rect.width*ratio);canvas.height=Math.round(rect.height*ratio)}const c=canvas.getContext('2d');c.setTransform(ratio,0,0,ratio,0,0);return {c,w:rect.width,h:rect.height}}
function bounds(values,fallback=[0,1]){const v=values.filter(Number.isFinite);if(!v.length)return fallback;let lo=Math.min(...v),hi=Math.max(...v);if(lo===hi){lo-=1;hi+=1}const pad=(hi-lo)*.1;return [lo-pad,hi+pad]}
function base(canvas,leftLabel,rightLabel){const {c,w,h}=prepare(canvas);c.clearRect(0,0,w,h);const p={l:52,r:rightLabel?52:18,t:14,b:30};c.strokeStyle='#dce8e2';c.fillStyle='#607681';c.font='11px Arial';for(let i=0;i<=4;i++){const y=p.t+(h-p.t-p.b)*i/4;c.beginPath();c.moveTo(p.l,y);c.lineTo(w-p.r,y);c.stroke()}c.fillText('Zeit [s]',w/2-20,h-7);c.save();c.translate(13,h/2);c.rotate(-Math.PI/2);c.fillText(leftLabel,0,0);c.restore();if(rightLabel){c.save();c.translate(w-7,h/2);c.rotate(-Math.PI/2);c.fillText(rightLabel,0,0);c.restore()}return {c,w,h,p}}
function line(ctx,values,color,xmin,xmax,ymin,ymax,right=false){const {c,w,h,p}=ctx;c.strokeStyle=color;c.lineWidth=2;c.beginPath();let open=false;values.forEach((v,i)=>{if(!Number.isFinite(v)){open=false;return}const x=p.l+(w-p.l-p.r)*((rows[i].elapsed_s-xmin)/(xmax-xmin||1));const y=p.t+(h-p.t-p.b)*(1-(v-ymin)/(ymax-ymin||1));if(!open){c.moveTo(x,y);open=true}else c.lineTo(x,y)});c.stroke()}
function labels(ctx,min,max,right=false){const {c,w,h,p}=ctx;c.fillStyle='#607681';c.font='10px Arial';c.textAlign=right?'left':'right';for(let i=0;i<=4;i++){const val=max-(max-min)*i/4;const x=right?w-p.r+5:p.l-5;const y=p.t+(h-p.t-p.b)*i/4+3;c.fillText(val.toFixed(1),x,y)}c.textAlign='left'}
function drawAll(){if(!rows.length){prepare($('distanceChart')).c.clearRect(0,0,$('distanceChart').width,$('distanceChart').height);prepare($('reactionChart')).c.clearRect(0,0,$('reactionChart').width,$('reactionChart').height);return}const xmin=Number(rows[0].elapsed_s),xmax=Number(rows.at(-1).elapsed_s)||1;let a=base($('distanceChart'),'Distanz [m]');const target=rows.map(r=>Number(r.radest_target_distance_m)),radar=rows.map(r=>r.radar_distance==null?NaN:Number(r.radar_distance));const db=bounds([...target,...radar],[0,50]);labels(a,...db);line(a,target,'#008143',xmin,xmax,...db);line(a,radar,'#d58a00',xmin,xmax,...db);let b=base($('reactionChart'),'km/h · bar');const speed=rows.map(r=>r.vehicle_speed_avg==null?NaN:Number(r.vehicle_speed_avg)),brake=rows.map(r=>r.main_brake_pressure==null?NaN:Number(r.main_brake_pressure));const lb=bounds([...speed,...brake],[0,10]);labels(b,...lb);line(b,speed,'#1976d2',xmin,xmax,...lb);line(b,brake,'#d24632',xmin,xmax,...lb)}
async function init(){scenarioFields();try{const r=await fetch('/api/config').then(x=>x.json());$('vehicle').innerHTML=r.vehicles.map(v=>`<option value="${v.id}">${escapeHtml(v.name)} · ID ${v.id}</option>`).join('');$('channel').value=r.defaults.can_channel;setState(await fetch('/api/status').then(x=>x.json()))}catch(e){$('message').textContent=e.message}connectWs();timer();window.addEventListener('resize',drawAll)}init();
</script></body></html>'''


if __name__ == "__main__":
    import uvicorn

    print(f"AEB-Liveoberflaeche: http://raspberrypi.local:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)
