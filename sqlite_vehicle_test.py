import can
import time
import subprocess

from database.database import (
    get_vehicles,
    get_parameters
)

from decoder import decode_parameter


INTERVAL = 0.5

def select_parameter(vehicle_id):
    parameters = get_parameters(vehicle_id)

    if not parameters:
        raise RuntimeError(
            "Für dieses Fahrzeug sind keine "
            "Diagnoseparameter hinterlegt."
        )

    print()
    print("Verfügbare Diagnoseparameter:")
    print()

    for index, parameter in enumerate(
        parameters,
        start=1
    ):
        print(
            f"{index}: "
            f"{parameter['name']} "
            f"(DID 0x{parameter['did']:04X})"
        )

    print()

    while True:
        try:
            selection = int(
                input("Diagnoseparameter auswählen: ")
            )
        except ValueError:
            print("Bitte eine Zahl eingeben.")
            continue

        if 1 <= selection <= len(parameters):
            return parameters[selection - 1]

        print("Ungültige Auswahl.")

def configure_can(channel, bitrate):
    print(
        f"Konfiguriere {channel} mit {bitrate} bit/s ..."
    )

    subprocess.run(
        ["sudo", "ip", "link", "set", channel, "down"],
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
        ["sudo", "ip", "link", "set", channel, "up"],
        check=True
    )

    print(f"{channel} ist aktiv.")

def build_read_did_request(parameter_config):
    service = parameter_config["service"]
    did = parameter_config["did"]

    did_high = (did >> 8) & 0xFF
    did_low = did & 0xFF

    uds_payload = [
        service,
        did_high,
        did_low
    ]

    # ISO-TP Single Frame
    frame = [
        len(uds_payload),
        *uds_payload
    ]

    # auf 8 Byte auffüllen
    while len(frame) < 8:
        frame.append(0x00)

    return frame


def read_isotp(bus, request_id):
    first = bus.recv(timeout=0.2)

    if first is None:
        return None

    # ISO-TP Single Frame
    if (first.data[0] & 0xF0) == 0x00:
        length = first.data[0] & 0x0F
        return bytes(first.data[1:1 + length])

    # ISO-TP First Frame erwartet
    if (first.data[0] & 0xF0) != 0x10:
        return None

    length = (
        ((first.data[0] & 0x0F) << 8)
        | first.data[1]
    )

    payload = bytearray(
        first.data[2:]
    )

    # Flow Control
    flow_control = can.Message(
        arbitration_id=request_id,
        data=[
            0x30,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00
        ],
        is_extended_id=False
    )

    bus.send(flow_control)

    while len(payload) < length:
        frame = bus.recv(timeout=0.2)

        if frame is None:
            return None

        # Consecutive Frame
        if (frame.data[0] & 0xF0) == 0x20:
            payload.extend(
                frame.data[1:]
            )

    return bytes(
        payload[:length]
    )


def select_vehicle():
    vehicles = get_vehicles()

    if not vehicles:
        raise RuntimeError(
            "Keine Fahrzeuge in der Datenbank."
        )

    print()
    print("Verfügbare Fahrzeuge:")
    print()

    for vehicle in vehicles:
        print(
            f"{vehicle['id']}: "
            f"{vehicle['manufacturer']} "
            f"{vehicle['model']} "
            f"{vehicle['generation'] or ''}"
        )

    print()

    while True:
        try:
            vehicle_id = int(
                input("Fahrzeug-ID auswählen: ")
            )
        except ValueError:
            print("Bitte eine Zahl eingeben.")
            continue

        for vehicle in vehicles:
            if vehicle["id"] == vehicle_id:
                return vehicle

        print("Ungültige Fahrzeug-ID.")


def main():
    vehicle = select_vehicle()

    parameter = select_parameter(
    vehicle["id"]
    )

    if parameter is None:
        raise RuntimeError(
            "Für dieses Fahrzeug wurde kein "
            "'radar_target'-Parameter gefunden."
        )

    request_id = parameter["request_id"]
    response_id = parameter["response_id"]

    request_data = build_read_did_request(
        parameter
    )

    print()
    print("Ausgewähltes Fahrzeug:")
    print(
        f"{vehicle['manufacturer']} "
        f"{vehicle['model']} "
        f"{vehicle['generation'] or ''}"
    )

    print()
    print("Diagnosekonfiguration:")
    print(
        f"CAN-Kanal:        {parameter['channel']}"
    )
    print(
        f"Bitrate:          {parameter['bitrate']}"
    )
    print(
        f"Request-ID:       0x{request_id:X}"
    )
    print(
        f"Response-ID:      0x{response_id:X}"
    )
    print(
        f"Service:          0x{parameter['service']:02X}"
    )
    print(
        f"DID:              0x{parameter['did']:04X}"
    )
    print()

    configure_can(
    channel=parameter["channel"],
    bitrate=parameter["bitrate"]
    )

    bus = can.Bus(
        interface="socketcan",
        channel=parameter["channel"],
        can_filters=[
            {
                "can_id": response_id,
                "can_mask": 0x7FF,
                "extended": False
            }
        ]
    )

    try:
        while True:
            start = time.monotonic()

            request = can.Message(
                arbitration_id=request_id,
                data=request_data,
                is_extended_id=False
            )

            bus.send(request)

            response = read_isotp(
                bus=bus,
                request_id=request_id
            )

            if response is None:
                print("Keine Antwort")
                continue

            expected_header = bytes([
                parameter["service"] + 0x40,
                (parameter["did"] >> 8) & 0xFF,
                parameter["did"] & 0xFF
            ])

            if not response.startswith(
                expected_header
            ):
                print(
                    "Unerwartete Antwort:",
                    response.hex(" ")
                )
                continue

            values = decode_parameter(
                response,
                parameter
            )

            print(
                f"Status: "
                f"{values['status']['value']} | "
                f"Abstand: "
                f"{values['distance']['value']:6.2f} "
                f"{values['distance']['unit']} | "
                f"v_rel: "
                f"{values['relative_speed']['value']:7.2f} "
                f"{values['relative_speed']['unit']} | "
                f"Winkel: "
                f"{values['angle']['value']:7.2f} "
                f"{values['angle']['unit']} | "
                f"a_rel: "
                f"{values['relative_acceleration']['value']:7.2f} "
                f"{values['relative_acceleration']['unit']}"
            )

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
        bus.shutdown()


if __name__ == "__main__":
    main()