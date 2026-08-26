import socket
import struct
import subprocess
import time

SOL_CAN_ISOTP = getattr(socket, "SOL_CAN_ISOTP", 106)
CAN_ISOTP_OPTS = getattr(socket, "CAN_ISOTP_OPTS", 1)
CAN_ISOTP_TX_PADDING = getattr(socket, "CAN_ISOTP_TX_PADDING", 0x0004)

from database.database import (
    get_vehicles,
    get_parameters
)

from decoder import decode_parameter


INTERVAL = 0.5
TIMEOUT = 0.5


def configure_can(channel, bitrate):
    print(
        f"Konfiguriere {channel} mit "
        f"{bitrate} bit/s ..."
    )

    subprocess.run(
        [
            "sudo",
            "ip",
            "link",
            "set",
            channel,
            "down"
        ],
        check=False
    )

    subprocess.run(
        [
            "sudo",
            "ip",
            "link",
            "set",
            channel,
            "type",
            "can",
            "bitrate",
            str(bitrate)
        ],
        check=True
    )

    subprocess.run(
        [
            "sudo",
            "ip",
            "link",
            "set",
            channel,
            "up"
        ],
        check=True
    )


def create_isotp_socket(parameter):
    sock = socket.socket(
        socket.AF_CAN,
        socket.SOCK_DGRAM,
        socket.CAN_ISOTP
    )

    if parameter["tx_padding"] is not None:

        flags = CAN_ISOTP_TX_PADDING

        options = struct.pack(
            "=IIBBBB",
            flags,
            0,
            0,
            parameter["tx_padding"],
            0,
            0
        )

        sock.setsockopt(
            SOL_CAN_ISOTP,
            CAN_ISOTP_OPTS,
            options
        )

    sock.settimeout(TIMEOUT)

    sock.bind((
        parameter["channel"],
        parameter["response_id"],
        parameter["request_id"]
    ))

    return sock


def read_did(sock, parameter):
    service = parameter["service"]
    did = parameter["did"]

    request = bytes([
        service,
        (did >> 8) & 0xFF,
        did & 0xFF
    ])

    sock.send(request)

    return sock.recv(4095)


def select_vehicle():
    vehicles = get_vehicles()

    print("\nVerfügbare Fahrzeuge:\n")

    for vehicle in vehicles:
        print(
            f"{vehicle['id']}: "
            f"{vehicle['manufacturer']} "
            f"{vehicle['model']} "
            f"{vehicle['generation'] or ''}"
        )

    while True:
        try:
            vehicle_id = int(
                input("\nFahrzeug-ID auswählen: ")
            )
        except ValueError:
            continue

        for vehicle in vehicles:
            if vehicle["id"] == vehicle_id:
                return vehicle

        print("Ungültige Fahrzeug-ID.")


def select_parameter(vehicle_id):
    parameters = get_parameters(vehicle_id)

    print("\nVerfügbare Diagnoseparameter:\n")

    for index, parameter in enumerate(
        parameters,
        start=1
    ):
        print(
            f"{index}: "
            f"{parameter['name']} "
            f"(DID 0x{parameter['did']:04X})"
        )

    while True:
        try:
            selection = int(
                input(
                    "\nDiagnoseparameter auswählen: "
                )
            )
        except ValueError:
            continue

        if 1 <= selection <= len(parameters):
            return parameters[selection - 1]

        print("Ungültige Auswahl.")


def format_values(values):
    output = []

    for name, item in values.items():
        value = item["value"]
        unit = item["unit"]

        if isinstance(value, float):
            if not unit and value.is_integer():
                value_text = str(int(value))
            else:
                value_text = f"{value:.2f}"
        else:
            value_text = str(value)

        if unit:
            output.append(
                f"{name}: {value_text} {unit}"
            )
        else:
            output.append(
                f"{name}: {value_text}"
            )

    return " | ".join(output)


def main():
    vehicle = select_vehicle()

    parameter = select_parameter(
        vehicle["id"]
    )

    print("\nAusgewähltes Fahrzeug:")

    print(
        f"{vehicle['manufacturer']} "
        f"{vehicle['model']} "
        f"{vehicle['generation'] or ''}"
    )

    print("\nDiagnosekonfiguration:")

    print(
        f"ECU:              "
        f"{parameter['ecu_name']}"
    )

    print(
        f"Transport:        "
        f"{parameter['transport']}"
    )

    print(
        f"CAN-Kanal:        "
        f"{parameter['channel']}"
    )

    print(
        f"Bitrate:          "
        f"{parameter['bitrate']}"
    )

    print(
        f"Request-ID:       "
        f"0x{parameter['request_id']:X}"
    )

    print(
        f"Response-ID:      "
        f"0x{parameter['response_id']:X}"
    )

    print(
        f"Service:          "
        f"0x{parameter['service']:02X}"
    )

    print(
        f"DID:              "
        f"0x{parameter['did']:04X}"
    )

    configure_can(
        parameter["channel"],
        parameter["bitrate"]
    )

    # Aktuell implementieren wir ISO-TP.
    # Weitere Transportarten können später
    # hier ergänzt werden.
    if parameter["transport"] != "isotp":
        raise NotImplementedError(
            "Transport "
            f"'{parameter['transport']}' "
            "ist noch nicht implementiert."
        )

    sock = create_isotp_socket(
        parameter
    )

    print("\nMessung läuft...\n")

    try:
        while True:
            start = time.monotonic()

            try:
                response = read_did(
                    sock,
                    parameter
                )

                # Negative UDS Response
                if (
                    len(response) >= 3
                    and response[0] == 0x7F
                ):
                    print(
                        "Negative UDS-Antwort:",
                        response.hex(" ")
                    )

                else:
                    expected_header = bytes([
                        parameter["service"] + 0x40,
                        (
                            parameter["did"] >> 8
                        ) & 0xFF,
                        parameter["did"] & 0xFF
                    ])

                    if response.startswith(
                        expected_header
                    ):
                        values = decode_parameter(
                            response,
                            parameter
                        )

                        print(
                            format_values(values)
                        )

                    else:
                        print(
                            "Unerwartete Antwort:",
                            response.hex(" ")
                        )

            except socket.timeout:
                print("Keine Antwort")

            elapsed = (
                time.monotonic() - start
            )

            time.sleep(
                max(
                    0,
                    INTERVAL - elapsed
                )
            )

    except KeyboardInterrupt:
        print("\nMessung beendet")

    finally:
        sock.close()


if __name__ == "__main__":
    main()