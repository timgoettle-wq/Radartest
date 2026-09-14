"""Demo: Erkennungsgrenze des Fahrzeugradars ueber die Daempfung bestimmen.

1db Attenuation = 4 dB weniger power am Empfänger.

Der RadEsT simuliert ein statisches Ziel. Die Daempfung wird schrittweise
erhoeht und die vom Fahrzeug gemeldete Objektdistanz mehrfach ausgelesen.
Alle Einzelmessungen werden als CSV unter ``test_runs`` gespeichert.

Start aus dem Projektordner:
    python demo_scripte/attenuation_threshold_test.py
"""

import csv
import math
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from test_controller import TestController


# ======================================================
# KONFIGURATION
# ======================================================

VEHICLE_ID = 1
TARGET_DISTANCE_M = 10.0

START_ATTENUATION_DB = 0.0
MAX_ATTENUATION_DB = 31.75
ATTENUATION_STEP_DB = 0.25

# Wartezeit nach jeder Aenderung, damit das Fahrzeugtracking reagieren kann.
SETTLE_TIME_S = 1.0

# Mehrere Messwerte verhindern, dass ein einzelner Aussetzer den Test beendet.
SAMPLES_PER_LEVEL = 5
SAMPLE_INTERVAL_S = 0.25
MIN_DETECTED_SAMPLES = 3

# Ein Wert gilt nur als erkannt, wenn er nahe an der simulierten Distanz liegt.
DISTANCE_TOLERANCE_M = 3.0

# Erst nach mehreren aufeinanderfolgenden verlorenen Stufen automatisch stoppen.
STOP_AFTER_LOST_LEVELS = 3


def validate_configuration():
    """Prueft den vom RadEsT erlaubten Bereich und das 0,25-dB-Raster."""

    for name, value in (
        ("START_ATTENUATION_DB", START_ATTENUATION_DB),
        ("MAX_ATTENUATION_DB", MAX_ATTENUATION_DB),
        ("ATTENUATION_STEP_DB", ATTENUATION_STEP_DB),
    ):
        if not math.isclose(value * 4, round(value * 4), abs_tol=1e-9):
            raise ValueError(f"{name} muss ein Vielfaches von 0,25 dB sein.")

    if not 0 <= START_ATTENUATION_DB <= 31.75:
        raise ValueError("START_ATTENUATION_DB muss zwischen 0 und 31,75 dB liegen.")
    if not START_ATTENUATION_DB <= MAX_ATTENUATION_DB <= 31.75:
        raise ValueError("MAX_ATTENUATION_DB muss zwischen Startwert und 31,75 dB liegen.")
    if ATTENUATION_STEP_DB <= 0:
        raise ValueError("ATTENUATION_STEP_DB muss groesser als 0 sein.")
    if not 1 <= MIN_DETECTED_SAMPLES <= SAMPLES_PER_LEVEL:
        raise ValueError("MIN_DETECTED_SAMPLES passt nicht zu SAMPLES_PER_LEVEL.")


def attenuation_levels():
    """Erzeugt exakte Viertel-dB-Werte ohne Gleitkomma-Aufaddierungsfehler."""

    start_tick = round(START_ATTENUATION_DB * 4)
    stop_tick = round(MAX_ATTENUATION_DB * 4)
    step_tick = round(ATTENUATION_STEP_DB * 4)
    return [tick / 4 for tick in range(start_tick, stop_tick + 1, step_tick)]


def get_vehicle_distance(measurement):
    value = measurement.get("vehicle", {}).get("distance", {}).get("value")
    if value is None or value == "":
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def run_level(controller, writer, requested_attenuation_db):
    """Setzt eine Daempfungsstufe und liest mehrere Fahrzeugwerte aus."""

    controller.radest.system_set_attenuation(requested_attenuation_db)
    actual_attenuation_db = controller.radest.system_get_attenuation()

    time.sleep(SETTLE_TIME_S)

    rows = []
    numeric_distances = []
    detected_samples = 0

    for sample_number in range(1, SAMPLES_PER_LEVEL + 1):
        vehicle_distance_m = None
        distance_error_m = None
        sample_detected = False
        error_message = ""

        try:
            measurement = controller.read_static_measurement()
            vehicle_distance_m = get_vehicle_distance(measurement)

            if vehicle_distance_m is not None:
                numeric_distances.append(vehicle_distance_m)
                distance_error_m = vehicle_distance_m - controller.radest_distance
                sample_detected = abs(distance_error_m) <= DISTANCE_TOLERANCE_M

        except Exception as error:
            error_message = str(error)

        if sample_detected:
            detected_samples += 1

        rows.append(
            {
                "timestamp": datetime.now().isoformat(timespec="milliseconds"),
                "attenuation_requested_db": f"{requested_attenuation_db:.2f}",
                "attenuation_actual_db": f"{actual_attenuation_db:.2f}",
                "sample": sample_number,
                "target_distance_m": f"{controller.radest_distance:.2f}",
                "vehicle_distance_m": "" if vehicle_distance_m is None else f"{vehicle_distance_m:.3f}",
                "distance_error_m": "" if distance_error_m is None else f"{distance_error_m:.3f}",
                "sample_detected": int(sample_detected),
                "error": error_message,
            }
        )

        if sample_number < SAMPLES_PER_LEVEL:
            time.sleep(SAMPLE_INTERVAL_S)

    level_detected = detected_samples >= MIN_DETECTED_SAMPLES

    for row in rows:
        row["level_detected"] = int(level_detected)
        writer.writerow(row)

    median_distance = statistics.median(numeric_distances) if numeric_distances else None
    distance_text = "--" if median_distance is None else f"{median_distance:.2f} m"

    print(
        f"Daempfung {actual_attenuation_db:5.2f} dB | "
        f"erkannt {detected_samples}/{SAMPLES_PER_LEVEL} | "
        f"Fahrzeug Median {distance_text} | "
        f"Stufe {'ERKANNT' if level_detected else 'VERLOREN'}"
    )

    return level_detected, actual_attenuation_db


