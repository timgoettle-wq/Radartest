"""Demo fuer eine Matrix dynamischer RadEsT-Messungen.

Das Skript fuehrt fuer jede konfigurierte Geschwindigkeit je einen Lauf
mit Annaeherung und Entfernen aus. Fuer jeden Lauf entstehen eine CSV-Datei
mit den Rohdaten und eine PNG-Grafik im zugehoerigen TestRun-Ordner.

Start aus dem Projektordner:
    python demo_scripte/dynamic_test_demo.py
"""

import csv
import sys
import time
from pathlib import Path

import matplotlib


# Auf dem Raspberry Pi gibt es normalerweise keinen angeschlossenen Bildschirm.
matplotlib.use("Agg")

import matplotlib.pyplot as plt


# Ermoeglicht den Start als Datei aus dem Unterordner demo_scripte.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from test_controller import TestController


# ======================================================
# KONFIGURATION
# ======================================================

VEHICLE_ID = 2

NEAR_DISTANCE_M = 5.0
FAR_DISTANCE_M = 15.0

VELOCITIES_KMH = [1.0, 2.0, 3.0, 4.0, 5.0]

# Jede Kombination wird so oft wiederholt.
REPETITIONS = 1

# 0,2 s entsprechen nominell 5 Messpunkten pro Sekunde.
MEASUREMENT_INTERVAL_S = 0.2

# Vor jedem Lauf muss Enter gedrueckt werden.
CONFIRM_EACH_TEST = True


def create_test_cases():
    """Erzeugt Annaeherungs- und Entfernungslaeufe."""

    test_cases = []

    for repetition in range(1, REPETITIONS + 1):
        for velocity_kmh in VELOCITIES_KMH:
            test_cases.append(
                {
                    "direction": "Annaeherung",
                    "start_distance_m": FAR_DISTANCE_M,
                    "end_distance_m": NEAR_DISTANCE_M,
                    "velocity_kmh": velocity_kmh,
                    "repetition": repetition,
                }
            )

            test_cases.append(
                {
                    "direction": "Entfernen",
                    "start_distance_m": NEAR_DISTANCE_M,
                    "end_distance_m": FAR_DISTANCE_M,
                    "velocity_kmh": velocity_kmh,
                    "repetition": repetition,
                }
            )

    return test_cases


def read_float(row, column):
    """Liest einen optionalen Zahlenwert aus einer CSV-Zeile."""

    value = row.get(column)

    if value is None or value.strip() == "":
        return None

    return float(value.replace(",", "."))


def create_diagram(csv_file, test_case):
    """Erzeugt aus einer Mess-CSV das Distanzdiagramm."""

    time_values = []
    radest_values = []
    vehicle_time_values = []
    vehicle_values = []

    with open(csv_file, newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file, delimiter=";")

        for row in reader:
            elapsed_s = read_float(row, "scenario_elapsed_s")
            radest_distance_m = read_float(row, "radest_distance_m")
            vehicle_distance_m = read_float(row, "vehicle_distance")

            if elapsed_s is None or radest_distance_m is None:
                continue

            time_values.append(elapsed_s)
            radest_values.append(radest_distance_m)

            if vehicle_distance_m is not None:
                vehicle_time_values.append(elapsed_s)
                vehicle_values.append(vehicle_distance_m)

    if not time_values:
        raise RuntimeError(f"CSV enthaelt keine Messwerte: {csv_file}")

    figure, axis = plt.subplots(figsize=(12, 6))

    axis.plot(
        time_values,
        radest_values,
        marker="o",
        markersize=3,
        linewidth=1.5,
        label="RadEsT",
    )

    axis.plot(
        vehicle_time_values,
        vehicle_values,
        marker="o",
        markersize=3,
        linewidth=1.5,
        label="Fahrzeug",
    )

    axis.set_title(
        "Dynamischer Radartest - "
        f"{test_case['direction']}, "
        f"{test_case['velocity_kmh']:g} km/h, "
        f"Wiederholung {test_case['repetition']}"
    )
    axis.set_xlabel("Zeit seit Szenariostart [s]")
    axis.set_ylabel("Abstand [m]")
    axis.grid(True, alpha=0.4)
    axis.legend()

    figure.tight_layout()

    image_file = Path(csv_file).with_suffix(".png")

    figure.savefig(
        image_file,
        dpi=180,
        bbox_inches="tight",
    )

    plt.close(figure)

    return image_file


