"""Standalone-Demo fuer RadEsT-/AEB-Versuche auf dem Rollenpruefstand.

Das Skript verwendet absichtlich NICHT die Fahrzeugdatenbank. Es steuert den
RadEsT, zeichnet den CAN-Bus passiv auf und fragt zusaetzlich eine lokal
konfigurierte UDS-DIDs ueber Linux ISO-TP ab. Die vorlaeufigen
Signaldefinitionen werden direkt im Konfigurationsblock gepflegt.

Start aus dem Projektordner:
    python demo_scripte/aeb_pruefstand_test.py

Wichtig: Dieses Skript ersetzt weder die Pruefstandsfreigabe noch einen
hardwareseitigen Not-Aus. Es sendet die unten konfigurierten Diagnoseanfragen,
steuert den Rollenpruefstand aber nicht.
"""

import csv
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

from radest.device import RadestDevice


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

# ESP-Diagnosedaten aus den mitgeschnittenen Diagnosetests:
#   0x7E2  22 20 01 -> 0x7EA  62 20 01 ...  (Raddrehzahlen)
#   0x7E2  22 20 02 -> 0x7EA  62 20 02 ...  (Brems-/ESP-Sensoren)
DIAGNOSTIC_ENABLED = True
DIAGNOSTIC_REQUEST_ID = 0x7E2
DIAGNOSTIC_RESPONSE_ID = 0x7EA
DIAGNOSTIC_SERVICE = 0x22
DIAGNOSTIC_DIDS = (0x2001, 0x2002)
DIAGNOSTIC_INTERVAL_S = 0.10
DIAGNOSTIC_TIMEOUT_S = 0.50
DIAGNOSTIC_TX_PADDING = 0x00

# start_byte zaehlt jeweils ab dem ersten Datenbyte NACH "62 DID_H DID_L".
# Solange Byteposition und Umrechnung noch unbekannt sind, bleibt start_byte
# auf None. Die kompletten Antworten werden trotzdem in diagnostic_raw.csv
# gespeichert und koennen fuer das Reverse Engineering verglichen werden.
DIAGNOSTIC_SIGNALS = {
    "wheel_speed_fl": {
        "did": 0x2001,
        "start_byte": None,
        "length": 2,
        "byte_order": "big",
        "signed": False,
        "factor": 1.0,
        "offset": 0.0,
        "unit": "km/h",
    },
    "wheel_speed_fr": {
        "did": 0x2001,
        "start_byte": None,
        "length": 2,
        "byte_order": "big",
        "signed": False,
        "factor": 1.0,
        "offset": 0.0,
        "unit": "km/h",
    },
    "wheel_speed_rl": {
        "did": 0x2001,
        "start_byte": None,
        "length": 2,
        "byte_order": "big",
        "signed": False,
        "factor": 1.0,
        "offset": 0.0,
        "unit": "km/h",
    },
    "wheel_speed_rr": {
        "did": 0x2001,
        "start_byte": None,
        "length": 2,
        "byte_order": "big",
        "signed": False,
        "factor": 1.0,
        "offset": 0.0,
        "unit": "km/h",
    },
    "main_brake_pressure": {
        "did": 0x2002,
        "start_byte": 15,
        "length": 2,
        "byte_order": "big",
        "signed": True,
        "factor": 0.01000091556,
        "offset": 0.0,
        "unit": "bar",
    },
    "brake_circuit_2_pressure": {
        "did": 0x2002,
        "start_byte": 18,
        "length": 2,
        "byte_order": "big",
        "signed": True,
        "factor": 0.01000091556,
        "offset": 0.0,
        "unit": "bar",
    },
    "brake_vacuum": {
        "did": 0x2002,
        "start_byte": None,
        "length": 2,
        "byte_order": "big",
        "signed": True,
        "factor": 1.0,
        "offset": 0.0,
        "unit": "bar",
    },
    "steering_angle": {
        "did": 0x2002,
        "start_byte": 12,
        "length": 2,
        "byte_order": "big",
        "signed": True,
        "factor": 0.04375133518,
        "offset": 0.0,
        "unit": "deg",
    },
    "longitudinal_acceleration": {
        "did": 0x2002,
        "start_byte": 3,
        "length": 2,
        "byte_order": "big",
        "signed": True,
        "factor": 0.0980999176,
        "offset": 0.0,
        "unit": "m/s^2",
    },
    "lateral_acceleration": {
        "did": 0x2002,
        "start_byte": 6,
        "length": 2,
        "byte_order": "big",
        "signed": True,
        "factor": 0.0980999176,
        "offset": 0.0,
        "unit": "m/s^2",
    },
    "yaw_rate": {
        "did": 0x2002,
        "start_byte": 9,
        "length": 2,
        "byte_order": "big",
        "signed": True,
        "factor": 0.002859889523,
        "offset": 0.0,
        "unit": "deg/s",
    },
}


