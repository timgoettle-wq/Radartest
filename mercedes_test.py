import can
import time

REQUEST_ID = 0x741
RESPONSE_ID = 0x721

bus = can.Bus(
    interface="socketcan",
    channel="can0",
    can_filters=[
        {
            "can_id": RESPONSE_ID,
            "can_mask": 0x7FF,
            "extended": False
        }
    ]
)

def read_isotp_response(timeout=1.0):
    first = bus.recv(timeout=timeout)

    if first is None:
        return None

    print("RX:", first.data.hex(" "))

    # ISO-TP Single Frame
    if (first.data[0] & 0xF0) == 0x00:
        length = first.data[0] & 0x0F
        return bytes(first.data[1:1 + length])

    # ISO-TP First Frame
    if (first.data[0] & 0xF0) == 0x10:
        total_length = ((first.data[0] & 0x0F) << 8) | first.data[1]

        payload = bytearray(first.data[2:])

        print(f"ISO-TP First Frame, Gesamtlänge: {total_length} Byte")

        # Flow Control senden
        flow_control = can.Message(
            arbitration_id=REQUEST_ID,
            data=[0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
            is_extended_id=False
        )

        bus.send(flow_control)
        print("TX Flow Control:", flow_control.data.hex(" "))

        expected_sequence = 1

        while len(payload) < total_length:
            frame = bus.recv(timeout=timeout)

            if frame is None:
                print("Timeout bei Consecutive Frame")
                return None

            print("RX:", frame.data.hex(" "))

            if (frame.data[0] & 0xF0) != 0x20:
                print("Unerwarteter ISO-TP Frame")
                continue

            sequence = frame.data[0] & 0x0F

            if sequence != expected_sequence:
                print(
                    f"Falsche Sequence Number: "
                    f"{sequence}, erwartet {expected_sequence}"
                )

            payload.extend(frame.data[1:])

            expected_sequence = (expected_sequence + 1) & 0x0F

        return bytes(payload[:total_length])

    print("Unbekannter ISO-TP Frame")
    return None


try:
    while True:

        request = can.Message(
            arbitration_id=REQUEST_ID,
            data=[
                0x03,
                0x22,
                0x02,
                0x01,
                0x00,
                0x00,
                0x00,
                0x00
            ],
            is_extended_id=False
        )

        print("\nSending request...")
        bus.send(request)

        response = read_isotp_response()

        if response is None:
            print("Keine vollständige Antwort")
        else:
            print("Komplette UDS-Antwort:")
            print(response.hex(" "))

        time.sleep(0.5)

except KeyboardInterrupt:
    print("\nStopped")

finally:
    bus.shutdown()