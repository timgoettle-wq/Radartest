import time

from database.database import get_parameter
from decoder import decode_parameter
from mock_transport import MockTransport


INTERVAL = 0.5


def build_request(parameter):
    service = parameter["service"]
    did = parameter["did"]

    return bytes([
        service,
        (did >> 8) & 0xFF,
        did & 0xFF
    ])


def main():

    parameter = get_parameter(
        vehicle_id=1,
        parameter_name="radar_target"
    )

    if parameter is None:
        raise RuntimeError(
            "radar_target nicht in Datenbank gefunden"
        )

    transport = MockTransport()

    request = build_request(parameter)

    print("Fahrzeugsimulation gestartet")
    print(
        f"DID: 0x{parameter['did']:04X}"
    )
    print("Abbruch mit Ctrl+C\n")

    try:

        while True:

            response = transport.request(
                request
            )

            if response[0] == 0x7F:

                print(
                    "Negative Response:",
                    response.hex(" ")
                )

            else:

                values = decode_parameter(
                    response,
                    parameter
                )

                print(
                    f"Status: "
                    f"{values['status']['value']:.0f} | "
                    f"Abstand: "
                    f"{values['distance']['value']:.2f} m | "
                    f"v_rel: "
                    f"{values['relative_speed']['value']:.2f} km/h | "
                    f"Winkel: "
                    f"{values['angle']['value']:.2f} deg | "
                    f"a_rel: "
                    f"{values['relative_acceleration']['value']:.2f} m/s2"
                )

            time.sleep(INTERVAL)

    except KeyboardInterrupt:
        print("\nSimulation beendet")


if __name__ == "__main__":
    main()