def main():
    validate_configuration()

    output_directory = PROJECT_ROOT / "test_runs"
    output_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    csv_file = output_directory / f"attenuation_test_{timestamp}_vehicle_{VEHICLE_ID}.csv"

    fieldnames = [
        "timestamp",
        "attenuation_requested_db",
        "attenuation_actual_db",
        "sample",
        "target_distance_m",
        "vehicle_distance_m",
        "distance_error_m",
        "sample_detected",
        "level_detected",
        "error",
    ]

    controller = TestController(vehicle_id=VEHICLE_ID)
    connected = False
    original_attenuation_db = None
    last_detected_db = None
    loss_candidate_db = None
    consecutive_lost_levels = 0

    print("Attenuation-Grenzwerttest")
    print(f"Fahrzeug-ID:       {VEHICLE_ID}")
    print(f"Zieldistanz:       {TARGET_DISTANCE_M:.2f} m")
    print(
        f"Daempfung:         {START_ATTENUATION_DB:.2f} bis "
        f"{MAX_ATTENUATION_DB:.2f} dB in {ATTENUATION_STEP_DB:.2f}-dB-Schritten"
    )
    print(f"Erkennungskriterium: mindestens {MIN_DETECTED_SAMPLES}/{SAMPLES_PER_LEVEL} Werte innerhalb +/-{DISTANCE_TOLERANCE_M:.1f} m")
    input("\nAufbau pruefen. Enter verbindet und startet den Test, Ctrl+C bricht ab: ")

    try:
        controller.connect()
        connected = True

        original_attenuation_db = controller.radest.system_get_attenuation()
        controller.radest.system_set_attenuation(START_ATTENUATION_DB)

        print("Precheck wird ausgefuehrt ...")
        controller.run_precheck()

        configuration = controller.start_static_measurement(TARGET_DISTANCE_M)
        print(f"Realisierte RadEsT-Distanz: {configuration['radest_distance']:.2f} m")
        print(f"CSV: {csv_file}\n")

        with csv_file.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames, delimiter=";")
            writer.writeheader()

            for attenuation_db in attenuation_levels():
                detected, actual_attenuation_db = run_level(controller, writer, attenuation_db)
                file.flush()

                if detected:
                    last_detected_db = actual_attenuation_db
                    consecutive_lost_levels = 0
                    loss_candidate_db = None
                else:
                    if consecutive_lost_levels == 0:
                        loss_candidate_db = actual_attenuation_db
                    consecutive_lost_levels += 1

                    if consecutive_lost_levels >= STOP_AFTER_LOST_LEVELS:
                        print(
                            f"\nObjekt bei {STOP_AFTER_LOST_LEVELS} aufeinanderfolgenden "
                            "Daempfungsstufen nicht stabil erkannt."
                        )
                        break

        print("\nErgebnis")
        print(f"Letzte stabil erkannte Daempfung: {last_detected_db if last_detected_db is not None else '--'} dB")
        print(f"Beginn des bestaetigten Zielverlusts: {loss_candidate_db if loss_candidate_db is not None else '--'} dB")
        print(f"Messdaten: {csv_file}")

    except KeyboardInterrupt:
        print("\nTest durch Benutzer abgebrochen.")

    finally:
        if connected:
            if original_attenuation_db is not None:
                try:
                    controller.radest.system_set_attenuation(original_attenuation_db)
                    restored = controller.radest.system_get_attenuation()
                    print(f"Urspruengliche Daempfung wiederhergestellt: {restored:.2f} dB")
                except Exception as error:
                    print(f"WARNUNG: Daempfung konnte nicht wiederhergestellt werden: {error}")

            controller.disconnect()
            print("Verbindungen getrennt.")


if __name__ == "__main__":
    main()
