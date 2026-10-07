"""Standalone-Demo fuer RadEsT-/AEB-Versuche auf dem Rollenpruefstand.

Das Skript schreibt nichts in die Fahrzeugdatenbank. Es liest lediglich die
Radar-Diagnosekonfiguration des beim Start angegebenen Fahrzeugs. Die
ESP-/Bremswerte werden unabhaengig davon ueber das Fahrzeugprofil aus
demo_scripte/fahrzeugprofile/ gelesen (UDS-DIDs und/oder passiv mitgelesene
CAN-Frames). Der CAN-Bus wird zusaetzlich komplett passiv aufgezeichnet.

RadEsT-Verbindung, Precheck und RCS laufen ueber den TestController wie im
gefuehrten Pruefablauf. Die Radar-Livesignale werden ueber dessen
Fahrzeugverbindung gelesen.

Start aus dem Projektordner:
    python demo_scripte/aeb_pruefstand_test.py

Wichtig: Dieses Skript ersetzt weder die Pruefstandsfreigabe noch einen
hardwareseitigen Not-Aus. Es sendet die im Profil konfigurierten Diagnoseanfragen,
steuert den Rollenpruefstand aber nicht.
"""

import csv
import json
import math
import socket
import struct
import sys
import threading
import time
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from demo_scripte.fahrzeugprofile import (
    STANDARD_SIGNALS,
    can_signals,
    profile_for_vehicle,
    profile_summary,
    standard_values,
    uds_active,
    uds_dids,
    uds_signals,
)
from test_controller import TestController


# ======================================================
# VERBINDUNG UND AUFZEICHNUNG
# ======================================================

RADEST_IP = "192.168.0.10"
RADEST_PORT = 2101
CAN_CHANNEL = "can0"

# 20 Hz fuer die zusammengefuehrte Mess-CSV. Die separate Roh-CAN-Datei
# enthaelt weiterhin jedes empfangene CAN-Frame mit Zeitstempel.
SAMPLE_INTERVAL_S = 0.05
MAX_SIGNAL_AGE_S = 0.5


# ======================================================
# LOKALE UDS-DIAGNOSE (KEINE DATENBANK)
# ======================================================

# Adressen, DIDs, CAN-IDs und Signaldefinitionen stehen fahrzeugspezifisch in
# demo_scripte/fahrzeugprofile/. Das Profil wird ueber die Vehicle-ID gewaehlt.
DIAGNOSTIC_INTERVAL_S = 0.10
DIAGNOSTIC_TIMEOUT_S = 0.50
RADAR_INTERVAL_S = 0.05

# Wie im gefuehrten Pruefablauf (TestController.prepare_dynamic_measurement).
RCS_CONSTANT_STATES_TEXT = {
    "0": "Konstante RCS",
    "1": "Variable RCS / konstante Ausgangsleistung",
}

# RCS-Arbeitspunkt des RadEsT, in jeder Zeile der Mess-CSV wiederholt.
RADEST_COLUMNS = (
    "radest_rcs_dbsm",
    "radest_tx_value",
    "radest_att_set",
    "radest_temperature_c",
)

CAN_FRAME = struct.Struct("=IB3x8s")
CAN_EFF_MASK = 0x1FFFFFFF
CAN_ERR_FLAG = 0x20000000
CAN_RTR_FLAG = 0x40000000

SOL_CAN_ISOTP = getattr(socket, "SOL_CAN_ISOTP", 106)
CAN_ISOTP_OPTS = getattr(socket, "CAN_ISOTP_OPTS", 1)
CAN_ISOTP_TX_PADDING = getattr(socket, "CAN_ISOTP_TX_PADDING", 0x0004)


def ask_float(prompt, default, minimum=None, maximum=None):
    while True:
        answer = input(f"{prompt} [{default:g}]: ").strip().replace(",", ".")
        try:
            value = float(answer) if answer else float(default)
        except ValueError:
            print("Bitte eine Zahl eingeben.")
            continue

        if not math.isfinite(value) or (minimum is not None and value < minimum):
            print(f"Der Wert muss mindestens {minimum:g} betragen.")
            continue
        if maximum is not None and value > maximum:
            print(f"Der Wert darf hoechstens {maximum:g} betragen.")
            continue
        return value


def ask_choice(prompt, options, default):
    for key, text in options.items():
        print(f"{key} - {text}")
    while True:
        choice = input(f"{prompt} [{default}]: ").strip() or default
        if choice in options:
            return choice
        print(f"Bitte {' oder '.join(options)} eingeben.")


def ask_vehicle_id():
    while True:
        answer = input("Vehicle-ID aus der Datenbank: ").strip()
        try:
            vehicle_id = int(answer)
        except ValueError:
            print("Bitte eine ganzzahlige Vehicle-ID eingeben.")
            continue

        if vehicle_id <= 0:
            print("Die Vehicle-ID muss groesser als 0 sein.")
            continue
        return vehicle_id


