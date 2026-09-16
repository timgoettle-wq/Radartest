"""Demo: Feste Zieldistanz mit zusaetzlicher Dopplergeschwindigkeit.

Der RadEsT behaelt eine feste Entfernung bei und simuliert gleichzeitig eine
radiale Relativgeschwindigkeit. Parallel wird das standardisierte
Fahrzeugsignal ``distance`` aus der vorhandenen Datenbankkonfiguration gelesen.

Das Skript schreibt weder in die Datenbank noch einen TestRun.

Start aus dem Projektordner:
    python demo_scripte/static_doppler_test.py
"""

import math
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from diagnostics.vehicle import VehicleDiagnostic
from radest.device import RadestDevice


# ======================================================
# KONFIGURATION
# ======================================================

VEHICLE_ID = 1

STATIC_DISTANCE_M = 20.0
RELATIVE_SPEED_KMH = 3.0

# True: Ziel bewegt sich auf das Fahrzeug zu
# False: Ziel bewegt sich vom Fahrzeug weg
MOVING_TOWARDS = True

READ_INTERVAL_S = 0.25

RADEST_IP = "192.168.0.10"
RADEST_PORT = 2101


def validate_configuration():
    if STATIC_DISTANCE_M <= 0:
        raise ValueError("STATIC_DISTANCE_M muss groesser als 0 m sein.")
    if RELATIVE_SPEED_KMH < 0:
        raise ValueError("RELATIVE_SPEED_KMH darf nicht negativ sein.")
    if READ_INTERVAL_S <= 0:
        raise ValueError("READ_INTERVAL_S muss groesser als 0 s sein.")


def extract_distance(result):
    value = result.get("value") if isinstance(result, dict) else result
    if value is None or value == "":
        return None

    distance = float(value)
    return distance if math.isfinite(distance) else None


def main():
    validate_configuration()

    radest = RadestDevice(RADEST_IP, RADEST_PORT)
    vehicle = VehicleDiagnostic(VEHICLE_ID)

    radest_connected = False
    vehicle_connected = False
    original_distance = None

    try:
        if "distance" not in vehicle.get_available_signals():
            raise KeyError(
                f"Fuer Vehicle-ID {VEHICLE_ID} ist kein Signal 'distance' definiert."
            )

        print("Verbindung zum RadEsT wird hergestellt ...")
        radest_connected = bool(radest.connect())
        if not radest_connected:
            raise ConnectionError("Verbindung zum RadEsT fehlgeschlagen.")

        try:
            original_distance = radest.target_get_distance()
        except Exception:
            original_distance = None

        print("Fahrzeugdiagnose wird verbunden ...")
        vehicle.connect()
        vehicle_connected = True

        radest.target_set_distance(STATIC_DISTANCE_M)
        actual_distance = radest.target_get_distance()
        radest.set_velocity_to_value(RELATIVE_SPEED_KMH, MOVING_TOWARDS)

        direction = "zum Fahrzeug" if MOVING_TOWARDS else "vom Fahrzeug weg"
        print("\nTest laeuft - Ctrl+C zum Beenden")
        print(f"Feste RadEsT-Distanz: {actual_distance:.2f} m")
        print(
            f"Simulierte Relativgeschwindigkeit: {RELATIVE_SPEED_KMH:.2f} km/h "
            f"({direction})\n"
        )

        started_at = time.monotonic()

        while True:
            try:
                result = vehicle.read_signal("distance")
                vehicle_distance = extract_distance(result)

                if vehicle_distance is None:
                    value_text = "keine gueltige Distanz"
                else:
                    deviation = vehicle_distance - actual_distance
                    value_text = (
                        f"Fahrzeug={vehicle_distance:7.2f} m | "
                        f"Abweichung={deviation:+7.2f} m"
                    )

                elapsed = time.monotonic() - started_at
                print(
                    f"t={elapsed:7.2f} s | RadEsT={actual_distance:7.2f} m | "
                    f"{value_text}"
                )
            except Exception as error:
                elapsed = time.monotonic() - started_at
                print(f"t={elapsed:7.2f} s | Diagnosefehler: {error}")

            time.sleep(READ_INTERVAL_S)

    except KeyboardInterrupt:
        print("\nTest beendet.")
    finally:
        if radest_connected:
            try:
                radest.set_velocity_to_value(0, True)
                print("Dopplergeschwindigkeit auf 0 km/h gesetzt.")
            except Exception as error:
                print(f"Dopplergeschwindigkeit konnte nicht zurueckgesetzt werden: {error}")

            if original_distance is not None:
                try:
                    radest.target_set_distance(original_distance)
                    print(
                        "Urspruengliche Zieldistanz wiederhergestellt: "
                        f"{original_distance:.2f} m"
                    )
                except Exception as error:
                    print(f"Zieldistanz konnte nicht wiederhergestellt werden: {error}")

        if vehicle_connected:
            vehicle.disconnect()
        if radest_connected:
            radest.disconnect()

        print("Verbindungen getrennt.")


if __name__ == "__main__":
    main()
