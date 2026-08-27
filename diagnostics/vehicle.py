import socket
import struct
import subprocess

from database.database import get_parameters
from decoder import decode_parameter


# Linux ISO-TP Konstanten
SOL_CAN_ISOTP = getattr(
    socket,
    "SOL_CAN_ISOTP",
    106
)

CAN_ISOTP_OPTS = getattr(
    socket,
    "CAN_ISOTP_OPTS",
    1
)

CAN_ISOTP_TX_PADDING = getattr(
    socket,
    "CAN_ISOTP_TX_PADDING",
    0x0004
)


class VehicleDiagnostic:

    def __init__(self, vehicle_id):
        self.vehicle_id = vehicle_id

        # Alle Diagnoseparameter des Fahrzeugs laden
        self.parameters = get_parameters(vehicle_id)

        if not self.parameters:
            raise ValueError(
                f"Keine Diagnoseparameter für "
                f"vehicle_id={vehicle_id} gefunden"
            )

        # ISO-TP-Sockets
        # Key:
        # (channel, request_id, response_id)
        self.sockets = {}

        # Zuordnung:
        # Signalname -> Diagnoseparameter
        #
        # Beispiel Mercedes:
        # distance       -> DID 0x0201
        # angle          -> DID 0x0201
        # relative_speed -> DID 0x0201
        #
        # Beispiel anderes Fahrzeug:
        # distance       -> DID A
        # angle          -> DID B
        # relative_speed -> DID C
        self.signal_map = {}

        self._build_signal_map()


    def _build_signal_map(self):
        for parameter in self.parameters:

            for field in parameter["fields"]:

                signal_name = field["name"]

                if signal_name in self.signal_map:
                    raise ValueError(
                        f"Signal '{signal_name}' ist "
                        f"für vehicle_id={self.vehicle_id} "
                        f"mehrfach definiert"
                    )

                self.signal_map[
                    signal_name
                ] = parameter


    def connect(self):
        """
        CAN konfigurieren und benötigte
        ISO-TP-Sockets öffnen.
        """

        configured_channels = {}

        for parameter in self.parameters:

            channel = parameter["channel"]
            bitrate = parameter["bitrate"]

            # Prüfen, ob derselbe CAN-Kanal bereits
            # mit einer anderen Bitrate verwendet wird
            if channel in configured_channels:

                if configured_channels[channel] != bitrate:
                    raise ValueError(
                        f"CAN-Kanal '{channel}' hat "
                        f"unterschiedliche Bitraten in "
                        f"der Datenbank"
                    )

            else:
                self._configure_can(
                    channel,
                    bitrate
                )

                configured_channels[
                    channel
                ] = bitrate

            transport = parameter["transport"]

            if transport != "isotp":
                raise NotImplementedError(
                    f"Transport '{transport}' "
                    f"wird aktuell nicht unterstützt"
                )

            socket_key = self._get_socket_key(
                parameter
            )

            # Mehrere DIDs eines Steuergeräts
            # verwenden denselben ISO-TP-Socket
            if socket_key not in self.sockets:

                self.sockets[
                    socket_key
                ] = self._create_isotp_socket(
                    parameter
                )


    def disconnect(self):
        """
        Alle geöffneten ISO-TP-Sockets schließen.
        """

        for sock in self.sockets.values():

            try:
                sock.close()
            except Exception:
                pass

        self.sockets.clear()


    def _configure_can(
        self,
        channel,
        bitrate
    ):
        """
        SocketCAN Interface konfigurieren.
        """

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


    def _get_socket_key(
        self,
        parameter
    ):
        """
        Eindeutige Verbindung zu einem ECU.

        Verschiedene DIDs mit denselben CAN-IDs
        teilen sich einen ISO-TP-Socket.
        """

        return (
            parameter["channel"],
            parameter["request_id"],
            parameter["response_id"]
        )


    def _create_isotp_socket(
        self,
        parameter
    ):
        """
        Linux ISO-TP-Socket erzeugen.
        """

        sock = socket.socket(
            socket.AF_CAN,
            socket.SOCK_DGRAM,
            socket.CAN_ISOTP
        )

        padding = parameter["tx_padding"]

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
            parameter["channel"],
            parameter["response_id"],
            parameter["request_id"]
        ))

        return sock


    def _read_parameter(
        self,
        parameter
    ):
        """
        Einen einzelnen Diagnoseparameter /
        eine einzelne DID lesen und dekodieren.
        """

        socket_key = self._get_socket_key(
            parameter
        )

        if socket_key not in self.sockets:
            raise RuntimeError(
                "Fahrzeugdiagnose ist nicht verbunden"
            )

        sock = self.sockets[
            socket_key
        ]

        service = parameter["service"]
        did = parameter["did"]

        # Beispiel:
        #
        # service = 0x22
        # did     = 0x0201
        #
        # Request:
        # 22 02 01

        request = bytes([
            service,
            (did >> 8) & 0xFF,
            did & 0xFF
        ])

        sock.send(request)

        response = sock.recv(4095)

        # Negative UDS Response:
        # 7F Service NRC
        if (
            len(response) >= 3
            and response[0] == 0x7F
        ):
            raise RuntimeError(
                f"Negative UDS-Antwort bei "
                f"DID 0x{did:04X}: "
                + response.hex(" ")
            )

        # Positive Response bei UDS:
        #
        # 22 -> 62
        expected = bytes([
            service + 0x40,
            (did >> 8) & 0xFF,
            did & 0xFF
        ])

        if not response.startswith(expected):
            raise RuntimeError(
                f"Unerwartete UDS-Antwort bei "
                f"DID 0x{did:04X}: "
                + response.hex(" ")
            )

        return decode_parameter(
            response,
            parameter
        )


    def read_signals(
        self,
        signal_names,
        ignore_missing=False
    ):
        """
        Beliebige standardisierte Signale lesen.

        Beispiel:

        read_signals([
            "distance",
            "angle",
            "relative_speed"
        ])

        Es spielt keine Rolle, ob diese Signale
        aus einer DID oder aus mehreren DIDs kommen.
        """

        result = {}

        # Parameter zusammenfassen, damit eine DID
        # nicht mehrfach gelesen wird.
        parameters_to_read = {}

        for signal_name in signal_names:

            parameter = self.signal_map.get(
                signal_name
            )

            if parameter is None:

                if ignore_missing:
                    continue

                raise ValueError(
                    f"Signal '{signal_name}' ist "
                    f"für vehicle_id={self.vehicle_id} "
                    f"nicht definiert"
                )

            # diagnostic_parameters.id verwenden
            parameter_id = parameter["id"]

            if parameter_id not in parameters_to_read:

                parameters_to_read[
                    parameter_id
                ] = {
                    "parameter": parameter,
                    "signals": []
                }

            parameters_to_read[
                parameter_id
            ]["signals"].append(
                signal_name
            )

        # Jede benötigte DID genau einmal lesen
        for item in parameters_to_read.values():

            parameter = item[
                "parameter"
            ]

            decoded = self._read_parameter(
                parameter
            )

            for signal_name in item[
                "signals"
            ]:

                if signal_name not in decoded:
                    raise RuntimeError(
                        f"Signal '{signal_name}' "
                        f"wurde von DID "
                        f"0x{parameter['did']:04X} "
                        f"nicht dekodiert"
                    )

                result[
                    signal_name
                ] = decoded[
                    signal_name
                ]

        return result


    def read_signal(
        self,
        signal_name
    ):
        """
        Convenience-Funktion für ein einzelnes Signal.

        Beispiel:
        vehicle.read_signal("distance")
        """

        values = self.read_signals([
            signal_name
        ])

        return values[
            signal_name
        ]


    def get_available_signals(self):
        """
        Liefert die für dieses Fahrzeug
        verfügbaren standardisierten Signale.
        """

        return list(
            self.signal_map.keys()
        )