def ask_scenario():
    print("\nSzenario")
    print("1 - Konstanter Zielabstand")
    print("2 - Dynamische Annaeherung")
    print("    Fuer ein stehendes Strassenobjekt: Schliessgeschwindigkeit = Rollenpruefstandsgeschwindigkeit.")

    while True:
        choice = input("Auswahl [2]: ").strip() or "2"
        if choice in {"1", "2"}:
            break
        print("Bitte 1 oder 2 eingeben.")

    if choice == "1":
        return {
            "type": "constant",
            "distance_m": ask_float("Zielabstand in m", 20.0, 0.1),
            "duration_s": ask_float("Messdauer in s", 15.0, 0.1),
        }

    start_distance = ask_float("Startdistanz in m", 40.0, 0.1)
    end_distance = ask_float("Enddistanz in m", 5.0, 0.1)

    if end_distance >= start_distance:
        raise ValueError("Bei einer Annaeherung muss die Enddistanz kleiner als die Startdistanz sein.")

    return {
        "type": "dynamic",
        "start_distance_m": start_distance,
        "end_distance_m": end_distance,
        "velocity_kmh": ask_float("RadEsT-Schliessgeschwindigkeit in km/h", 10.0, 0.1),
        "pre_hold_s": ask_float("Haltezeit vor Bewegung in s", 2.0, 0.0),
        "post_hold_s": ask_float("Haltezeit am Ende in s", 3.0, 0.0),
        "rcs_constant_state": int(
            ask_choice("RCS-Verhalten im Szenario", RCS_CONSTANT_STATES_TEXT, "0")
        ),
        # Hin und zurueck: Start -> Ende -> Start mit derselben Geschwindigkeit,
        # an der Enddistanz ohne Haltezeit. Die Haltezeit am Ende gilt am Schluss.
        "round_trip": ask_choice(
            "Ablauf",
            {"1": "Nur Hinweg (Start -> Ende)", "2": "Hin und zurueck (Start -> Ende -> Start)"},
            "1",
        ) == "2",
    }


def decode_signal(data, definition):
    configured_start = definition.get("start_byte")
    if configured_start is None:
        return None

    start = int(configured_start)

    # Bitsignal innerhalb eines Bytes, Bit 0 = niederwertigstes Bit.
    if "bit" in definition:
        bit = definition["bit"]
        bit_length = int(definition.get("bit_length", 1))
        if bit is None or start < 0 or start >= len(data) or not 0 <= int(bit) <= 8 - bit_length:
            return None
        raw = (data[start] >> int(bit)) & ((1 << bit_length) - 1)
        return raw * float(definition.get("factor", 1.0)) + float(definition.get("offset", 0.0))

    length = int(definition["length"])
    end = start + length

    if start < 0 or length <= 0 or end > len(data):
        return None

    raw = int.from_bytes(
        data[start:end],
        byteorder=definition.get("byte_order", "big"),
        signed=bool(definition.get("signed", False)),
    )
    return raw * float(definition.get("factor", 1.0)) + float(definition.get("offset", 0.0))


class PassiveCanMonitor:
    """Empfaengt klassische CAN-Frames, sendet aber selbst keine Nachrichten."""

    def __init__(self, channel, raw_csv_file, time_origin, signals=None):
        self.channel = channel
        self.raw_csv_file = raw_csv_file
        self.time_origin = time_origin
        self.signals = dict(signals or {})
        self.socket = None
        self.thread = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.latest_frames = {}
        self.error = None

    def start(self):
        if not hasattr(socket, "PF_CAN"):
            raise RuntimeError("SocketCAN ist auf diesem Betriebssystem nicht verfuegbar.")

        self.socket = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        self.socket.settimeout(0.2)
        self.socket.bind((self.channel,))
        self.thread = threading.Thread(target=self._receive_loop, name="PassiveCanMonitor", daemon=True)
        self.thread.start()

    def _receive_loop(self):
        try:
            with self.raw_csv_file.open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=["timestamp_unix_ns", "elapsed_s", "can_id", "dlc", "data_hex"],
                    delimiter=";",
                )
                writer.writeheader()

                while not self.stop_event.is_set():
                    try:
                        frame = self.socket.recv(CAN_FRAME.size)
                    except socket.timeout:
                        continue

                    if len(frame) != CAN_FRAME.size:
                        continue

                    can_id_with_flags, dlc, payload = CAN_FRAME.unpack(frame)
                    if can_id_with_flags & (CAN_ERR_FLAG | CAN_RTR_FLAG):
                        continue

                    can_id = can_id_with_flags & CAN_EFF_MASK
                    data = payload[: min(dlc, 8)]
                    now = time.perf_counter()
                    unix_ns = time.time_ns()

                    with self.lock:
                        self.latest_frames[can_id] = (now, data)

                    writer.writerow(
                        {
                            "timestamp_unix_ns": unix_ns,
                            "elapsed_s": f"{now - self.time_origin:.6f}",
                            "can_id": f"0x{can_id:X}",
                            "dlc": len(data),
                            "data_hex": data.hex(" ").upper(),
                        }
                    )

        except Exception as error:
            self.error = error

    def snapshot(self):
        now = time.perf_counter()
        values = {}

        with self.lock:
            frames = dict(self.latest_frames)

        for name, definition in self.signals.items():
            configured_id = definition.get("can_id")
            if configured_id is None:
                values[name] = None
                values[f"{name}_age_s"] = None
                continue

            frame = frames.get(int(configured_id))
            if frame is None:
                values[name] = None
                values[f"{name}_age_s"] = None
                continue

            received_at, data = frame
            age_s = now - received_at
            values[f"{name}_age_s"] = age_s
            values[name] = None if age_s > MAX_SIGNAL_AGE_S else decode_signal(data, definition)

        return values

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=1.0)
        if self.socket is not None:
            self.socket.close()
            self.socket = None


