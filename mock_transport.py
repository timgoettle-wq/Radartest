import struct


class MockTransport:
    def __init__(self):
        self.distance = 5.0
        self.direction = 1

    def request(self, request: bytes) -> bytes:

        # Mindestens Service + DID erforderlich
        if len(request) < 3:
            return bytes([
                0x7F,
                0x00,
                0x13
            ])

        service = request[0]
        did = (request[1] << 8) | request[2]

        # Nur ReadDataByIdentifier unterstützen
        if service != 0x22:
            return bytes([
                0x7F,
                service,
                0x11
            ])

        # Unsere bekannte Radar-DID
        if did == 0x0201:

            status = 1
            relative_speed = 0.0
            angle = -2.5
            relative_acceleration = 0.0

            response = bytes([
                0x62,
                0x02,
                0x01
            ])

            response += struct.pack(
                ">Bffff",
                status,
                self.distance,
                relative_speed,
                angle,
                relative_acceleration
            )

            # Abstand für nächste Messung ändern
            self.distance += 0.5 * self.direction

            if self.distance >= 15.0:
                self.direction = -1

            elif self.distance <= 5.0:
                self.direction = 1

            return response

        # DID nicht unterstützt
        return bytes([
            0x7F,
            0x22,
            0x31
        ])