import time

from test_controller import TestController


VEHICLE_ID = 2
STATIC_DISTANCE = 7.0
INTERVAL = 0.5


def main():

    controller = TestController(
        vehicle_id=VEHICLE_ID
    )

    try:
        # ------------------------------------------
        # Verbinden
        # ------------------------------------------

        print("Testsystem wird verbunden...")

        controller.connect()

        print("Testsystem verbunden.")

        print(
            "\nVerfügbare Fahrzeugsignale:"
        )

        for signal in (
            controller.get_available_signals()
        ):
            print(
                f"  - {signal}"
            )

        # ------------------------------------------
        # Precheck
        # ------------------------------------------

        print("\n")
        print("=" * 50)
        print("RADEST PRECHECK")
        print("=" * 50)

        precheck = (
            controller.run_precheck()
        )

        print(
            f"Polarisation: "
            f"{precheck['polarization']}"
        )

        print(
            f"Frequenzbereich: "
            f"{precheck['frequency_range']}"
        )

        print(
            f"Leistung: "
            f"{precheck['power']}"
        )

        # ------------------------------------------
        # Statische Messung starten
        # ------------------------------------------

        print("\n")
        print("=" * 50)
        print("STATISCHE MESSUNG")
        print("=" * 50)

        static_start = (
            controller.start_static_measurement(
                STATIC_DISTANCE
            )
        )

        print(
            f"Soll: "
            f"{static_start['requested_distance']:.2f} m"
        )

        print(
            f"RadEsT realisiert: "
            f"{static_start['radest_distance']:.2f} m"
        )

        print(
            "\nLive-Messung läuft "
            "- Ctrl+C zum Beenden\n"
        )

        # ------------------------------------------
        # Live-Werte
        # ------------------------------------------

        while True:

            measurement = (
                controller.read_static_measurement()
            )

            vehicle = measurement[
                "vehicle"
            ]

            output = [
                (
                    f"RadEsT: "
                    f"{measurement['radest_distance']:.2f} m"
                )
            ]

            # Abstand
            distance = (
                vehicle["distance"]["value"]
            )

            output.append(
                f"Abstand: {distance:.2f} m"
            )

            output.append(
                f"Δ: "
                f"{measurement['distance_error']:+.2f} m"
            )

            # Winkel
            if "angle" in vehicle:

                angle = (
                    vehicle["angle"]["value"]
                )

                unit = (
                    vehicle["angle"]["unit"]
                )

                output.append(
                    f"Winkel: "
                    f"{angle:.2f} {unit}"
                )

            # Relativgeschwindigkeit
            if "relative_speed" in vehicle:

                speed = (
                    vehicle[
                        "relative_speed"
                    ]["value"]
                )

                unit = (
                    vehicle[
                        "relative_speed"
                    ]["unit"]
                )

                output.append(
                    f"v_rel: "
                    f"{speed:.2f} {unit}"
                )

            # Relativbeschleunigung
            if (
                "relative_acceleration"
                in vehicle
            ):

                acceleration = (
                    vehicle[
                        "relative_acceleration"
                    ]["value"]
                )

                unit = (
                    vehicle[
                        "relative_acceleration"
                    ]["unit"]
                )

                output.append(
                    f"a_rel: "
                    f"{acceleration:.2f} {unit}"
                )

            print(
                " | ".join(output)
            )

            time.sleep(
                INTERVAL
            )

    except KeyboardInterrupt:
        print(
            "\nMessung beendet."
        )

    except Exception as error:
        print(
            f"\nFEHLER: {error}"
        )

    finally:
        print(
            "Verbindungen werden getrennt..."
        )

        controller.disconnect()

        print(
            "Testsystem beendet."
        )


if __name__ == "__main__":
    main()