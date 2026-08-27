from test_controller import TestController


def main():

    controller = TestController(
        vehicle_id=1,
        parameter_name="radar_target"
    )

    try:
        controller.connect()

        print("Testsystem verbunden")

        precheck = controller.run_precheck()

        print("\n--- Ergebnis Precheck ---")

        print(
            "Polarisation:",
            precheck["polarization"]
        )

        print(
            "Frequenzbereich:",
            precheck["frequency_range"]
        )

        print(
            "Leistung:",
            precheck["power"]
        )

    finally:
        controller.disconnect()


if __name__ == "__main__":
    main()