class StandaloneUdsMonitor:
    """Fragt die DIDs aus dem Fahrzeugprofil zyklisch ohne Datenbank ab."""

    def __init__(self, channel, raw_csv_file, time_origin, uds_config, signals):
        self.channel = channel
        self.raw_csv_file = raw_csv_file
        self.time_origin = time_origin
        self.request_id = int(uds_config["request_id"])
        self.response_id = int(uds_config["response_id"])
        self.service = int(uds_config.get("service", 0x22))
        self.dids = tuple(int(did) for did in uds_config["dids"])
        self.tx_padding = int(uds_config.get("tx_padding", 0x00))
        self.signals = dict(signals)
        self.socket = None
        self.thread = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.latest_responses = {}
        self.latest_received_at = {}
        self.latest_status = {
            did: "noch_nicht_abgefragt"
            for did in self.dids
        }
        self.latest_errors = {}
        self.error = None

    def start(self):
        if not hasattr(socket, "AF_CAN") or not hasattr(socket, "CAN_ISOTP"):
            raise RuntimeError("Linux ISO-TP ist auf diesem System nicht verfuegbar.")

        self.socket = socket.socket(socket.AF_CAN, socket.SOCK_DGRAM, socket.CAN_ISOTP)

        options = struct.pack(
            "=IIBBBB",
            CAN_ISOTP_TX_PADDING,
            0,
            0,
            self.tx_padding,
            0,
            0,
        )
        self.socket.setsockopt(SOL_CAN_ISOTP, CAN_ISOTP_OPTS, options)
        self.socket.settimeout(DIAGNOSTIC_TIMEOUT_S)

        # Linux ISO-TP erwartet (Interface, RX-ID, TX-ID).
        self.socket.bind(
            (
                self.channel,
                self.response_id,
                self.request_id,
            )
        )

        self.thread = threading.Thread(
            target=self._request_loop,
            name="StandaloneUdsMonitor",
            daemon=True,
        )
        self.thread.start()

    def _validate_response(self, response, expected_did):
        if not response:
            return "leer", "Leere Diagnoseantwort"

        if response[0] == 0x7F:
            if len(response) >= 3:
                return "negative_antwort", f"NRC 0x{response[2]:02X}"
            return "negative_antwort", "Ungueltige negative UDS-Antwort"

        expected_service = (self.service + 0x40) & 0xFF
        if len(response) < 3:
            return "ungueltig", "UDS-Antwort kuerzer als Service und DID"
        if response[0] != expected_service:
            return "ungueltig", f"Service 0x{response[0]:02X} statt 0x{expected_service:02X}"

        response_did = (response[1] << 8) | response[2]
        if response_did != expected_did:
            return "ungueltig", f"DID 0x{response_did:04X} statt 0x{expected_did:04X}"

        return "ok", None

    def _request_loop(self):
        try:
            with self.raw_csv_file.open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=[
                        "timestamp_unix_ns",
                        "elapsed_s",
                        "request_id",
                        "response_id",
                        "service",
                        "did",
                        "status",
                        "response_hex",
                        "error",
                    ],
                    delimiter=";",
                )
                writer.writeheader()

                while not self.stop_event.is_set():
                    cycle_started = time.perf_counter()

                    for did in self.dids:
                        if self.stop_event.is_set():
                            break

                        request = bytes(
                            [
                                self.service,
                                (did >> 8) & 0xFF,
                                did & 0xFF,
                            ]
                        )
                        response = None
                        status = "fehler"
                        error_text = None

                        try:
                            self.socket.send(request)
                            response = self.socket.recv(4095)
                            status, error_text = self._validate_response(response, did)
                        except socket.timeout:
                            status = "timeout"
                            error_text = "Keine Diagnoseantwort innerhalb des Timeouts"
                        except OSError as error:
                            if self.stop_event.is_set():
                                break
                            status = "socket_fehler"
                            error_text = str(error)

                        received_at = time.perf_counter()
                        with self.lock:
                            if response is not None:
                                self.latest_responses[did] = response
                                self.latest_received_at[did] = received_at
                            self.latest_status[did] = status
                            self.latest_errors[did] = error_text

                        writer.writerow(
                            {
                                "timestamp_unix_ns": time.time_ns(),
                                "elapsed_s": f"{received_at - self.time_origin:.6f}",
                                "request_id": f"0x{self.request_id:X}",
                                "response_id": f"0x{self.response_id:X}",
                                "service": f"0x{self.service:02X}",
                                "did": f"0x{did:04X}",
                                "status": status,
                                "response_hex": response.hex(" ").upper() if response else "",
                                "error": error_text or "",
                            }
                        )
                        file.flush()

                    remaining = DIAGNOSTIC_INTERVAL_S - (time.perf_counter() - cycle_started)
                    if remaining > 0:
                        self.stop_event.wait(remaining)

        except Exception as error:
            self.error = error

    def snapshot(self):
        now = time.perf_counter()
        with self.lock:
            responses = dict(self.latest_responses)
            received_times = dict(self.latest_received_at)
            statuses = dict(self.latest_status)
            errors = dict(self.latest_errors)

        values = {}
        for did in self.dids:
            prefix = f"diagnostic_{did:04x}"
            response = responses.get(did)
            received_at = received_times.get(did)
            values[f"{prefix}_response_hex"] = (
                response.hex(" ").upper()
                if response
                else None
            )
            values[f"{prefix}_response_age_s"] = (
                None
                if received_at is None
                else now - received_at
            )
            values[f"{prefix}_status"] = statuses.get(did)
            values[f"{prefix}_error"] = errors.get(did)

        for name, definition in self.signals.items():
            did = int(definition["did"])
            response = responses.get(did)
            expected_header = bytes(
                [
                    (self.service + 0x40) & 0xFF,
                    (did >> 8) & 0xFF,
                    did & 0xFF,
                ]
            )
            payload = None
            if response and statuses.get(did) == "ok" and response[:3] == expected_header:
                payload = response

            values[name] = (
                decode_signal(payload, definition)
                if payload is not None
                else None
            )

        return values

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=DIAGNOSTIC_TIMEOUT_S + 1.0)
        if self.socket is not None:
            self.socket.close()
            self.socket = None


