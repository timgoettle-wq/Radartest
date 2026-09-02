import time

from diagnostics.vehicle import VehicleDiagnostic


VEHICLE_ID = 2
INTERVAL = 0.2


def main():
    vehicle = VehicleDiagnostic(
        vehicle_id=VEHICLE_ID
    )

    try:
        vehicle.connect()

        print("Fahrzeugdiagnose verbunden")
        print("Messung läuft - Abbruch mit Ctrl+C\n")

        while True:

            values = vehicle.read_signals([
                "distance",
                "angle"
            ])

            distance = values["distance"]["value"]
            distance_unit = values["distance"]["unit"]

            angle = values["angle"]["value"]
            angle_unit = values["angle"]["unit"]

            print(
                f"Abstand: {distance:7.2f} {distance_unit} | "
                f"Winkel: {angle:7.2f} {angle_unit}"
            )

            time.sleep(INTERVAL)

    except KeyboardInterrupt:
        print("\nMessung beendet")

    finally:
        vehicle.disconnect()


if __name__ == "__main__":
    main()