def print_live_measurement(measurement):
    """Gibt einen neuen Messpunkt kompakt im Terminal aus."""

    vehicle_distance = (
        measurement.get("vehicle", {})
        .get("distance", {})
        .get("value")
    )

    vehicle_text = (
        "--"
        if vehicle_distance is None
        else f"{vehicle_distance:.2f} m"
    )

    print(
        f"t={measurement['scenario_elapsed_s']:6.2f} s | "
        f"RadEsT={measurement['radest_distance']:7.2f} m | "
        f"Fahrzeug={vehicle_text}"
    )


def run_dynamic_test(controller, test_case):
    """Fuehrt genau einen dynamischen Lauf aus."""

    configuration = controller.start_dynamic_measurement(
        start_distance_m=test_case["start_distance_m"],
        end_distance_m=test_case["end_distance_m"],
        velocity_kmh=test_case["velocity_kmh"],
    )

    csv_file = controller.start_logging()

    controller.start_measurement_loop(
        interval_s=MEASUREMENT_INTERVAL_S
    )

    controller.trigger_dynamic_scenario()

    last_sequence = None

    while controller.is_measurement_running():
        measurement = controller.get_latest_measurement()

        if (
            measurement is not None
            and measurement.get("sequence") != last_sequence
        ):
            print_live_measurement(measurement)
            last_sequence = measurement.get("sequence")

        time.sleep(0.05)

    # Gibt einen eventuellen Fehler aus dem Hintergrundthread weiter.
    final_measurement = controller.get_latest_measurement()

    controller.stop_measurement_loop()
    controller.stop_logging()

    if (
        final_measurement is None
        or not final_measurement.get("scenario_done", False)
    ):
        raise RuntimeError("Dynamische Messung wurde vorzeitig beendet")

    image_file = create_diagram(csv_file, test_case)

    print(f"CSV:      {csv_file}")
    print(f"Diagramm: {image_file}")
    print(
        "RadEsT-Konfiguration: "
        f"{configuration['start_distance']:.2f} -> "
        f"{configuration['end_distance']:.2f} m, "
        f"{configuration['velocity_kmh']:.2f} km/h"
    )


def main():
    test_cases = create_test_cases()
    controller = TestController(vehicle_id=VEHICLE_ID)

    print(f"Geplante dynamische Messungen: {len(test_cases)}")
    print("Testsystem wird verbunden...")

    try:
        controller.connect()

        test_run = controller.start_test_run()

        print(f"TestRun: {test_run['run_id']}")
        print(f"Ausgabeordner: {test_run['directory']}")
        print("Precheck wird ausgefuehrt...")

        controller.run_precheck()

        for index, test_case in enumerate(test_cases, start=1):
            print("\n" + "=" * 70)
            print(
                f"Test {index}/{len(test_cases)}: "
                f"{test_case['direction']}, "
                f"{test_case['start_distance_m']:g} -> "
                f"{test_case['end_distance_m']:g} m, "
                f"{test_case['velocity_kmh']:g} km/h, "
                f"Wiederholung {test_case['repetition']}"
            )
            print("=" * 70)

            if CONFIRM_EACH_TEST:
                answer = input(
                    "Enter startet den Test, q beendet die Testreihe: "
                ).strip().lower()

                if answer == "q":
                    print("Testreihe wurde vom Benutzer beendet.")
                    break

            run_dynamic_test(controller, test_case)

        print("\nTestreihe abgeschlossen.")

    except KeyboardInterrupt:
        print("\nTestreihe wurde mit Ctrl+C abgebrochen.")

    except Exception as error:
        print(f"\nFEHLER: {error}")
        raise

    finally:
        print("Verbindungen werden getrennt...")
        controller.disconnect()
        print("Testsystem beendet.")


if __name__ == "__main__":
    main()