class DatabaseRadarMonitor:
    """Liest die Radar-Livesignale ueber die Fahrzeugverbindung des TestControllers.

    Der TestController haelt bereits die ISO-TP-Sockets zum Radar. Ein zweiter
    Socket auf dieselben IDs wuerde ihm die Antworten wegnehmen.
    """

    SIGNAL_MAPPING = {
        "distance": "radar_distance",
        "relative_speed": "radar_relative_speed",
    }

    def __init__(self, diagnostic):
        self.diagnostic = diagnostic
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.thread = None
        self.latest_values = {}
        self.latest_received_at = None
        self.latest_status = "noch_nicht_abgefragt"
        self.latest_error = None
        self.error = None

        available_signals = set(self.diagnostic.get_available_signals())
        self.signal_names = [
            name
            for name in self.SIGNAL_MAPPING
            if name in available_signals
        ]
        if not self.signal_names:
            raise ValueError(
                f"Fuer Vehicle-ID {diagnostic.vehicle_id} ist weder 'distance' noch "
                "'relative_speed' konfiguriert."
            )

    def start(self):
        self.thread = threading.Thread(
            target=self._read_loop,
            name="DatabaseRadarMonitor",
            daemon=True,
        )
        self.thread.start()

    @staticmethod
    def _extract_value(decoded):
        if isinstance(decoded, dict):
            return decoded.get("value")
        return decoded

    def _read_loop(self):
        try:
            while not self.stop_event.is_set():
                started = time.perf_counter()
                try:
                    result = self.diagnostic.read_signals(self.signal_names)
                    values = {
                        self.SIGNAL_MAPPING[name]: self._extract_value(result[name])
                        for name in self.signal_names
                    }
                    received_at = time.perf_counter()
                    with self.lock:
                        self.latest_values = values
                        self.latest_received_at = received_at
                        self.latest_status = "ok"
                        self.latest_error = None
                except Exception as error:
                    with self.lock:
                        self.latest_status = "lesefehler"
                        self.latest_error = str(error)

                remaining = RADAR_INTERVAL_S - (time.perf_counter() - started)
                if remaining > 0:
                    self.stop_event.wait(remaining)
        except Exception as error:
            self.error = error

    def snapshot(self):
        now = time.perf_counter()
        with self.lock:
            values = dict(self.latest_values)
            received_at = self.latest_received_at
            status = self.latest_status
            error_text = self.latest_error

        age_s = None if received_at is None else now - received_at
        snapshot = {
            "radar_distance": None,
            "radar_distance_age_s": age_s,
            "radar_relative_speed": None,
            "radar_relative_speed_age_s": age_s,
            "radar_diagnostic_status": status,
            "radar_diagnostic_error": error_text,
        }
        if age_s is not None and age_s <= MAX_SIGNAL_AGE_S:
            snapshot.update(values)
        return snapshot

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=1.5)


def dynamic_movement_duration(actual):
    return abs(actual["end_distance_m"] - actual["start_distance_m"]) / (actual["velocity_kmh"] / 3.6)


def expected_dynamic_distance(actual, movement_elapsed_s):
    start = actual["start_distance_m"]
    end = actual["end_distance_m"]
    duration = dynamic_movement_duration(actual)
    progress = min(max(movement_elapsed_s / duration, 0.0), 1.0)
    return start + (end - start) * progress


def prepare_return_leg(controller, actual):
    """Stellt den RadEsT fuer den Rueckweg ein: Enddistanz -> Startdistanz.

    Laeuft direkt ueber controller.radest, damit test_controller.py unveraendert
    bleibt. Geschwindigkeit, RCS-Verhalten und RCS bleiben vom Hinweg eingestellt.
    """
    radest = controller.radest
    radest.scenario_distance_start(actual["end_distance_m"])
    radest.scenario_distance_end(actual["start_distance_m"])
    return {
        "start_distance_m": radest.scenario_get_distance_start(),
        "end_distance_m": radest.scenario_get_distance_end(),
        "velocity_kmh": float(radest.scenario_get_velocity()),
    }