# ======================================================
# VORLAEUFIGE LIVE-SIGNALE
# ======================================================

# can_id=None bedeutet: Signal noch nicht konfiguriert. Sobald ein Signal
# reverse-engineert ist, CAN-ID und Byteauswertung hier eintragen.
#
# Die erste Version unterstuetzt byteweise ausgerichtete Signale:
#   can_id:      z. B. 0x353
#   start_byte:  0 = erstes Datenbyte
#   length:      Anzahl Bytes
#   byte_order:  "big" oder "little"
#   signed:      True oder False
#   factor:      physikalischer Wert = Rohwert * Faktor + Offset
#   offset:      physikalischer Offset
#   unit:        nur fuer die Anzeige

SIGNALS = {
    "vehicle_speed": {
        "can_id": None,
        "start_byte": 0,
        "length": 2,
        "byte_order": "big",
        "signed": False,
        "factor": 0.01,
        "offset": 0.0,
        "unit": "km/h",
    },
    "wheel_speed_fl": {
        "can_id": None,
        "start_byte": 0,
        "length": 2,
        "byte_order": "big",
        "signed": False,
        "factor": 0.01,
        "offset": 0.0,
        "unit": "km/h",
    },
    "wheel_speed_fr": {
        "can_id": None,
        "start_byte": 0,
        "length": 2,
        "byte_order": "big",
        "signed": False,
        "factor": 0.01,
        "offset": 0.0,
        "unit": "km/h",
    },
    "wheel_speed_rl": {
        "can_id": None,
        "start_byte": 0,
        "length": 2,
        "byte_order": "big",
        "signed": False,
        "factor": 0.01,
        "offset": 0.0,
        "unit": "km/h",
    },
    "wheel_speed_rr": {
        "can_id": None,
        "start_byte": 0,
        "length": 2,
        "byte_order": "big",
        "signed": False,
        "factor": 0.01,
        "offset": 0.0,
        "unit": "km/h",
    },
    "radar_distance": {
        "can_id": None,
        "start_byte": 0,
        "length": 2,
        "byte_order": "big",
        "signed": False,
        "factor": 0.1,
        "offset": 0.0,
        "unit": "m",
    },
    "radar_relative_speed": {
        "can_id": None,
        "start_byte": 0,
        "length": 2,
        "byte_order": "big",
        "signed": True,
        "factor": 0.01,
        "offset": 0.0,
        "unit": "km/h",
    },
    "brake_pressure": {
        "can_id": None,
        "start_byte": 0,
        "length": 2,
        "byte_order": "big",
        "signed": False,
        "factor": 0.1,
        "offset": 0.0,
        "unit": "bar",
    },
    "aeb_state": {
        "can_id": None,
        "start_byte": 0,
        "length": 1,
        "byte_order": "big",
        "signed": False,
        "factor": 1.0,
        "offset": 0.0,
        "unit": "",
    },
}


CAN_FRAME = struct.Struct("=IB3x8s")
CAN_EFF_MASK = 0x1FFFFFFF
CAN_ERR_FLAG = 0x20000000
CAN_RTR_FLAG = 0x40000000

SOL_CAN_ISOTP = getattr(socket, "SOL_CAN_ISOTP", 106)
CAN_ISOTP_OPTS = getattr(socket, "CAN_ISOTP_OPTS", 1)
CAN_ISOTP_TX_PADDING = getattr(socket, "CAN_ISOTP_TX_PADDING", 0x0004)


def ask_float(prompt, default, minimum=None):
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
        return value


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
    }


