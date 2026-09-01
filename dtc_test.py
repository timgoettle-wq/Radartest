from diagnostics.vehicle import VehicleDiagnostic


VEHICLE_ID = 1


def main():

    vehicle = VehicleDiagnostic(
        vehicle_id=VEHICLE_ID
    )

    try:

        vehicle.connect()

        print("Fahrzeug verbunden\n")

        results = vehicle.read_dtcs()

        for ecu in results:

            print(
                f"ECU: {ecu['ecu_name']}"
            )

            print(
                "Status Availability Mask:",
                ecu["status_availability_mask"]
            )

            if not ecu["dtcs"]:

                print(
                    "Keine DTCs vorhanden"
                )

            else:

                for dtc in ecu["dtcs"]:

                    print(
                        f"DTC: {dtc['code']} | "
                        f"Status: {dtc['status']}"
                    )

            print()

    finally:

        vehicle.disconnect()


if __name__ == "__main__":
    main()