class RadestScenarioRunner:
    """Fuehrt das RadEsT-Szenario im Hintergrund aus, optional mit Rueckweg.

    Beim Rueckweg werden direkt nach dem Hinweg die Distanzen getauscht und das
    Szenario ohne Haltezeit erneut gestartet. return_started wird unmittelbar
    vor dem zweiten Trigger gesetzt.
    """

    def __init__(self, controller, scenario, stop_event=None):
        self.controller = controller
        self.scenario = scenario
        self.stop_event = stop_event or threading.Event()
        self.return_started = threading.Event()
        self.return_leg = None
        self.error = None
        self.thread = threading.Thread(target=self._run, name="RadestScenario", daemon=True)

    def start(self):
        self.thread.start()

    def is_alive(self):
        return self.thread.is_alive()

    def join(self, timeout=None):
        self.thread.join(timeout)

    def _run(self):
        try:
            self.controller.radest.scenario_trigger()
            if not self.scenario.get("round_trip") or self.stop_event.is_set():
                return
            self.return_leg = prepare_return_leg(self.controller, self.scenario["actual"])
            self.return_started.set()
            self.controller.radest.scenario_trigger()
        except Exception as error:
            self.error = error
        finally:
            self.return_started.set()

    def wait_for_return(self):
        """Liefert die Distanzen des gestarteten Rueckwegs."""
        if self.error is not None:
            raise RuntimeError(f"RadEsT-Szenariofehler: {self.error}")
        if self.return_leg is None:
            raise RuntimeError("RadEsT hat den Rueckweg nicht gestartet.")
        return self.return_leg


# Jeder Precheck (auch uebersprungene und wiederholte) wird hier angehaengt,
# damit kein Ergebnis verloren geht. Pro Test steht zusaetzlich die Liste der
# Prechecks der Sitzung in test_config.json.
PRECHECK_LOG = PROJECT_ROOT / "test_runs" / "aeb_prechecks.csv"
PRECHECK_LOG_COLUMNS = (
    "time",
    "vehicle_id",
    "status",
    "polarization",
    "frequency_range",
    "power",
)


def save_precheck(vehicle_id, result, path=PRECHECK_LOG):
    """Haengt einen Precheck an die Precheck-CSV an und gibt den Eintrag zurueck."""
    entry = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "vehicle_id": vehicle_id,
        "status": "uebersprungen" if result.get("skipped") else "durchgefuehrt",
        "polarization": result.get("polarization"),
        "frequency_range": result.get("frequency_range"),
        "power": result.get("power"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=PRECHECK_LOG_COLUMNS, delimiter=";")
        if new_file:
            writer.writeheader()
        writer.writerow({key: "" if value is None else value for key, value in entry.items()})
    return {**result, **entry}


