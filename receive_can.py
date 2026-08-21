import can

bus = can.Bus(
    interface="socketcan",
    channel="vcan0"
)

print("Waiting for CAN message...")

message = bus.recv()

print("Message received:")
print(f"CAN ID: 0x{message.arbitration_id:X}")
print(f"Data: {message.data.hex(' ')}")