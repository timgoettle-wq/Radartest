import can
import struct
import time

bus = can.Bus(
    interface="socketcan",
    channel="can0"
)

REQUEST_ID = 0x741
RESPONSE_ID = 0x721


while True:

    request = can.Message(
        arbitration_id=REQUEST_ID,
        data=[0x03, 0x22, 0x02, 0x01],
        is_extended_id=False
    )

    bus.send(request)

    while True:
        response = bus.recv(timeout=1.0)

        if response is None:
            print("Keine Antwort")
            break

        if response.arbitration_id == RESPONSE_ID:

            print("RAW:", response.data.hex(" "))

            distance = struct.unpack(
                ">f",
                response.data[4:8]
            )[0]

            print(f"Distance: {distance:.2f} m")

            break

    time.sleep(0.5)