def write_test_config(path, config_data):
    path.write_text(
        json.dumps(config_data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


# Laenger als das wird nach der berechneten Hinwegdauer nicht auf den RadEsT
# gewartet, bevor der Rueckweg als fehlgeschlagen gilt.
RETURN_PREPARE_TIMEOUT_S = 15.0


RADAR_UNITS = {
    "radar_distance": "m",
    "radar_relative_speed": "km/h",
}


def configured_signal_text(values, profile):
    parts = []
    units = {**RADAR_UNITS, **STANDARD_SIGNALS}
    preferred = (
        "radar_distance",
        "radar_relative_speed",
        *STANDARD_SIGNALS,
    )

    for name in preferred:
        value = values.get(name)
        if value is None:
            continue
        unit = units.get(name, "")
        parts.append(f"{name}={value:.2f}{(' ' + unit) if unit else ''}")

    if parts:
        return " | ".join(parts)

    dids = uds_dids(profile)
    diagnostic_statuses = [
        values.get(f"diagnostic_{did:04x}_status")
        for did in dids
    ]
    if any(diagnostic_statuses):
        status_text = ", ".join(
            f"0x{did:04X}={status}"
            for did, status in zip(dids, diagnostic_statuses)
        )
        return f"Diagnose: {status_text} | Signaldekodierung noch nicht vollstaendig konfiguriert"
    return "keine Live-Signale konfiguriert"


def measurement_fieldnames(profile):
    signal_columns = []
    for signal_name in can_signals(profile):
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
    for did in uds_dids(profile):
        prefix = f"diagnostic_{did:04x}"
        diagnostic_columns.extend(
            (
                f"{prefix}_response_hex",
                f"{prefix}_response_age_s",
                f"{prefix}_status",
                f"{prefix}_error",
            )
        )
    if uds_active(profile):
        diagnostic_columns.extend(uds_signals(profile))

    # Standardsignale stehen bei jedem Fahrzeug in der CSV. Heisst ein
    # Rohsignal genauso (z. B. steering_angle beim W213), bleibt es eine Spalte.
    return list(
        dict.fromkeys(
            [
                "timestamp_unix_ns",
                "elapsed_s",
                "phase",
                "radest_target_distance_m",
                "scenario_velocity_kmh",
                *signal_columns,
                *radar_columns,
                *diagnostic_columns,
                *STANDARD_SIGNALS,
                *RADEST_COLUMNS,
            ]
        )
    )


def write_sample(
    writer,
    rows,
    monitor,
    diagnostic_monitor,
    radar_monitor,
    origin,
    phase,
    target_distance_m,
    scenario_velocity_kmh,
    profile,
    extra=None,
):
    values = monitor.snapshot()
    if diagnostic_monitor is not None:
        values.update(diagnostic_monitor.snapshot())
    if radar_monitor is not None:
        values.update(radar_monitor.snapshot())
    values.update(standard_values(profile, values))
    row = {
        "timestamp_unix_ns": time.time_ns(),
        "elapsed_s": time.perf_counter() - origin,
        "phase": phase,
        "radest_target_distance_m": target_distance_m,
        "scenario_velocity_kmh": scenario_velocity_kmh,
        **(extra or {}),
        **values,
    }
    writer.writerow(row)
    rows.append(row)
    return values


def sample_for_duration(
    writer,
    rows,
    monitor,
    diagnostic_monitor,
    radar_monitor,
    origin,
    duration_s,
    phase,
    distance_function,
    velocity_kmh,
    profile,
    extra=None,
):
    started = time.perf_counter()
    next_sample = started
    next_print = started

    while True:
        now = time.perf_counter()
        phase_elapsed = now - started
        if phase_elapsed >= duration_s:
            break

        target_distance = distance_function(phase_elapsed)
        values = write_sample(
            writer,
            rows,
            monitor,
            diagnostic_monitor,
            radar_monitor,
            origin,
            phase,
            target_distance,
            velocity_kmh,
            profile,
            extra,
        )

        if now >= next_print:
            print(
                f"t={now - origin:7.2f} s | Phase={phase:9s} | "
                f"RadEsT={target_distance:7.2f} m | {configured_signal_text(values, profile)}"
            )
            next_print = now + 0.25

        next_sample += SAMPLE_INTERVAL_S
        time.sleep(max(0.0, next_sample - time.perf_counter()))


def prepare_radest(controller, scenario):
    """Stellt das Szenario ueber den TestController ein und liefert die RCS-Grenzen.

    Die angeforderten Werte bleiben in scenario, die vom RadEsT tatsaechlich
    uebernommenen Werte stehen danach in scenario["actual"].
    """
    if scenario["type"] == "constant":
        result = controller.prepare_static_measurement(scenario["distance_m"])
        scenario["actual"] = {"distance_m": result["radest_distance"]}
        return result["rcs_limits"]

    result = controller.prepare_dynamic_measurement(
        start_distance_m=scenario["start_distance_m"],
        end_distance_m=scenario["end_distance_m"],
        velocity_kmh=scenario["velocity_kmh"],
        rcs_constant_state=scenario["rcs_constant_state"],
        pre_hold_s=scenario["pre_hold_s"],
        post_hold_s=scenario["post_hold_s"],
    )
    scenario["actual"] = {
        "pre_hold_distance_m": result["pre_hold_distance"],
        "start_distance_m": result["start_distance"],
        "end_distance_m": result["end_distance"],
        "velocity_kmh": result["velocity_kmh"],
    }
    return result["rcs_limits"]


def start_radest(controller, scenario, rcs_dbsm):
    """Setzt die RCS ueber den TestController und liest die RadEsT-Temperatur."""
    if scenario["type"] == "constant":
        return controller.start_static_measurement(scenario["distance_m"], rcs_dbsm)

    return controller.start_dynamic_measurement(
        start_distance_m=scenario["start_distance_m"],
        end_distance_m=scenario["end_distance_m"],
        velocity_kmh=scenario["velocity_kmh"],
        rcs_constant_state=scenario["rcs_constant_state"],
        rcs_dbsm=rcs_dbsm,
    )


def radest_row_values(start_result):
    setting = (start_result.get("rcs_radest_setting") or {}).get("values", {})
    return {
        "radest_rcs_dbsm": start_result.get("rcs_dbsm"),
        "radest_tx_value": setting.get("txValue"),
        "radest_att_set": setting.get("attSet"),
        "radest_temperature_c": start_result.get("radest_temperature_c"),
    }


def rcs_limits_text(limits):
    return (
        f"{limits['rcs_min_dbsm']:.2f} bis {limits['rcs_max_dbsm']:.2f} dBsm "
        f"(Polarisation {limits['polarization']}, EIRP {limits['eirp_dbm']:.2f} dBm)"
    )


def create_diagram(rows, output_file):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("Matplotlib nicht installiert - Diagramm wird uebersprungen.")
        return None

    if not rows:
        return None

    times = [row["elapsed_s"] for row in rows]
    figure, axes = plt.subplots(3, 1, figsize=(13, 10), sharex=True)

    axes[0].plot(times, [row["radest_target_distance_m"] for row in rows], label="RadEsT Soll", color="#008143")
    radar_values = [row.get("radar_distance") for row in rows]
    if any(value is not None for value in radar_values):
        axes[0].plot(times, radar_values, label="Fahrzeug Radar", color="#d58a00")
    axes[0].set_ylabel("Distanz [m]")
    axes[0].legend()
    axes[0].grid(True, alpha=0.35)

    vehicle_speeds = [row.get("vehicle_speed") for row in rows]
    if any(value is not None for value in vehicle_speeds):
        axes[1].plot(
            times,
            vehicle_speeds,
            label="Fahrzeuggeschwindigkeit",
            color="#1976d2",
        )
    axes[1].set_ylabel("Geschwindigkeit [km/h]")
    if axes[1].lines:
        axes[1].legend()
    axes[1].grid(True, alpha=0.35)

    for name, label in (
        ("brake_pressure", "Bremsdruck [bar]"),
        ("brake_pedal_pressed", "Bremspedal betaetigt [0/1]"),
    ):
        values = [row.get(name) for row in rows]
        if any(value is not None for value in values):
            axes[2].plot(times, values, label=label)
    axes[2].set_ylabel("Bremse / AEB")
    axes[2].set_xlabel("Zeit [s]")
    if axes[2].lines:
        axes[2].legend()
    axes[2].grid(True, alpha=0.35)

    figure.suptitle("AEB-Pruefstandtest")
    figure.tight_layout()
    figure.savefig(output_file, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return output_file


def main():
    vehicle_id = ask_vehicle_id()
    profile = profile_for_vehicle(vehicle_id)
    print(profile_summary(profile))
    scenario = ask_scenario()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_directory = PROJECT_ROOT / "test_runs" / f"aeb_bench_{timestamp}"
    output_directory.mkdir(parents=True, exist_ok=True)

    measurement_csv = output_directory / "measurement.csv"
    raw_can_csv = output_directory / "can_raw.csv"
    diagnostic_raw_csv = output_directory / "diagnostic_raw.csv"
    diagram_file = output_directory / "measurement.png"
    (output_directory / "vehicle_profile.json").write_text(
        json.dumps(profile, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    fieldnames = measurement_fieldnames(profile)

    controller = None
    monitor = None
    diagnostic_monitor = None
    radar_monitor = None
    scenario_thread = None
    rows = []
    origin = time.perf_counter()

    try:
        # RadEsT, Precheck und RCS laufen ueber den TestController wie im
        # gefuehrten Pruefablauf. Dabei wird auch die Radarverbindung aufgebaut.
        controller = TestController(vehicle_id, radest_ip=RADEST_IP, radest_port=RADEST_PORT)
        controller.connect()

        print("\nPrecheck")
        prechecks = []
        choice = ask_choice("Auswahl", {"1": "Precheck durchfuehren", "2": "Precheck ueberspringen"}, "1")
        while choice == "1":
            precheck = save_precheck(vehicle_id, controller.run_precheck())
            prechecks.append(precheck)
            print(
                f"Precheck {len(prechecks)} abgeschlossen: Polarisation {precheck['polarization']}, "
                f"Frequenzbereich {precheck['frequency_range']}, Leistung {precheck['power']}"
            )
            choice = ask_choice("Weiter", {"1": "Precheck wiederholen", "2": "Weiter zum Test"}, "2")
        if not prechecks:
            precheck = save_precheck(vehicle_id, controller.skip_precheck())
            prechecks.append(precheck)
            print("Precheck uebersprungen.")
        print(f"Prechecks gespeichert in {PRECHECK_LOG}")

        rcs_limits = prepare_radest(controller, scenario)
        print(f"RCS-Bereich: {rcs_limits_text(rcs_limits)}")
        rcs_dbsm = ask_float(
            "RCS in dBsm",
            min(max(10.0, rcs_limits["rcs_min_dbsm"]), rcs_limits["rcs_max_dbsm"]),
            rcs_limits["rcs_min_dbsm"],
            rcs_limits["rcs_max_dbsm"],
        )

        if input("Zum Start START eingeben: ").strip() != "START":
            print("Test nicht gestartet.")
            return

        radest_result = start_radest(controller, scenario, rcs_dbsm)
        radest_values = radest_row_values(radest_result)
        config_data = {
            "vehicle_id": vehicle_id,
            "scenario": scenario,
            "precheck": precheck,
            "prechecks": prechecks,
            "radest": radest_result,
        }
        write_test_config(output_directory / "test_config.json", config_data)
        print(
            f"RCS gesetzt: {radest_values['radest_rcs_dbsm']} dBsm, "
            f"txValue {radest_values['radest_tx_value']}, attSet {radest_values['radest_att_set']}, "
            f"RadEsT-Temperatur {radest_values['radest_temperature_c']} degC"
        )

        radar_monitor = DatabaseRadarMonitor(controller.vehicle)
        radar_monitor.start()

        monitor = PassiveCanMonitor(CAN_CHANNEL, raw_can_csv, origin, can_signals(profile))
        monitor.start()

        if uds_active(profile):
            diagnostic_monitor = StandaloneUdsMonitor(
                CAN_CHANNEL,
                diagnostic_raw_csv,
                origin,
                profile["uds"],
                uds_signals(profile),
            )
            diagnostic_monitor.start()

        print(f"\nAusgabeordner: {output_directory}")
        print("Der komplette CAN-Bus wird passiv in can_raw.csv aufgezeichnet.")
        print(
            f"Radar-Diagnose ueber TestController aktiv: Vehicle-ID {vehicle_id}, "
            f"Signale {', '.join(radar_monitor.signal_names)}."
        )
        if diagnostic_monitor is not None:
            did_text = ", ".join(f"0x{did:04X}" for did in diagnostic_monitor.dids)
            print(
                f"UDS-Abfrage aktiv: 0x{diagnostic_monitor.request_id:X} -> "
                f"0x{diagnostic_monitor.response_id:X}, DIDs {did_text}."
            )
        else:
            print(f"UDS-Abfrage fuer {profile['name']} deaktiviert.")
        for number in range(3, 0, -1):
            print(f"Start in {number} ...")
            time.sleep(1.0)

        origin = time.perf_counter()

        with measurement_csv.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames, delimiter=";")
            writer.writeheader()

            if scenario["type"] == "constant":
                sample_for_duration(
                    writer,
                    rows,
                    monitor,
                    diagnostic_monitor,
                    radar_monitor,
                    origin,
                    scenario["duration_s"],
                    "constant",
                    lambda _elapsed: scenario["actual"]["distance_m"],
                    0.0,
                    profile,
                    radest_values,
                )

            else:
                sample_for_duration(
                    writer,
                    rows,
                    monitor,
                    diagnostic_monitor,
                    radar_monitor,
                    origin,
                    scenario["pre_hold_s"],
                    "pre_hold",
                    lambda _elapsed: scenario["actual"]["pre_hold_distance_m"],
                    scenario["actual"]["velocity_kmh"],
                    profile,
                    radest_values,
                )

                scenario_thread = RadestScenarioRunner(controller, scenario)
                scenario_thread.start()

                def sample(duration_s, phase, distance_function):
                    sample_for_duration(
                        writer,
                        rows,
                        monitor,
                        diagnostic_monitor,
                        radar_monitor,
                        origin,
                        duration_s,
                        phase,
                        distance_function,
                        scenario["actual"]["velocity_kmh"],
                        profile,
                        radest_values,
                    )

                sample(
                    dynamic_movement_duration(scenario["actual"]),
                    "moving",
                    lambda elapsed: expected_dynamic_distance(scenario["actual"], elapsed),
                )

                if scenario["round_trip"]:
                    # Bis der RadEsT den Hinweg beendet und den Rueckweg
                    # gestartet hat, an der Enddistanz weiter aufzeichnen.
                    end_distance = scenario["actual"]["end_distance_m"]
                    waited = time.perf_counter()
                    while not scenario_thread.return_started.is_set():
                        if time.perf_counter() - waited > RETURN_PREPARE_TIMEOUT_S:
                            raise RuntimeError("RadEsT hat den Hinweg nicht rechtzeitig beendet.")
                        sample(0.05, "turn", lambda _elapsed: end_distance)

                    return_leg = scenario_thread.wait_for_return()
                    scenario["actual"]["return_leg"] = return_leg
                    print(
                        f"Rueckweg: {return_leg['start_distance_m']} m -> "
                        f"{return_leg['end_distance_m']} m mit {return_leg['velocity_kmh']} km/h"
                    )
                    sample(
                        dynamic_movement_duration(return_leg),
                        "moving_back",
                        lambda elapsed: expected_dynamic_distance(return_leg, elapsed),
                    )
                    final_distance = return_leg["end_distance_m"]
                else:
                    final_distance = scenario["actual"]["end_distance_m"]

                sample(scenario["post_hold_s"], "post_hold", lambda _elapsed: final_distance)

                scenario_thread.join(timeout=1.0)
                if scenario_thread.is_alive():
                    print("WARNUNG: RadEsT meldet das Szenario noch nicht als beendet.")
                if scenario_thread.error is not None:
                    raise RuntimeError(f"RadEsT-Szenariofehler: {scenario_thread.error}")

                if scenario["round_trip"]:
                    # Enthaelt jetzt auch die Distanzen des Rueckwegs.
                    write_test_config(output_directory / "test_config.json", config_data)

        if monitor.error is not None:
            raise RuntimeError(f"CAN-Aufzeichnung fehlgeschlagen: {monitor.error}")
        if diagnostic_monitor is not None and diagnostic_monitor.error is not None:
            raise RuntimeError(f"Diagnoseaufzeichnung fehlgeschlagen: {diagnostic_monitor.error}")
        if radar_monitor is not None and radar_monitor.error is not None:
            raise RuntimeError(f"Radar-Diagnose fehlgeschlagen: {radar_monitor.error}")

        diagram = create_diagram(rows, diagram_file)
        print("\nTest abgeschlossen.")
        print(f"Messwerte: {measurement_csv}")
        print(f"CAN-Rohdaten: {raw_can_csv}")
        if diagnostic_monitor is not None:
            print(f"Diagnose-Rohdaten: {diagnostic_raw_csv}")
        if diagram is not None:
            print(f"Diagramm: {diagram}")

    except KeyboardInterrupt:
        print("\nTest durch Benutzer abgebrochen.")

    finally:
        if diagnostic_monitor is not None:
            diagnostic_monitor.stop()
        if monitor is not None:
            monitor.stop()
        if radar_monitor is not None:
            radar_monitor.stop()

        if controller is not None:
            controller.disconnect()
            print("RadEsT- und Fahrzeugverbindung getrennt.")


if __name__ == "__main__":
    main()