def decode_signal(data, definition):
    configured_start = definition.get("start_byte")
    if configured_start is None:
        return None

    start = int(configured_start)
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

    def __init__(self, channel, raw_csv_file, time_origin):
        self.channel = channel
        self.raw_csv_file = raw_csv_file
        self.time_origin = time_origin
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

        for name, definition in SIGNALS.items():
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
    """Fragt mehrere lokal konfigurierte DIDs zyklisch ohne Datenbank ab."""

    def __init__(self, channel, raw_csv_file, time_origin):
        self.channel = channel
        self.raw_csv_file = raw_csv_file
        self.time_origin = time_origin
        self.socket = None
        self.thread = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.latest_responses = {}
        self.latest_received_at = {}
        self.latest_status = {
            did: "noch_nicht_abgefragt"
            for did in DIAGNOSTIC_DIDS
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
            DIAGNOSTIC_TX_PADDING,
            0,
            0,
        )
        self.socket.setsockopt(SOL_CAN_ISOTP, CAN_ISOTP_OPTS, options)
        self.socket.settimeout(DIAGNOSTIC_TIMEOUT_S)

        # Linux ISO-TP erwartet (Interface, RX-ID, TX-ID).
        self.socket.bind(
            (
                self.channel,
                DIAGNOSTIC_RESPONSE_ID,
                DIAGNOSTIC_REQUEST_ID,
            )
        )

        self.thread = threading.Thread(
            target=self._request_loop,
            name="StandaloneUdsMonitor",
            daemon=True,
        )
        self.thread.start()

    @staticmethod
    def _validate_response(response, expected_did):
        if not response:
            return "leer", "Leere Diagnoseantwort"

        if response[0] == 0x7F:
            if len(response) >= 3:
                return "negative_antwort", f"NRC 0x{response[2]:02X}"
            return "negative_antwort", "Ungueltige negative UDS-Antwort"

        expected_service = (DIAGNOSTIC_SERVICE + 0x40) & 0xFF
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

                    for did in DIAGNOSTIC_DIDS:
                        if self.stop_event.is_set():
                            break

                        request = bytes(
                            [
                                DIAGNOSTIC_SERVICE,
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
                                "request_id": f"0x{DIAGNOSTIC_REQUEST_ID:X}",
                                "response_id": f"0x{DIAGNOSTIC_RESPONSE_ID:X}",
                                "service": f"0x{DIAGNOSTIC_SERVICE:02X}",
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
        for did in DIAGNOSTIC_DIDS:
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

        for name, definition in DIAGNOSTIC_SIGNALS.items():
            did = int(definition["did"])
            response = responses.get(did)
            expected_header = bytes(
                [
                    (DIAGNOSTIC_SERVICE + 0x40) & 0xFF,
                    (did >> 8) & 0xFF,
                    did & 0xFF,
                ]
            )
            payload = None
            if response and statuses.get(did) == "ok" and response[:3] == expected_header:
                payload = response[3:]

            values[name] = (
                decode_signal(payload, definition)
                if payload is not None
                else None
            )
            if name in SIGNALS:
                received_at = received_times.get(did)
                values[f"{name}_age_s"] = (
                    None
                    if received_at is None
                    else now - received_at
                )

        return values

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=DIAGNOSTIC_TIMEOUT_S + 1.0)
        if self.socket is not None:
            self.socket.close()
            self.socket = None


def expected_dynamic_distance(scenario, movement_elapsed_s):
    start = scenario["start_distance_m"]
    end = scenario["end_distance_m"]
    duration = abs(end - start) / (scenario["velocity_kmh"] / 3.6)
    progress = min(max(movement_elapsed_s / duration, 0.0), 1.0)
    return start + (end - start) * progress


def configured_signal_text(values):
    parts = []
    preferred = (
        "vehicle_speed",
        "wheel_speed_fl",
        "wheel_speed_fr",
        "wheel_speed_rl",
        "wheel_speed_rr",
        "radar_distance",
        "main_brake_pressure",
        "brake_circuit_2_pressure",
        "brake_vacuum",
        "steering_angle",
        "longitudinal_acceleration",
        "lateral_acceleration",
        "yaw_rate",
        "brake_pressure",
        "aeb_state",
    )

    for name in preferred:
        value = values.get(name)
        if value is None:
            continue
        definition = SIGNALS.get(name) or DIAGNOSTIC_SIGNALS.get(name) or {}
        unit = definition.get("unit", "")
        parts.append(f"{name}={value:.2f}{(' ' + unit) if unit else ''}")

    if parts:
        return " | ".join(parts)

    diagnostic_statuses = [
        values.get(f"diagnostic_{did:04x}_status")
        for did in DIAGNOSTIC_DIDS
    ]
    if any(diagnostic_statuses):
        status_text = ", ".join(
            f"0x{did:04X}={status}"
            for did, status in zip(DIAGNOSTIC_DIDS, diagnostic_statuses)
        )
        return f"Diagnose: {status_text} | Signaldekodierung noch nicht vollstaendig konfiguriert"
    return "keine Live-Signale konfiguriert"


def write_sample(
    writer,
    rows,
    monitor,
    diagnostic_monitor,
    origin,
    phase,
    target_distance_m,
    scenario_velocity_kmh,
):
    values = monitor.snapshot()
    if diagnostic_monitor is not None:
        values.update(diagnostic_monitor.snapshot())
    row = {
        "timestamp_unix_ns": time.time_ns(),
        "elapsed_s": time.perf_counter() - origin,
        "phase": phase,
        "radest_target_distance_m": target_distance_m,
        "scenario_velocity_kmh": scenario_velocity_kmh,
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
    origin,
    duration_s,
    phase,
    distance_function,
    velocity_kmh,
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
            origin,
            phase,
            target_distance,
            velocity_kmh,
        )

        if now >= next_print:
            print(
                f"t={now - origin:7.2f} s | Phase={phase:9s} | "
                f"RadEsT={target_distance:7.2f} m | {configured_signal_text(values)}"
            )
            next_print = now + 0.25

        next_sample += SAMPLE_INTERVAL_S
        time.sleep(max(0.0, next_sample - time.perf_counter()))


def configure_radest_scenario(radest, scenario):
    if scenario["type"] == "constant":
        radest.target_set_distance(scenario["distance_m"])
        actual_distance = radest.target_get_distance()
        scenario["distance_m"] = actual_distance
        return

    radest.scenario_distance_start(scenario["start_distance_m"])
    radest.scenario_distance_end(scenario["end_distance_m"])
    radest.scenario_velocity(scenario["velocity_kmh"])

    scenario["start_distance_m"] = radest.scenario_get_distance_start()
    scenario["end_distance_m"] = radest.scenario_get_distance_end()
    scenario["velocity_kmh"] = radest.scenario_get_velocity()

    radest.target_set_distance(scenario["start_distance_m"])
    scenario["start_distance_m"] = radest.target_get_distance()


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

    speed_names = ("vehicle_speed", "wheel_speed_fl", "wheel_speed_fr", "wheel_speed_rl", "wheel_speed_rr")
    for name in speed_names:
        values = [row.get(name) for row in rows]
        if any(value is not None for value in values):
            axes[1].plot(times, values, label=name)
    axes[1].set_ylabel("Geschwindigkeit [km/h]")
    if axes[1].lines:
        axes[1].legend(ncol=3)
    axes[1].grid(True, alpha=0.35)

    for name in (
        "main_brake_pressure",
        "brake_circuit_2_pressure",
        "brake_vacuum",
        "brake_pressure",
        "aeb_state",
    ):
        values = [row.get(name) for row in rows]
        if any(value is not None for value in values):
            axes[2].plot(times, values, label=name)
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
    scenario = ask_scenario()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_directory = PROJECT_ROOT / "test_runs" / f"aeb_bench_{timestamp}"
    output_directory.mkdir(parents=True, exist_ok=True)

    measurement_csv = output_directory / "measurement.csv"
    raw_can_csv = output_directory / "can_raw.csv"
    diagnostic_raw_csv = output_directory / "diagnostic_raw.csv"
    diagram_file = output_directory / "measurement.png"

    signal_columns = []
    for signal_name in SIGNALS:
        signal_columns.extend((signal_name, f"{signal_name}_age_s"))

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
    diagnostic_columns.extend(
        signal_name
        for signal_name in DIAGNOSTIC_SIGNALS
        if signal_name not in SIGNALS
    )

    fieldnames = [
        "timestamp_unix_ns",
        "elapsed_s",
        "phase",
        "radest_target_distance_m",
        "scenario_velocity_kmh",
        *signal_columns,
        *diagnostic_columns,
    ]

    print("\nSICHERHEITSHINWEIS")
    print("Das Skript steuert den Pruefstand nicht und ist kein Not-Aus.")
    print("Nur auf einem fuer automatische Bremseingriffe freigegebenen Pruefstand verwenden.")
    print("Der Bereich vor dem Fahrzeug muss frei bleiben.")
    if DIAGNOSTIC_ENABLED:
        did_text = ", ".join(f"0x{did:04X}" for did in DIAGNOSTIC_DIDS)
        print(
            f"Das Skript fragt zyklisch die DIDs {did_text} mit "
            f"Service 0x{DIAGNOSTIC_SERVICE:02X} auf CAN-ID "
            f"0x{DIAGNOSTIC_REQUEST_ID:X} ab."
        )
        print("Ein anderes Diagnosegeraet fuer diesen ECU-Kanal vorher trennen.")

    if input("Zum Start START eingeben: ").strip() != "START":
        print("Test nicht gestartet.")
        return

    radest = RadestDevice(RADEST_IP, RADEST_PORT)
    monitor = None
    diagnostic_monitor = None
    connected = False
    original_distance = None
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

        configure_radest_scenario(radest, scenario)

        monitor = PassiveCanMonitor(CAN_CHANNEL, raw_can_csv, origin)
        monitor.start()

        if DIAGNOSTIC_ENABLED:
            diagnostic_monitor = StandaloneUdsMonitor(CAN_CHANNEL, diagnostic_raw_csv, origin)
            diagnostic_monitor.start()

        print(f"\nAusgabeordner: {output_directory}")
        print("Der komplette CAN-Bus wird passiv in can_raw.csv aufgezeichnet.")
        if diagnostic_monitor is not None:
            did_text = ", ".join(f"0x{did:04X}" for did in DIAGNOSTIC_DIDS)
            print(
                f"UDS-Abfrage aktiv: 0x{DIAGNOSTIC_REQUEST_ID:X} -> "
                f"0x{DIAGNOSTIC_RESPONSE_ID:X}, DIDs {did_text}."
            )
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
                    origin,
                    scenario["duration_s"],
                    "constant",
                    lambda _elapsed: scenario["distance_m"],
                    0.0,
                )

            else:
                sample_for_duration(
                    writer,
                    rows,
                    monitor,
                    diagnostic_monitor,
                    origin,
                    scenario["pre_hold_s"],
                    "pre_hold",
                    lambda _elapsed: scenario["start_distance_m"],
                    scenario["velocity_kmh"],
                )

                def trigger_scenario():
                    try:
                        radest.scenario_trigger()
                    except Exception as error:
                        scenario_error.append(error)

                scenario_thread = threading.Thread(target=trigger_scenario, name="RadestScenario", daemon=True)
                scenario_thread.start()

                movement_duration = (
                    abs(scenario["end_distance_m"] - scenario["start_distance_m"])
                    / (scenario["velocity_kmh"] / 3.6)
                )
                sample_for_duration(
                    writer,
                    rows,
                    monitor,
                    diagnostic_monitor,
                    origin,
                    movement_duration,
                    "moving",
                    lambda elapsed: expected_dynamic_distance(scenario, elapsed),
                    scenario["velocity_kmh"],
                )

                sample_for_duration(
                    writer,
                    rows,
                    monitor,
                    diagnostic_monitor,
                    origin,
                    scenario["post_hold_s"],
                    "post_hold",
                    lambda _elapsed: scenario["end_distance_m"],
                    scenario["velocity_kmh"],
                )

                scenario_thread.join(timeout=1.0)
                if scenario_thread.is_alive():
                    print("WARNUNG: RadEsT meldet das Szenario noch nicht als beendet.")
                if scenario_error:
                    raise RuntimeError(f"RadEsT-Szenariofehler: {scenario_error[0]}")

        if monitor.error is not None:
            raise RuntimeError(f"CAN-Aufzeichnung fehlgeschlagen: {monitor.error}")
        if diagnostic_monitor is not None and diagnostic_monitor.error is not None:
            raise RuntimeError(f"Diagnoseaufzeichnung fehlgeschlagen: {diagnostic_monitor.error}")

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

        # Waehrend SCENARIO:TRIGGER noch blockiert, darf derselbe Socket nicht
        # fuer einen weiteren Befehl verwendet werden.
        scenario_running = scenario_thread is not None and scenario_thread.is_alive()

        if connected and not scenario_running and original_distance is not None:
            try:
                radest.target_set_distance(original_distance)
                print(f"Urspruengliche Zieldistanz wiederhergestellt: {original_distance:.2f} m")
            except Exception as error:
                print(f"WARNUNG: Zieldistanz konnte nicht wiederhergestellt werden: {error}")

        if connected:
            radest.disconnect()
            print("RadEsT-Verbindung getrennt.")


if __name__ == "__main__":
    main()
