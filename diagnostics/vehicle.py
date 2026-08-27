import socket
import struct
import subprocess

from database.database import get_parameter
from decoder import decode_parameter


SOL_CAN_ISOTP = getattr(socket, "SOL_CAN_ISOTP", 106)
CAN_ISOTP_OPTS = getattr(socket, "CAN_ISOTP_OPTS", 1)
CAN_ISOTP_TX_PADDING = getattr(
    socket,
    "CAN_ISOTP_TX_PADDING",
    0x0004
)


class VehicleDiagnostic:

    def __init__(
        self,
        vehicle_id,
        parameter_name
    ):
        self.parameter = get_parameter(
            vehicle_id=vehicle_id,
            parameter_name=parameter_name
        )

        if self.parameter is None:
            raise ValueError(
                f"Parameter '{parameter_name}' "
                "nicht gefunden"
            )

        self.socket = None


    def connect(self):
        self._configure_can()

        if self.parameter["transport"] != "isotp":
            raise NotImplementedError(
                f"Transport "
                f"'{self.parameter['transport']}' "
                "noch nicht unterstützt"
            )

        self.socket = self._create_isotp_socket()


    def disconnect(self):
        if self.socket is not None:
            self.socket.close()
            self.socket = None


    def _configure_can(self):
        channel = self.parameter["channel"]
        bitrate = self.parameter["bitrate"]

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


    def _create_isotp_socket(self):
        sock = socket.socket(
            socket.AF_CAN,
            socket.SOCK_DGRAM,
            socket.CAN_ISOTP
        )

        padding = self.parameter["tx_padding"]

        if padding is not None:
            options = struct.pack(
                "=IIBBBB",
                CAN_ISOTP_TX_PADDING,
                0,
                0,
                padding,
                0,
                0
            )

            sock.setsockopt(
                SOL_CAN_ISOTP,
                CAN_ISOTP_OPTS,
                options
            )

        sock.settimeout(0.5)

        sock.bind((
            self.parameter["channel"],
            self.parameter["response_id"],
            self.parameter["request_id"]
        ))

        return sock


    def read(self):
        if self.socket is None:
            raise RuntimeError(
                "Fahrzeugdiagnose nicht verbunden"
            )

        service = self.parameter["service"]
        did = self.parameter["did"]

        request = bytes([
            service,
            (did >> 8) & 0xFF,
            did & 0xFF
        ])

        self.socket.send(request)

        response = self.socket.recv(4095)

        # Negative UDS Response
        if (
            len(response) >= 3
            and response[0] == 0x7F
        ):
            raise RuntimeError(
                "Negative UDS-Antwort: "
                + response.hex(" ")
            )

        expected = bytes([
            service + 0x40,
            (did >> 8) & 0xFF,
            did & 0xFF
        ])

        if not response.startswith(expected):
            raise RuntimeError(
                "Unerwartete UDS-Antwort: "
                + response.hex(" ")
            )

        return decode_parameter(
            response,
            self.parameter
        )