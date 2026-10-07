"""Kompakte Live-Weboberflaeche fuer den AEB-Rollenpruefstandstest.

Die Anwendung verwendet die Messkomponenten aus ``aeb_pruefstand_test.py``.
RadEsT-Verbindung, Precheck und RCS laufen ueber den TestController wie im
gefuehrten Pruefablauf. Ablauf: Verbinden, Precheck, RCS-Grenzen ermitteln,
RCS eingeben, Test starten. Die Verbindung bleibt fuer weitere Tests bestehen.
Die Anwendung schreibt nichts in die Datenbank.

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
import socket
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from database.database import get_vehicles
from demo_scripte.aeb_pruefstand_test import (
    CAN_CHANNEL,
    RADEST_IP,
    RADEST_PORT,
    SAMPLE_INTERVAL_S,
    DatabaseRadarMonitor,
    PRECHECK_LOG,
    RETURN_PREPARE_TIMEOUT_S,
    PassiveCanMonitor,
    RadestScenarioRunner,
    StandaloneUdsMonitor,
    create_diagram,
    dynamic_movement_duration,
    expected_dynamic_distance,
    measurement_fieldnames,
    prepare_radest,
    radest_row_values,
    rcs_limits_text,
    save_precheck,
    start_radest,
    write_sample,
)
from web.system_time import make_system_time_router
from demo_scripte.fahrzeugprofile import (
    can_signals,
    profile_for_vehicle,
    profile_summary,
    uds_active,
    uds_signals,
)
from test_controller import TestController


HOST = "0.0.0.0"
PORT = 8001


class ConnectConfig(BaseModel):
    vehicle_id: int
    can_channel: str = CAN_CHANNEL


class TestConfig(BaseModel):
    scenario_type: str = "dynamic"
    distance_m: float = 20.0
    duration_s: float = 15.0
    start_distance_m: float = 40.0
    end_distance_m: float = 5.0
    velocity_kmh: float = 10.0
    pre_hold_s: float = 2.0
    post_hold_s: float = 3.0
    rcs_constant_state: int = 0
    # Start -> Ende -> Start mit derselben Geschwindigkeit.
    round_trip: bool = False
    rcs_dbsm: Optional[float] = None


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
    if config.scenario_type not in {"constant", "dynamic"}:
        raise ValueError("Unbekannte Testart.")
    if config.scenario_type == "constant":
        if config.distance_m < 0.1 or config.duration_s < 0.1:
            raise ValueError("Distanz und Messdauer muessen groesser als 0 sein.")
    else:
        if config.start_distance_m < 0.1 or config.end_distance_m < 0.1:
            raise ValueError("Start- und Enddistanz muessen groesser als 0 sein.")
        if config.start_distance_m == config.end_distance_m:
            raise ValueError("Start- und Enddistanz muessen unterschiedlich sein.")
        if config.velocity_kmh <= 0:
            raise ValueError("Die Relativgeschwindigkeit muss groesser als 0 sein.")
        if config.pre_hold_s < 0 or config.post_hold_s < 0:
            raise ValueError("Haltezeiten duerfen nicht negativ sein.")
        if config.rcs_constant_state not in (0, 1):
            raise ValueError("RCS-Verhalten muss 0 (konstant) oder 1 (variabel) sein.")


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
        "rcs_constant_state": config.rcs_constant_state,
        "round_trip": config.round_trip,
    }


def scenario_key(scenario):
    # Messdauer und Rueckweg beeinflussen die RadEsT-Vorbereitung nicht.
    return json.dumps(
        {
            key: value
            for key, value in scenario.items()
            if key not in {"duration_s", "actual", "round_trip"}
        },
        sort_keys=True,
    )


class AebWebRunner:
    def __init__(self):
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.busy = None
        self.sequence = 0
        self.history = deque(maxlen=3600)
        self.status = "getrennt"
        self.message = "Fahrzeug waehlen und verbinden."
        self.output_directory = None
        self.started_at = None
        self.finished_at = None
        self.brake_onset_s = None
        self.latest = None
        self.profile = None
        # Jede Messung bekommt eine eigene Nummer, damit die Weboberflaeche
        # Zeilen eines vorherigen Tests nicht in das neue Diagramm uebernimmt.
        self.run_id = 0

        # Sitzung: bleibt ueber mehrere Tests bestehen.
        self.controller = None
        self.vehicle_id = None
        self.can_channel = None
        self.radar_signals = []
        self.precheck = None
        # Alle Prechecks dieser Verbindung; zusaetzlich in PRECHECK_LOG gespeichert.
        self.prechecks = []
        self.rcs_limits = None
        self.prepared_key = None
        self.prepared_scenario = None
        self.last_radest = None

    def snapshot(self, include_history=False):
        with self.lock:
            result = {
                "status": self.status,
                "message": self.message,
                "sequence": self.sequence,
                "run_id": self.run_id,
                "running": self._running(),
                "busy": self.busy,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "output_directory": str(self.output_directory) if self.output_directory else None,
                "brake_onset_s": self.brake_onset_s,
                "latest": self.latest,
                "session": {
                    "connected": self.controller is not None,
                    "vehicle_id": self.vehicle_id,
                    "can_channel": self.can_channel,
                    "profile": profile_summary(self.profile) if self.profile else None,
                    "radar_signals": self.radar_signals,
                    "precheck": self.precheck,
                    "prechecks": list(self.prechecks),
                    "precheck_log": str(PRECHECK_LOG),
                    "rcs_limits": self.rcs_limits,
                    "prepared": self.prepared_key is not None,
                    "prepared_actual": (self.prepared_scenario or {}).get("actual"),
                    "last_radest": self.last_radest,
                },
            }
            if include_history:
                result["history"] = list(self.history)
            return result

    def _running(self):
        return self.thread is not None and self.thread.is_alive()

    def _set_state(self, status, message):
        with self.lock:
            self.status = status
            self.message = message
            self.sequence += 1

    def _exclusive(self, label, action, needs_connection=True):
        with self.lock:
            if self._running():
                raise RuntimeError("Waehrend eines laufenden Tests nicht moeglich.")
            if self.busy is not None:
                raise RuntimeError(f"Bitte warten: {self.busy} laeuft noch.")
            if needs_connection and self.controller is None:
                raise RuntimeError("Bitte zuerst verbinden.")
            self.busy = label
            self.sequence += 1
        try:
            return action()
        finally:
            with self.lock:
                self.busy = None
                self.sequence += 1

    def connect(self, config):
        if config.vehicle_id <= 0:
            raise ValueError("Bitte ein Fahrzeug auswaehlen.")
        can_channel = config.can_channel.strip()
        if not can_channel:
            raise ValueError("Der CAN-Kanal darf nicht leer sein.")

        def action():
            profile = profile_for_vehicle(config.vehicle_id)
            if socket.if_nametoindex(can_channel) == 0:
                raise OSError(f"CAN-Interface {can_channel} nicht gefunden")

            self._disconnect_controller()
            self._set_state("verbindet", "RadEsT und Fahrzeug werden verbunden.")
            controller = TestController(config.vehicle_id, radest_ip=RADEST_IP, radest_port=RADEST_PORT)
            try:
                controller.connect()
                radar_signals = DatabaseRadarMonitor(controller.vehicle).signal_names
            except Exception:
                controller.disconnect()
                raise

            with self.lock:
                self.controller = controller
                self.vehicle_id = config.vehicle_id
                self.can_channel = can_channel
                self.profile = profile
                self.radar_signals = radar_signals
            self._set_state("verbunden", "Verbunden. Precheck durchfuehren oder ueberspringen.")
            return self.snapshot()

        try:
            return self._exclusive("Verbinden", action, needs_connection=False)
        except Exception as error:
            self._set_state("fehler", str(error))
            raise

    def _disconnect_controller(self):
        with self.lock:
            controller = self.controller
            self.controller = None
            self.vehicle_id = None
            self.can_channel = None
            self.radar_signals = []
            self.precheck = None
            self.prechecks = []
            self.rcs_limits = None
            self.prepared_key = None
            self.prepared_scenario = None
            self.last_radest = None
        if controller is not None:
            controller.disconnect()

    def disconnect(self):
        def action():
            self._disconnect_controller()
            self._set_state("getrennt", "Verbindung getrennt.")
            return self.snapshot()

        return self._exclusive("Trennen", action, needs_connection=False)

    def run_precheck(self, skip=False):
        def action():
            with self.lock:
                self.rcs_limits = None
                self.prepared_key = None
                self.prepared_scenario = None
            if skip:
                result = self.controller.skip_precheck()
                message = "Precheck uebersprungen. RCS-Grenzen ermitteln."
            else:
                self._set_state("precheck", "Precheck laeuft.")
                result = self.controller.run_precheck()
                message = "Precheck abgeschlossen. RCS-Grenzen ermitteln."
            with self.lock:
                vehicle_id = self.vehicle_id
            result = save_precheck(vehicle_id, result)
            with self.lock:
                self.precheck = result
                self.prechecks.append(result)
            self._set_state("bereit", message)
            return self.snapshot()

        try:
            return self._exclusive("Precheck", action)
        except Exception as error:
            self._set_state("fehler", str(error))
            raise

    def prepare_rcs(self, config):
        validate_config(config)
        scenario = make_scenario(config)

        def action():
            with self.lock:
                self.prepared_key = None
                self.prepared_scenario = None
            limits = prepare_radest(self.controller, scenario)
            with self.lock:
                self.rcs_limits = limits
                self.prepared_key = scenario_key(scenario)
                self.prepared_scenario = scenario
            self._set_state("bereit", f"RCS-Bereich {rcs_limits_text(limits)}. RCS eingeben und Test starten.")
            return self.snapshot()

        try:
            return self._exclusive("RCS-Grenzen", action)
        except Exception as error:
            self._set_state("fehler", str(error))
            raise

    def start(self, config):
        validate_config(config)
        scenario = make_scenario(config)
        if config.rcs_dbsm is None:
            raise ValueError("Bitte einen RCS-Wert eingeben.")

        def action():
            with self.lock:
                if self.prepared_key is None:
                    raise RuntimeError("Bitte zuerst die RCS-Grenzen ermitteln.")
                if scenario_key(scenario) != self.prepared_key:
                    raise RuntimeError(
                        "Die Testkonfiguration wurde nach dem Ermitteln der RCS-Grenzen geaendert. "
                        "Bitte RCS-Grenzen neu ermitteln."
                    )
                scenario["actual"] = self.prepared_scenario["actual"]
            return start_radest(self.controller, scenario, config.rcs_dbsm)

        radest_result = self._exclusive("RCS setzen", action)

        with self.lock:
            if self._running() or self.busy is not None:
                raise RuntimeError("Es laeuft bereits ein Pruefstandstest.")
            # Nach jedem Test muessen die RCS-Grenzen neu ermittelt werden,
            # weil das Ziel dann am Szenarioende steht.
            self.prepared_key = None
            self.prepared_scenario = None
            self.last_radest = radest_row_values(radest_result)
            self.stop_event.clear()
            self.sequence += 1
            self.run_id += 1
            self.history.clear()
            self.latest = None
            self.brake_onset_s = None
            self.finished_at = None
            self.started_at = datetime.now().isoformat(timespec="seconds")
            self.status = "startet"
            self.message = "RCS gesetzt. Aufzeichnung wird gestartet."
            self.thread = threading.Thread(
                target=self._run,
                args=(config, self.profile, scenario, radest_result),
                name="AebWebTest",
                daemon=True,
            )
            self.thread.start()
        return self.snapshot()

    def stop(self):
        with self.lock:
            if not self._running():
                return self.snapshot()
            self.stop_event.set()
            self.status = "stoppt"
            self.message = "Aufzeichnung wird beendet. Ein laufendes RadEsT-Szenario muss noch auslaufen."
            self.sequence += 1
        return self.snapshot()

    def shutdown(self):
        self.stop()
        if self.thread is not None:
            self.thread.join(timeout=5.0)
        self._disconnect_controller()

    def _publish_row(self, row):
        web_row = dict(row)
        web_row["run_id"] = self.run_id

        if self.brake_onset_s is None:
            thresholds = self.profile["brake_onset"]
            pressure = row.get("brake_pressure")
            acceleration = row.get("longitudinal_acceleration")
            pedal = row.get("brake_pedal_pressed")
            if (
                pressure is not None and pressure >= thresholds["pressure_bar"]
            ) or (
                acceleration is not None and acceleration <= thresholds["deceleration_mps2"]
            ) or (
                pedal is not None and pedal >= 1
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
        radest_values,
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
                self.profile,
                radest_values,
            )
            file.flush()
            self._publish_row(rows[-1])
            next_sample += SAMPLE_INTERVAL_S
            self.stop_event.wait(max(0.0, next_sample - time.perf_counter()))

    def _run(self, config, profile, scenario, radest_result):
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
            controller = self.controller
            can_channel = self.can_channel
            config_data = {
                "vehicle_id": self.vehicle_id,
                "can_channel": can_channel,
                **(config.model_dump() if hasattr(config, "model_dump") else config.dict()),
                "scenario": scenario,
                "precheck": self.precheck,
                "prechecks": list(self.prechecks),
                "radest": radest_result,
                "vehicle_profile": profile,
            }

        config_file.write_text(
            json.dumps(config_data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        radest_values = radest_row_values(radest_result)
        actual = scenario["actual"]
        monitor = None
        diagnostic_monitor = None
        radar_monitor = None
        scenario_thread = None
        timeout_error = None
        rows = []
        origin = time.perf_counter()

        try:
            radar_monitor = DatabaseRadarMonitor(controller.vehicle)
            radar_monitor.start()
            monitor = PassiveCanMonitor(can_channel, raw_can_csv, origin, can_signals(profile))
            monitor.start()
            if uds_active(profile):
                diagnostic_monitor = StandaloneUdsMonitor(
                    can_channel,
                    diagnostic_raw_csv,
                    origin,
                    profile["uds"],
                    uds_signals(profile),
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
                writer = csv.DictWriter(file, fieldnames=measurement_fieldnames(profile), delimiter=";")
                writer.writeheader()

                if scenario["type"] == "constant":
                    self._sample_phase(
                        writer, file, rows, monitor, diagnostic_monitor, radar_monitor, origin,
                        scenario["duration_s"], "constant",
                        lambda _elapsed: actual["distance_m"], 0.0, radest_values,
                    )
                else:
                    self._sample_phase(
                        writer, file, rows, monitor, diagnostic_monitor, radar_monitor, origin,
                        scenario["pre_hold_s"], "pre_hold",
                        lambda _elapsed: actual["pre_hold_distance_m"], actual["velocity_kmh"],
                        radest_values,
                    )

                    def sample(duration_s, phase, distance_function):
                        self._sample_phase(
                            writer, file, rows, monitor, diagnostic_monitor, radar_monitor, origin,
                            duration_s, phase, distance_function, actual["velocity_kmh"], radest_values,
                        )

                    final_distance = actual["end_distance_m"]
                    if not self.stop_event.is_set():
                        scenario_thread = RadestScenarioRunner(controller, scenario, self.stop_event)
                        scenario_thread.start()
                        sample(
                            dynamic_movement_duration(actual), "moving",
                            lambda elapsed: expected_dynamic_distance(actual, elapsed),
                        )

                    if scenario["round_trip"] and not self.stop_event.is_set():
                        # Bis der RadEsT den Hinweg beendet und den Rueckweg
                        # gestartet hat, an der Enddistanz weiter aufzeichnen.
                        waited = time.perf_counter()
                        while not scenario_thread.return_started.is_set() and not self.stop_event.is_set():
                            if time.perf_counter() - waited > RETURN_PREPARE_TIMEOUT_S:
                                # Nicht sofort abbrechen: Das Szenario belegt noch den
                                # RadEsT-Socket. Rueckweg verhindern, unten auf das
                                # Szenarioende warten und dann den Fehler melden.
                                timeout_error = "RadEsT hat den Hinweg nicht rechtzeitig beendet."
                                self.stop_event.set()
                                break
                            sample(0.05, "turn", lambda _elapsed: actual["end_distance_m"])

                        if not self.stop_event.is_set():
                            return_leg = scenario_thread.wait_for_return()
                            actual["return_leg"] = return_leg
                            config_file.write_text(
                                json.dumps(config_data, indent=2, ensure_ascii=False, default=str),
                                encoding="utf-8",
                            )
                            self._set_state("laeuft", "Rueckweg laeuft.")
                            sample(
                                dynamic_movement_duration(return_leg), "moving_back",
                                lambda elapsed: expected_dynamic_distance(return_leg, elapsed),
                            )
                            final_distance = return_leg["end_distance_m"]

                    if not self.stop_event.is_set():
                        sample(scenario["post_hold_s"], "post_hold", lambda _elapsed: final_distance)

            if scenario_thread is not None and scenario_thread.is_alive():
                self._set_state("stoppt", "Aufzeichnung beendet. Das RadEsT-Szenario laeuft noch aus.")
                while scenario_thread.is_alive():
                    scenario_thread.join(timeout=0.25)

            if timeout_error is not None:
                raise RuntimeError(timeout_error)
            if scenario_thread is not None and scenario_thread.error is not None:
                raise RuntimeError(f"RadEsT-Szenariofehler: {scenario_thread.error}")
            if monitor.error is not None:
                raise RuntimeError(f"CAN-Aufzeichnung fehlgeschlagen: {monitor.error}")
            if diagnostic_monitor is not None and diagnostic_monitor.error is not None:
                raise RuntimeError(f"Diagnoseaufzeichnung fehlgeschlagen: {diagnostic_monitor.error}")
            if radar_monitor is not None and radar_monitor.error is not None:
                raise RuntimeError(f"Radar-Diagnose fehlgeschlagen: {radar_monitor.error}")

            create_diagram(rows, diagram_file)
            if self.stop_event.is_set():
                self._set_state(
                    "abgebrochen",
                    "Test gestoppt. Vorhandene Messdaten wurden gespeichert. "
                    "Fuer den naechsten Test RCS-Grenzen neu ermitteln.",
                )
            else:
                self._set_state(
                    "abgeschlossen",
                    "Test abgeschlossen und Dateien gespeichert. "
                    "Fuer den naechsten Test RCS-Grenzen neu ermitteln.",
                )

        except Exception as error:
            self._set_state("fehler", str(error))
        finally:
            if diagnostic_monitor is not None:
                diagnostic_monitor.stop()
            if monitor is not None:
                monitor.stop()
            if radar_monitor is not None:
                radar_monitor.stop()

            with self.lock:
                self.finished_at = datetime.now().isoformat(timespec="seconds")
                self.sequence += 1


runner = AebWebRunner()
app = FastAPI(title="AEB-Pruefstand Live")
app.include_router(make_system_time_router(
    runner.lock,
    lambda: runner.busy is not None or runner._running()
))


@app.on_event("shutdown")
def shutdown():
    runner.shutdown()


def _call(action, *args):
    try:
        return action(*args)
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


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


@app.post("/api/connect")
def connect(config: ConnectConfig):
    return _call(runner.connect, config)


@app.post("/api/disconnect")
def disconnect():
    return _call(runner.disconnect)


@app.post("/api/precheck")
def run_precheck():
    return _call(runner.run_precheck, False)


@app.post("/api/precheck/skip")
def skip_precheck():
    return _call(runner.run_precheck, True)


@app.post("/api/rcs-limits")
def rcs_limits(config: TestConfig):
    return _call(runner.prepare_rcs, config)


@app.post("/api/start")
def start_test(config: TestConfig):
    return _call(runner.start, config)


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
    .chart canvas{cursor:crosshair;touch-action:pan-y}.chart-tip{position:fixed;z-index:1000;min-width:180px;padding:9px 11px;border:1px solid var(--line);border-radius:6px;background:rgba(255,255,255,.97);box-shadow:0 5px 18px rgba(0,59,50,.16);font:12px/1.5 Arial,sans-serif;color:#003b32;pointer-events:none}.chart-tip strong{display:block;margin-bottom:3px}.chart-tip i{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}.chart-cursor{position:fixed;z-index:998;width:1px;background:rgba(0,59,50,.35);pointer-events:none}.chart-dot{position:fixed;z-index:999;width:10px;height:10px;border:2px solid #fff;border-radius:50%;box-shadow:0 1px 5px rgba(0,59,50,.35);transform:translate(-50%,-50%);pointer-events:none}
    .output{padding:10px 18px;color:var(--muted);font-size:13px;word-break:break-all}.switch{display:flex;align-items:center;gap:8px;padding-top:18px}.switch input{width:auto}
    .field .switch{padding-top:0;margin:0;font:600 15px Arial;letter-spacing:0;text-transform:none;color:var(--dark);cursor:pointer}
    @media(max-width:1050px){.form{grid-template-columns:repeat(3,1fr)}.values{grid-template-columns:repeat(3,1fr)}.charts{grid-template-columns:1fr}}
    @media(max-width:620px){main{padding:10px}.head{display:block}.safety{margin-top:10px}.form{grid-template-columns:1fr 1fr}.span2{grid-column:span 2}.values{grid-template-columns:1fr 1fr}.statusbar{grid-template-columns:1fr}.actions{flex-wrap:wrap}}
  </style>
</head>
<body><main>
  <div class="head"><div><h1>AEB-Prüfstand Live</h1><div class="sub">RadEsT-Szenario, Fahrzeugdiagnose und CAN-Aufzeichnung</div></div><div class="safety">Software-Stopp ersetzt keinen hardwareseitigen Not-Aus.</div></div>
  <section class="panel">
    <div class="panel-title">1 · Verbindung und Precheck</div>
    <div class="form">
      <div class="field span2"><label>Fahrzeug</label><select id="vehicle"></select></div>
      <div class="field"><label>CAN-Kanal</label><input id="channel" value="can0"></div>
    </div>
    <div class="actions"><button class="btn primary" id="connect">Verbinden</button><button class="btn secondary" id="disconnect" disabled>Trennen</button><button class="btn secondary" id="precheck" disabled>Precheck durchführen</button><button class="btn secondary" id="skipPrecheck" disabled>Precheck überspringen</button></div>
    <div class="checks" id="checks"><span class="check">Verbindung: getrennt</span><span class="check">Precheck: offen</span></div>
    <div class="checks" id="precheckList"></div>
  </section>

  <section class="panel">
    <div class="panel-title">2 · Testkonfiguration und RCS</div>
    <div class="form">
      <div class="field"><label>Testart</label><select id="type" class="scenario"><option value="dynamic">Dynamisch</option><option value="constant">Statisch</option></select></div>
      <div class="field dynamic"><label>Startdistanz [m]</label><input class="scenario" id="startDistance" type="number" min="0.1" step="0.1" value="40"></div>
      <div class="field dynamic"><label>Enddistanz [m]</label><input class="scenario" id="endDistance" type="number" min="0.1" step="0.1" value="5"></div>
      <div class="field dynamic"><label>Relativgeschwindigkeit [km/h]</label><input class="scenario" id="velocity" type="number" min="0.1" step="0.1" value="10"></div>
      <div class="field dynamic"><label>Haltezeit vorher [s]</label><input class="scenario" id="preHold" type="number" min="0" step="0.1" value="2"></div>
      <div class="field dynamic"><label>Haltezeit nachher [s]</label><input class="scenario" id="postHold" type="number" min="0" step="0.1" value="3"></div>
      <div class="field dynamic"><label>Ablauf</label><label class="switch" title="Start → Ende → Start mit derselben Geschwindigkeit, an der Enddistanz ohne Haltezeit."><input class="scenario" id="roundTrip" type="checkbox">Hin und zurück</label></div>
      <div class="field dynamic span2"><label>RCS-Verhalten im Szenario</label><select class="scenario" id="rcsMode"><option value="0" selected>Konstante RCS</option><option value="1">Variable RCS / konstante Ausgangsleistung</option></select></div>
      <div class="field constant hidden"><label>Zielabstand [m]</label><input class="scenario" id="distance" type="number" min="0.1" step="0.1" value="20"></div>
      <div class="field constant hidden"><label>Messdauer [s]</label><input id="duration" type="number" min="0.1" step="0.1" value="15"></div>
      <div class="field"><label>RCS-Bereich</label><div id="rcsRange" style="font-weight:600;padding-top:2px">–</div></div>
      <div class="field"><label>RCS [dBsm]</label><input id="rcs" type="number" step="0.1" disabled></div>
    </div>
    <div class="actions"><button class="btn secondary" id="rcsLimits" disabled>RCS-Grenzen ermitteln</button><button class="btn primary" id="start" disabled>Test starten</button><button class="btn danger" id="stop" disabled>Test stoppen</button></div>
    <div class="checks" id="radestInfo"><span class="check">RadEsT-Arbeitspunkt: noch kein Test</span></div>
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
const $=id=>document.getElementById(id); let rows=[]; let startedAt=null; let socket=null; let runId=null;
const num=id=>Number($(id).value.replace?.(',','.') ?? $(id).value);
function payload(){return {scenario_type:$('type').value,distance_m:num('distance'),duration_s:num('duration'),start_distance_m:num('startDistance'),end_distance_m:num('endDistance'),velocity_kmh:num('velocity'),pre_hold_s:num('preHold'),post_hold_s:num('postHold'),rcs_constant_state:Number($('rcsMode').value),round_trip:$('roundTrip').checked,rcs_dbsm:$('rcs').value===''?null:num('rcs')}}
function scenarioFields(){const constant=$('type').value==='constant';document.querySelectorAll('.dynamic').forEach(e=>e.classList.toggle('hidden',constant));document.querySelectorAll('.constant').forEach(e=>e.classList.toggle('hidden',!constant))}
function fmt(value,unit,digits=2){return value===null||value===undefined||!Number.isFinite(Number(value))?'–':`${Number(value).toFixed(digits)} ${unit}`}
function setLive(r){if(!r)return;$('target').textContent=fmt(r.radest_target_distance_m,'m');$('radar').textContent=fmt(r.radar_distance,'m');$('relative').textContent=fmt(r.radar_relative_speed,'km/h');$('speed').textContent=fmt(r.vehicle_speed,'km/h');$('brake').textContent=r.brake_pressure==null&&r.brake_pedal_pressed!=null?(Number(r.brake_pedal_pressed)>=1?'betätigt':'frei'):fmt(r.brake_pressure,'bar');$('accel').textContent=fmt(r.longitudinal_acceleration,'m/s²');$('steering').textContent=fmt(r.steering_angle,'°');$('yaw').textContent=fmt(r.yaw_rate,'°/s')}
function chip(ok,text){return `<span class="check ${ok===true?'ok':ok===false?'bad':''}">${escapeHtml(text)}</span>`}
function setSession(s){const x=s.session||{};const busy=!!s.busy,running=!!s.running,idle=!busy&&!running;
  if(x.connected){$('vehicle').value=String(x.vehicle_id);$('channel').value=x.can_channel}
  const pre=x.precheck;const preText=!pre?'Precheck: offen':pre.skipped?'Precheck: übersprungen':`Precheck: ${pre.polarization??''} · ${pre.frequency_range??''} · ${pre.power??''}`;
  $('checks').innerHTML=chip(x.connected?true:null,x.connected?`Verbunden: Fahrzeug ${x.vehicle_id} auf ${x.can_channel} · Radar ${x.radar_signals.join(', ')}`:'Verbindung: getrennt')+(x.profile?chip(true,x.profile):'')+chip(pre?true:null,preText);
  const all=x.prechecks||[];$('precheckList').innerHTML=all.length?all.map((p,i)=>chip(null,`Precheck ${i+1} · ${(p.time||'').slice(11)} · `+(p.skipped?'übersprungen':`${p.polarization??''} · ${p.frequency_range??''} · ${p.power??''}`))).join('')+`<span class="check" title="${escapeHtml(x.precheck_log||'')}">${all.length} gespeichert in test_runs/aeb_prechecks.csv</span>`:'';
  const limits=x.rcs_limits;$('rcsRange').textContent=limits?`${limits.rcs_min_dbsm.toFixed(2)} … ${limits.rcs_max_dbsm.toFixed(2)} dBsm`:'–';
  if(limits){$('rcs').min=limits.rcs_min_dbsm;$('rcs').max=limits.rcs_max_dbsm;if($('rcs').value==='')$('rcs').value=Math.min(Math.max(10,limits.rcs_min_dbsm),limits.rcs_max_dbsm).toFixed(1)}
  const r=x.last_radest;$('radestInfo').innerHTML=r?chip(true,`Letzter Test: RCS ${r.radest_rcs_dbsm} dBsm · txValue ${r.radest_tx_value??'–'} · attSet ${r.radest_att_set??'–'} · Temperatur ${r.radest_temperature_c??'–'} °C`):chip(null,'RadEsT-Arbeitspunkt: noch kein Test');
  $('vehicle').disabled=$('channel').disabled=x.connected||!idle;$('connect').disabled=x.connected||!idle;$('disconnect').disabled=!x.connected||!idle;$('precheck').disabled=$('skipPrecheck').disabled=!x.connected||!idle;
  $('rcsLimits').disabled=!x.connected||!pre||!idle;$('rcs').disabled=!x.prepared||!idle;$('start').disabled=!x.prepared||!idle;$('stop').disabled=!running;
  document.querySelectorAll('.scenario,#duration').forEach(e=>e.disabled=!idle)}
function setState(s){$('status').textContent=s.busy?`${s.busy} …`:s.status;$('message').textContent=s.message||'';$('output').textContent=s.output_directory?`Ausgabe: ${s.output_directory}`:'Noch kein Ausgabeordner angelegt.';setSession(s);if(s.started_at&&!startedAt)startedAt=new Date(s.started_at);if(!s.running&&['abgeschlossen','abgebrochen','fehler'].includes(s.status))startedAt=null;if(s.run_id!==undefined&&s.run_id!==runId){runId=s.run_id;rows=[]}if(s.history){rows=s.history.filter(r=>r.run_id===runId)}if(s.latest&&s.latest.run_id===runId){if(!rows.length||rows.at(-1).elapsed_s!==s.latest.elapsed_s)rows.push(s.latest);if(rows.length>3600)rows.shift();setLive(s.latest)}$('brakeCard').classList.toggle('active',s.brake_onset_s!==null&&s.brake_onset_s!==undefined);drawAll()}
async function post(url,body){const res=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:body===undefined?null:JSON.stringify(body)});const data=await res.json();if(!res.ok)throw new Error(data.detail||'Fehler');return data}
async function act(fn){try{setState(await fn())}catch(e){alert(e.message)}}
$('type').onchange=scenarioFields;
$('connect').onclick=()=>act(()=>post('/api/connect',{vehicle_id:Number($('vehicle').value),can_channel:$('channel').value.trim()}));
$('disconnect').onclick=()=>act(()=>post('/api/disconnect'));
$('precheck').onclick=()=>act(()=>post('/api/precheck'));
$('skipPrecheck').onclick=()=>act(()=>post('/api/precheck/skip'));
$('rcsLimits').onclick=()=>act(()=>post('/api/rcs-limits',payload()));
$('start').onclick=()=>{if(!confirm('Prüfstand freigegeben und hardwareseitiger Not-Aus erreichbar?'))return;startedAt=null;act(()=>post('/api/start',payload()))};
$('stop').onclick=()=>act(()=>post('/api/stop'));
function escapeHtml(v){const d=document.createElement('div');d.textContent=v??'';return d.innerHTML}
function connectWs(){const protocol=location.protocol==='https:'?'wss':'ws';socket=new WebSocket(`${protocol}://${location.host}/ws`);socket.onmessage=e=>setState(JSON.parse(e.data));socket.onclose=()=>setTimeout(connectWs,1000)}
function timer(){let seconds=rows.length?Number(rows.at(-1).elapsed_s):0;$('timer').textContent=`${String(Math.floor(seconds/60)).padStart(2,'0')}:${(seconds%60).toFixed(1).padStart(4,'0')}`;requestAnimationFrame(timer)}
function prepare(canvas){const ratio=devicePixelRatio||1;const rect=canvas.getBoundingClientRect();if(canvas.width!==Math.round(rect.width*ratio)||canvas.height!==Math.round(rect.height*ratio)){canvas.width=Math.round(rect.width*ratio);canvas.height=Math.round(rect.height*ratio)}const c=canvas.getContext('2d');c.setTransform(ratio,0,0,ratio,0,0);return {c,w:rect.width,h:rect.height}}
function bounds(values,fallback=[0,1]){const v=values.filter(Number.isFinite);if(!v.length)return fallback;let lo=Math.min(...v),hi=Math.max(...v);if(lo===hi){lo-=1;hi+=1}const pad=(hi-lo)*.1;return [lo-pad,hi+pad]}
function base(canvas,leftLabel,rightLabel){const {c,w,h}=prepare(canvas);c.clearRect(0,0,w,h);const p={l:52,r:rightLabel?52:18,t:14,b:30};c.strokeStyle='#dce8e2';c.fillStyle='#607681';c.font='11px Arial';for(let i=0;i<=4;i++){const y=p.t+(h-p.t-p.b)*i/4;c.beginPath();c.moveTo(p.l,y);c.lineTo(w-p.r,y);c.stroke()}c.fillText('Zeit [s]',w/2-20,h-7);c.save();c.translate(13,h/2);c.rotate(-Math.PI/2);c.fillText(leftLabel,0,0);c.restore();if(rightLabel){c.save();c.translate(w-7,h/2);c.rotate(-Math.PI/2);c.fillText(rightLabel,0,0);c.restore()}return {c,w,h,p}}
function line(ctx,values,color,xmin,xmax,ymin,ymax,right=false){const {c,w,h,p}=ctx;c.strokeStyle=color;c.lineWidth=2;c.beginPath();let open=false;values.forEach((v,i)=>{if(!Number.isFinite(v)){open=false;return}const x=p.l+(w-p.l-p.r)*((rows[i].elapsed_s-xmin)/(xmax-xmin||1));const y=p.t+(h-p.t-p.b)*(1-(v-ymin)/(ymax-ymin||1));if(!open){c.moveTo(x,y);open=true}else c.lineTo(x,y)});c.stroke()}
function labels(ctx,min,max,right=false){const {c,w,h,p}=ctx;c.fillStyle='#607681';c.font='10px Arial';c.textAlign=right?'left':'right';for(let i=0;i<=4;i++){const val=max-(max-min)*i/4;const x=right?w-p.r+5:p.l-5;const y=p.t+(h-p.t-p.b)*i/4+3;c.fillText(val.toFixed(1),x,y)}c.textAlign='left'}
function drawAll(){for(const id of ['distanceChart','reactionChart'])$(id).__hover=null;if(!rows.length){prepare($('distanceChart')).c.clearRect(0,0,$('distanceChart').width,$('distanceChart').height);prepare($('reactionChart')).c.clearRect(0,0,$('reactionChart').width,$('reactionChart').height);refreshHover();return}const xmin=Number(rows[0].elapsed_s),xmax=Number(rows.at(-1).elapsed_s)||1;let a=base($('distanceChart'),'Distanz [m]');const target=rows.map(r=>Number(r.radest_target_distance_m)),radar=rows.map(r=>r.radar_distance==null?NaN:Number(r.radar_distance));const db=bounds([...target,...radar],[0,50]);labels(a,...db);line(a,target,'#008143',xmin,xmax,...db);line(a,radar,'#d58a00',xmin,xmax,...db);
  $('distanceChart').__hover={...a,xmin,xmax,ymin:db[0],ymax:db[1],series:[{label:'RadEsT Soll',color:'#008143',unit:'m',values:target},{label:'Fahrzeug-Radar',color:'#d58a00',unit:'m',values:radar}],extra:i=>[['Abweichung',Number.isFinite(radar[i])&&Number.isFinite(target[i])?fmt(radar[i]-target[i],'m'):'–'],['Relativgeschw.',fmt(rows[i].radar_relative_speed,'km/h')]]};
  let b=base($('reactionChart'),'km/h · bar');const speed=rows.map(r=>r.vehicle_speed==null?NaN:Number(r.vehicle_speed)),brake=rows.map(r=>r.brake_pressure==null?NaN:Number(r.brake_pressure));const lb=bounds([...speed,...brake],[0,10]);labels(b,...lb);line(b,speed,'#1976d2',xmin,xmax,...lb);line(b,brake,'#d24632',xmin,xmax,...lb);
  $('reactionChart').__hover={...b,xmin,xmax,ymin:lb[0],ymax:lb[1],series:[{label:'Geschwindigkeit',color:'#1976d2',unit:'km/h',values:speed},{label:'Bremsdruck',color:'#d24632',unit:'bar',values:brake}],extra:i=>{const r=rows[i],out=[['Längsbeschl.',fmt(r.longitudinal_acceleration,'m/s²')]];if(r.brake_pedal_pressed!=null)out.push(['Bremspedal',Number(r.brake_pedal_pressed)>=1?'betätigt':'frei']);return out}};
  refreshHover()}
// Werte beim Überfahren mit der Maus bzw. Antippen auf dem Handy anzeigen
const hover={canvas:null,x:0,y:0,tip:null,cursor:null,dots:[]};
function hideHover(){hover.canvas=null;if(hover.tip)hover.tip.hidden=true;if(hover.cursor)hover.cursor.hidden=true;hover.dots.forEach(d=>d.hidden=true)}
function showHover(canvas,x,y){hover.canvas=canvas;hover.x=x;hover.y=y;refreshHover()}
function refreshHover(){const canvas=hover.canvas;if(!canvas)return;const st=canvas.__hover;const rect=canvas.getBoundingClientRect();const mx=hover.x-rect.left,my=hover.y-rect.top;
  if(!st||!rows.length||mx<st.p.l-6||mx>st.w-st.p.r+6||my<st.p.t||my>st.h-st.p.b){if(hover.tip)hover.tip.hidden=true;if(hover.cursor)hover.cursor.hidden=true;hover.dots.forEach(d=>d.hidden=true);return}
  const pw=st.w-st.p.l-st.p.r,ph=st.h-st.p.t-st.p.b,xOf=t=>st.p.l+pw*((t-st.xmin)/(st.xmax-st.xmin||1)),yOf=v=>st.p.t+ph*(1-(v-st.ymin)/(st.ymax-st.ymin||1));
  const t=st.xmin+(mx-st.p.l)/pw*(st.xmax-st.xmin);let lo=0,hi=rows.length-1;while(hi-lo>1){const m=(lo+hi)>>1;if(Number(rows[m].elapsed_s)<t)lo=m;else hi=m}const i=Math.abs(Number(rows[lo].elapsed_s)-t)<=Math.abs(Number(rows[hi].elapsed_s)-t)?lo:hi;
  if(!hover.tip){hover.tip=document.createElement('div');hover.tip.className='chart-tip';hover.cursor=document.createElement('div');hover.cursor.className='chart-cursor';document.body.append(hover.cursor,hover.tip)}
  while(hover.dots.length<st.series.length){const d=document.createElement('span');d.className='chart-dot';document.body.append(d);hover.dots.push(d)}
  const x=rect.left+xOf(Number(rows[i].elapsed_s));hover.cursor.style.left=x+'px';hover.cursor.style.top=rect.top+st.p.t+'px';hover.cursor.style.height=ph+'px';hover.cursor.hidden=false;
  hover.dots.forEach((d,k)=>{const s=st.series[k],v=s&&s.values[i];if(!s||!Number.isFinite(v)){d.hidden=true;return}d.style.background=s.color;d.style.left=x+'px';d.style.top=rect.top+yOf(v)+'px';d.hidden=false});
  hover.tip.innerHTML=`<strong>Zeit ${fmt(rows[i].elapsed_s,'s')}</strong>`+st.series.map(s=>`<div><i style="background:${s.color}"></i>${escapeHtml(s.label)}: ${fmt(s.values[i],s.unit)}</div>`).join('')+st.extra(i).map(([l,v])=>`<div><i></i>${escapeHtml(l)}: ${escapeHtml(v)}</div>`).join('');
  hover.tip.hidden=false;const left=hover.x+14+hover.tip.offsetWidth>innerWidth-8?hover.x-14-hover.tip.offsetWidth:hover.x+14;hover.tip.style.left=Math.max(8,left)+'px';hover.tip.style.top=Math.max(8,Math.min(hover.y+14,innerHeight-hover.tip.offsetHeight-8))+'px'}
for(const id of ['distanceChart','reactionChart']){const c=$(id);c.addEventListener('pointermove',e=>showHover(c,e.clientX,e.clientY));c.addEventListener('pointerdown',e=>showHover(c,e.clientX,e.clientY));c.addEventListener('pointerleave',e=>{if(e.pointerType==='mouse')hideHover()})}
document.addEventListener('pointerdown',e=>{if(hover.canvas&&e.target!==hover.canvas)hideHover()});window.addEventListener('scroll',()=>{if(hover.canvas)refreshHover()},{passive:true});
async function init(){scenarioFields();fetch('/api/system-time',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({unix_ms:Date.now()})}).catch(()=>{});try{const r=await fetch('/api/config').then(x=>x.json());$('vehicle').innerHTML=r.vehicles.map(v=>`<option value="${v.id}">${escapeHtml(v.name)} · ID ${v.id}</option>`).join('');$('channel').value=r.defaults.can_channel;setState(await fetch('/api/status').then(x=>x.json()))}catch(e){$('message').textContent=e.message}connectWs();timer();window.addEventListener('resize',drawAll)}init();
</script></body></html>'''


if __name__ == "__main__":
    import uvicorn

    print(f"AEB-Liveoberflaeche: http://raspberrypi.local:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)
