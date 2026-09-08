import socket
import struct
import subprocess

from database.database import (
    get_parameters,
    get_dtc_configs,
    get_identification_parameters,
)
from decoder import decode_parameter


# ==================================================
# Linux ISO-TP Konstanten
# ==================================================

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

    def __init__(
        self,
        vehicle_id
    ):

        self.vehicle_id = vehicle_id


        # ==================================================
        # Normale Diagnoseparameter
        # ==================================================

        self.parameters = get_parameters(
            vehicle_id
        )


        if not self.parameters:

            raise ValueError(
                f"Keine Diagnoseparameter für "
                f"Fahrzeug {vehicle_id} gefunden"
            )


        # ==================================================
        # DTC-Konfiguration
        #
        # Darf leer sein.
        # Fahrzeug kann also auch ohne DTC-Konfiguration
        # weiterhin normal funktionieren.
        # ==================================================

        self.dtc_configs = get_dtc_configs(
            vehicle_id
        )

        self.identification_parameters = (
            get_identification_parameters(
                vehicle_id
            )
        )


        # ==================================================
        # ISO-TP Sockets
        # ==================================================

        self.sockets = {}


        # ==================================================
        # Signal -> Parameter Zuordnung
        # ==================================================

        self.signal_map = {}


        self._build_signal_map()


    # ==================================================
    # SIGNAL MAP AUFBAUEN
    # ==================================================

    def _build_signal_map(self):

        for parameter in self.parameters:

            fields = parameter.get(
                "fields",
                []
            )


            for field in fields:

                signal_name = field[
                    "name"
                ]


                # ------------------------------------------
                # Ein standardisierter Signalname darf
                # innerhalb eines Fahrzeugs nur einmal
                # definiert sein.
                # ------------------------------------------

                if signal_name in self.signal_map:

                    raise ValueError(
                        f"Signal '{signal_name}' "
                        f"ist für Fahrzeug "
                        f"{self.vehicle_id} "
                        f"mehrfach definiert"
                    )


                self.signal_map[
                    signal_name
                ] = parameter


    # ==================================================
    # VERBINDEN
    # ==================================================

    def connect(self):

        configured_channels = {}


        # --------------------------------------------------
        # Für den Verbindungsaufbau berücksichtigen wir
        # sowohl normale Diagnoseparameter als auch
        # DTC-Konfigurationen.
        #
        # Wenn beide dieselben CAN-IDs verwenden,
        # wird trotzdem nur EIN ISO-TP-Socket erzeugt.
        # --------------------------------------------------

        configs = (
            self.parameters
            + self.dtc_configs
            + self.identification_parameters
        )


        for config in configs:

            channel = config[
                "channel"
            ]

            bitrate = config[
                "bitrate"
            ]


            # ==============================================
            # CAN-Kanal konfigurieren
            # ==============================================

            if channel not in configured_channels:

                self._configure_can(
                    channel,
                    bitrate
                )


                configured_channels[
                    channel
                ] = bitrate


            else:

                # ------------------------------------------
                # Gleicher CAN-Kanal darf nicht mit
                # verschiedenen Bitraten definiert sein.
                # ------------------------------------------

                if (
                    configured_channels[
                        channel
                    ]
                    != bitrate
                ):

                    raise ValueError(
                        f"Unterschiedliche Bitraten "
                        f"für CAN-Kanal "
                        f"'{channel}' definiert"
                    )


            # ==============================================
            # Transport prüfen
            # ==============================================

            if config[
                "transport"
            ] != "isotp":

                raise NotImplementedError(
                    f"Transport "
                    f"'{config['transport']}' "
                    f"wird aktuell nicht unterstützt"
                )


            # ==============================================
            # Socket-Key
            # ==============================================

            socket_key = (
                self._get_socket_key(
                    config
                )
            )


            # ==============================================
            # Socket nur einmal erzeugen
            # ==============================================

            if socket_key not in self.sockets:

                self.sockets[
                    socket_key
                ] = (
                    self._create_isotp_socket(
                        config
                    )
                )


    # ==================================================
    # TRENNEN
    # ==================================================

    def disconnect(self):

        for sock in self.sockets.values():

            try:

                sock.close()

            except Exception:

                pass


        self.sockets.clear()


    # ==================================================
    # CAN-KANAL KONFIGURIEREN
    # ==================================================

    def _configure_can(
        self,
        channel,
        bitrate
    ):

        # --------------------------------------------------
        # CAN zunächst herunterfahren.
        #
        # check=False:
        # Wenn das Interface bereits down ist,
        # soll das nicht sofort abbrechen.
        # --------------------------------------------------

        subprocess.run(
            [
                "sudo",
                "ip",
                "link",
                "set",
                channel,
                "down",
            ],
            check=False
        )


        # --------------------------------------------------
        # Bitrate setzen
        # --------------------------------------------------

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
                str(bitrate),
            ],
            check=True
        )


        # --------------------------------------------------
        # CAN aktivieren
        # --------------------------------------------------

        subprocess.run(
            [
                "sudo",
                "ip",
                "link",
                "set",
                channel,
                "up",
            ],
            check=True
        )


    # ==================================================
    # SOCKET KEY
    # ==================================================

    def _get_socket_key(
        self,
        config
    ):

        return (
            config[
                "channel"
            ],
            config[
                "request_id"
            ],
            config[
                "response_id"
            ],
        )


    # ==================================================
    # ISO-TP SOCKET ERZEUGEN
    # ==================================================

    def _create_isotp_socket(
        self,
        config
    ):

        sock = socket.socket(
            socket.AF_CAN,
            socket.SOCK_DGRAM,
            socket.CAN_ISOTP
        )


        # --------------------------------------------------
        # TX Padding
        #
        # Relevant z. B. für Mercedes:
        # UDS Request muss auf 8 Byte mit 0x00
        # aufgefüllt werden.
        # --------------------------------------------------

        tx_padding = config.get(
            "tx_padding"
        )


        if tx_padding is not None:

            options = struct.pack(
                "=IIBBBB",

                # flags
                CAN_ISOTP_TX_PADDING,

                # frame_txtime
                0,

                # ext_address
                0,

                # txpad_content
                int(tx_padding),

                # rxpad_content
                0,

                # rx_ext_address
                0,
            )


            sock.setsockopt(
                SOL_CAN_ISOTP,
                CAN_ISOTP_OPTS,
                options
            )


        # --------------------------------------------------
        # Timeout für Diagnoseantwort
        # --------------------------------------------------

        sock.settimeout(
            0.5
        )


        # --------------------------------------------------
        # ISO-TP Binding
        #
        # Linux erwartet:
        #
        # (Interface, RX-ID, TX-ID)
        #
        # response_id = RX
        # request_id  = TX
        # --------------------------------------------------

        sock.bind(
            (
                config[
                    "channel"
                ],

                config[
                    "response_id"
                ],

                config[
                    "request_id"
                ],
            )
        )


        return sock


    # ==================================================
    # NORMALEN DIAGNOSEPARAMETER LESEN
    # ==================================================

    def _read_parameter(
        self,
        parameter,
        include_raw_response=False
    ):

        service = parameter[
            "service"
        ]

        did = parameter[
            "did"
        ]


        # --------------------------------------------------
        # Request:
        #
        # Service
        # DID High Byte
        # DID Low Byte
        #
        # z. B.
        #
        # 22 02 01
        # --------------------------------------------------

        request = bytes(
            [
                service,

                (
                    did >> 8
                ) & 0xFF,

                did & 0xFF,
            ]
        )


        socket_key = (
            self._get_socket_key(
                parameter
            )
        )


        sock = self.sockets.get(
            socket_key
        )


        if sock is None:

            raise RuntimeError(
                f"Kein Diagnose-Socket für "
                f"Parameter "
                f"'{parameter.get('name')}' "
                f"vorhanden"
            )


        # --------------------------------------------------
        # Request senden
        # --------------------------------------------------

        sock.send(
            request
        )


        # --------------------------------------------------
        # Antwort lesen
        # --------------------------------------------------

        response = sock.recv(
            4095
        )


        if not response:

            raise TimeoutError(
                f"Keine Antwort auf "
                f"Service 0x{service:02X}, "
                f"DID 0x{did:04X}"
            )


        # ==================================================
        # Negative UDS Response
        # ==================================================

        if response[0] == 0x7F:

            if len(response) >= 3:

                raise RuntimeError(
                    f"Negative UDS-Antwort "
                    f"auf Service "
                    f"0x{service:02X}: "
                    f"NRC 0x{response[2]:02X}"
                )


            raise RuntimeError(
                "Ungültige negative UDS-Antwort"
            )


        # ==================================================
        # Positive Response prüfen
        # ==================================================

        expected_service = (
            service + 0x40
        ) & 0xFF


        if response[0] != expected_service:

            raise RuntimeError(
                f"Unerwartete UDS-Antwort: "
                f"0x{response[0]:02X}, "
                f"erwartet "
                f"0x{expected_service:02X}"
            )


        # --------------------------------------------------
        # Bei DID-Reads müssen mindestens
        #
        # Service + DID High + DID Low
        #
        # vorhanden sein.
        # --------------------------------------------------

        if len(response) < 3:

            raise RuntimeError(
                "UDS-Antwort ist zu kurz"
            )


        response_did = (
            response[1] << 8
        ) | response[2]


        if response_did != did:

            raise RuntimeError(
                f"Falsche DID in Antwort: "
                f"0x{response_did:04X}, "
                f"erwartet "
                f"0x{did:04X}"
            )


        # ==================================================
        # Vorhandenen Decoder verwenden
        # ==================================================

        decoded_values = decode_parameter(
            response,
            parameter
        )

        if include_raw_response:
            return decoded_values, response

        return decoded_values


    # ==================================================
    # MEHRERE SIGNALE LESEN
    # ==================================================

    def read_signals(
        self,
        signal_names,
        ignore_missing=False
    ):

        # --------------------------------------------------
        # Signale zunächst nach Diagnoseparameter gruppieren.
        #
        # Dadurch wird z. B. beim Mercedes der DID 0x0201
        # nur EINMAL gelesen, obwohl darin distance,
        # angle, speed usw. stecken.
        # --------------------------------------------------

        grouped_parameters = {}


        for signal_name in signal_names:

            parameter = self.signal_map.get(
                signal_name
            )


            if parameter is None:

                if ignore_missing:
                    continue


                raise KeyError(
                    f"Signal "
                    f"'{signal_name}' "
                    f"ist für Fahrzeug "
                    f"{self.vehicle_id} "
                    f"nicht definiert"
                )


            parameter_id = parameter[
                "id"
            ]


            if parameter_id not in grouped_parameters:

                grouped_parameters[
                    parameter_id
                ] = {
                    "parameter":
                        parameter,

                    "signals":
                        [],
                }


            grouped_parameters[
                parameter_id
            ][
                "signals"
            ].append(
                signal_name
            )


        results = {}


        # ==================================================
        # Jeden benötigten DID genau einmal lesen
        # ==================================================

        for group in grouped_parameters.values():

            parameter = group[
                "parameter"
            ]


            decoded_values = (
                self._read_parameter(
                    parameter
                )
            )


            # --------------------------------------------------
            # Nur die angeforderten Signale übernehmen.
            # --------------------------------------------------

            for signal_name in group[
                "signals"
            ]:

                if signal_name not in decoded_values:

                    raise KeyError(
                        f"Signal "
                        f"'{signal_name}' "
                        f"wurde aus Parameter "
                        f"'{parameter.get('name')}' "
                        f"nicht dekodiert"
                    )


                results[
                    signal_name
                ] = decoded_values[
                    signal_name
                ]


        return results


    # ==================================================
    # EIN SIGNAL LESEN
    # ==================================================

    def read_signal(
        self,
        signal_name
    ):

        result = self.read_signals(
            [
                signal_name
            ]
        )


        return result[
            signal_name
        ]


    # ==================================================
    # VERFÜGBARE SIGNALE
    # ==================================================

    def get_available_signals(self):

        return list(
            self.signal_map.keys()
        )


    # ==================================================
    # STEUERGERÄTE-IDENTIFIKATION LESEN
    # ==================================================

    def read_identification(self):

        results = []

        for parameter in self.identification_parameters:

            result = {
                "parameter_id": parameter["id"],
                "key": parameter["identifier_key"],
                "label": parameter["label"],
                "ecu_id": parameter["ecu_id"],
                "ecu_name": parameter["ecu_name"],
                "service": f"0x{parameter['service']:02X}",
                "did": f"0x{parameter['did']:04X}",
                "data_type": parameter["data_type"],
                "required": bool(parameter["required"]),
                "accepted_values": parameter["accepted_values"],
                "read_status": "ok",
                "value": None,
                "raw_response": None,
                "error_message": None,
            }

            try:

                decoded_values, response = (
                    self._read_parameter(
                        parameter,
                        include_raw_response=True
                    )
                )

                result["value"] = decoded_values[
                    "identification_value"
                ]["value"]

                result["raw_response"] = (
                    response.hex().upper()
                )

            except Exception as error:

                result["read_status"] = "read_error"
                result["error_message"] = str(error)

            results.append(result)

        return results


    # ==================================================
    # FEHLERSPEICHER LESEN
    # ==================================================

    def read_dtcs(self):

        # --------------------------------------------------
        # Fahrzeug ohne DTC-Konfiguration:
        # einfach leere Liste zurückgeben.
        # --------------------------------------------------

        if not self.dtc_configs:

            return []


        results = []


        # ==================================================
        # Jede konfigurierte ECU abfragen
        # ==================================================

        for config in self.dtc_configs:

            service = config[
                "service"
            ]

            subfunction = config[
                "subfunction"
            ]

            status_mask = config[
                "status_mask"
            ]


            # --------------------------------------------------
            # DTC Request
            #
            # z. B. Mercedes:
            #
            # 19 02 0D
            # --------------------------------------------------

            request = bytes(
                [
                    service,
                    subfunction,
                    status_mask,
                ]
            )


            socket_key = (
                self._get_socket_key(
                    config
                )
            )


            sock = self.sockets.get(
                socket_key
            )


            if sock is None:

                raise RuntimeError(
                    f"Kein Diagnose-Socket für "
                    f"ECU "
                    f"'{config['ecu_name']}' "
                    f"vorhanden"
                )


            # ==================================================
            # Request senden
            # ==================================================

            sock.send(
                request
            )


            # ==================================================
            # Antwort lesen
            # ==================================================

            response = sock.recv(
                4095
            )


            if not response:

                raise TimeoutError(
                    f"Keine DTC-Antwort von "
                    f"ECU "
                    f"'{config['ecu_name']}'"
                )


            # ==================================================
            # Negative UDS Response
            # ==================================================

            if response[0] == 0x7F:

                if len(response) >= 3:

                    raise RuntimeError(
                        f"Negative UDS-Antwort "
                        f"auf Service "
                        f"0x{service:02X}: "
                        f"NRC "
                        f"0x{response[2]:02X}"
                    )


                raise RuntimeError(
                    "Ungültige negative "
                    "UDS-Antwort"
                )


            # ==================================================
            # Positive Response prüfen
            #
            # 0x19 -> 0x59
            # ==================================================

            expected_service = (
                service + 0x40
            ) & 0xFF


            if response[0] != expected_service:

                raise RuntimeError(
                    f"Unerwartete DTC-Antwort "
                    f"von ECU "
                    f"'{config['ecu_name']}': "
                    f"0x{response[0]:02X}"
                )


            # --------------------------------------------------
            # Mindestens:
            #
            # 59
            # Subfunction
            # DTCStatusAvailabilityMask
            # --------------------------------------------------

            if len(response) < 3:

                raise RuntimeError(
                    "DTC-Antwort ist zu kurz"
                )


            # ==================================================
            # Subfunction prüfen
            # ==================================================

            if response[1] != subfunction:

                raise RuntimeError(
                    f"Unerwartete "
                    f"DTC-Subfunction: "
                    f"0x{response[1]:02X}, "
                    f"erwartet "
                    f"0x{subfunction:02X}"
                )


            # ==================================================
            # DTCStatusAvailabilityMask
            # ==================================================

            status_availability_mask = (
                response[2]
            )


            # ==================================================
            # DTC-Daten
            #
            # Ab Byte 3:
            #
            # DTC Byte 1
            # DTC Byte 2
            # DTC Byte 3
            # DTC Status
            #
            # also 4 Byte je Eintrag.
            # ==================================================

            dtc_data = response[
                3:
            ]


            if len(dtc_data) % 4 != 0:

                raise RuntimeError(
                    f"Ungültige Länge der "
                    f"DTC-Daten von ECU "
                    f"'{config['ecu_name']}': "
                    f"{len(dtc_data)} Byte"
                )


            dtcs = []


            # ==================================================
            # DTCs parsen
            # ==================================================

            for index in range(
                0,
                len(dtc_data),
                4
            ):

                dtc_bytes = (
                    dtc_data[
                        index:index + 3
                    ]
                )


                status = (
                    dtc_data[
                        index + 3
                    ]
                )


                # ----------------------------------------------
                # Drei DTC-Bytes als Hex darstellen
                #
                # C3 00 00
                # ->
                # C30000
                # ----------------------------------------------

                dtc_code = (
                    dtc_bytes
                    .hex()
                    .upper()
                )


                dtcs.append(
                    {
                        "code":
                            dtc_code,

                        "status":
                            f"0x{status:02X}",
                    }
                )


            # ==================================================
            # Ergebnis dieser ECU
            # ==================================================

            results.append(
                {
                    "ecu_id":
                        config[
                            "ecu_id"
                        ],

                    "ecu_name":
                        config[
                            "ecu_name"
                        ],

                    "service":
                        f"0x{service:02X}",

                    "subfunction":
                        f"0x{subfunction:02X}",

                    "status_mask":
                        f"0x{status_mask:02X}",

                    "status_availability_mask":
                        (
                            f"0x"
                            f"{status_availability_mask:02X}"
                        ),

                    "dtcs":
                        dtcs,
                }
            )


        return results
