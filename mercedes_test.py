import can
import struct
import time

REQUEST_ID = 0x741
RESPONSE_ID = 0x721
INTERVAL = 0.5  # 2 Hz

bus = can.Bus(
    interface="socketcan",
    channel="can0",
    can_filters=[{
        "can_id": RESPONSE_ID,
        "can_mask": 0x7FF,
        "extended": False
    }]
)


def read_isotp():
    first = bus.recv(timeout=0.2)

    if first is None:
        return None

    # First Frame erwartet
    if (first.data[0] & 0xF0) != 0x10:
        return None

    length = ((first.data[0] & 0x0F) << 8) | first.data[1]
    payload = bytearray(first.data[2:])

    # Flow Control
    bus.send(can.Message(
        arbitration_id=REQUEST_ID,
        data=[0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
        is_extended_id=False
    ))

    while len(payload) < length:
        frame = bus.recv(timeout=0.2)

        if frame is None:
            return None

        if (frame.data[0] & 0xF0) == 0x20:
            payload.extend(frame.data[1:])

    return bytes(payload[:length])


try:
    while True:
        start = time.monotonic()

        # UDS: ReadDataByIdentifier 0x0201
        bus.send(can.Message(
            arbitration_id=REQUEST_ID,
            data=[0x03, 0x22, 0x02, 0x01, 0x00, 0x00, 0x00, 0x00],
            is_extended_id=False
        ))

        response = read_isotp()

        if response and response[:3] == bytes([0x62, 0x02, 0x01]):

            status = response[3]

            distance = struct.unpack(">f", response[4:8])[0]
            rel_speed = struct.unpack(">f", response[8:12])[0]
            angle = struct.unpack(">f", response[12:16])[0]
            rel_accel = struct.unpack(">f", response[16:20])[0]

            print(
                f"Status: {status} | "
                f"Abstand: {distance:6.2f} m | "
                f"v_rel: {rel_speed:7.2f} km/h | "
                f"Winkel: {angle:7.2f}° | "
                f"a_rel: {rel_accel:7.2f} m/s²"
            )

        else:
            print("Keine gültige Antwort")

        # exakt ungefähr 2 Hz inklusive Kommunikationszeit
        elapsed = time.monotonic() - start
        time.sleep(max(0, INTERVAL - elapsed))

except KeyboardInterrupt:
    print("\nMessung beendet")

finally:
    bus.shutdown()