import can

bus = can.Bus(
    interface="socketcan",
    channel="vcan0"
)

message = can.Message(
    arbitration_id=0x123,
    data=[0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88],
    is_extended_id=False
)

bus.send(message)

print("CAN message sent")