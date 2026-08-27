import time

from test_controller import TestController


def main():

    controller = TestController(
        vehicle_id=1,
        parameter_name="radar_target"
    )

    try:
        controller.connect()

        print("Testsystem verbunden")

        realized = controller.set_distance(
            7.0
        )

        print(
            f"Angefordert: 7.00 m | "
            f"RadEsT realisiert: "
            f"{realized:.2f} m"
        )

        controller.set_velocity(
            0.0,
            towards=True
        )

        controller.set_rcs(
            20.0
        )

        print("\nLive-Messung:\n")

        while True:

            result = controller.read_once()

            vehicle = result["vehicle"]

            distance = (
                vehicle["distance"]["value"]
                if "distance" in vehicle
                else None
            )

            error = result["distance_error"]

            print(
                f"Soll: "
                f"{result['requested_distance']:.2f} m | "
                f"RadEsT: "
                f"{result['radest_distance']:.2f} m | "
                f"Fahrzeug: "
                f"{distance:.2f} m | "
                f"Δ: "
                f"{error:+.2f} m"
            )

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\nTest beendet")

    finally:
        controller.disconnect()


if __name__ == "__main__":
    main()