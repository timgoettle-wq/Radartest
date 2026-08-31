from diagnostics.vehicle import VehicleDiagnostic
from radest.device import RadestDevice


class TestController:

    def __init__(
        self,
        vehicle_id,
        radest_ip="192.168.0.10",
        radest_port=2101
    ):
        # Fahrzeug
        self.vehicle_id = vehicle_id

        self.vehicle = VehicleDiagnostic(
            vehicle_id=vehicle_id
        )

        # RadEsT
        self.radest = RadestDevice(
            ip_address=radest_ip,
            port=radest_port
        )

        # Status
        self.connected = False
        self.precheck_done = False
        self.static_test_active = False

        # Precheck-Ergebnisse
        self.polarization = None
        self.frequency_range = None
        self.power = None

        # Statische Messung
        self.requested_distance = None
        self.radest_distance = None


    # --------------------------------------------------
    # Verbindung
    # --------------------------------------------------

    def connect(self):
        """
        Fahrzeugdiagnose und RadEsT verbinden.
        """

        if self.connected:
            return

        self.vehicle.connect()

        try:
            radest_connected = self.radest.connect()

            if not radest_connected:
                raise ConnectionError(
                    "Verbindung zum RadEsT fehlgeschlagen"
                )

        except Exception:
            self.vehicle.disconnect()
            raise

        self.connected = True


    def disconnect(self):
        """
        Fahrzeugdiagnose und RadEsT trennen.
        """

        self.static_test_active = False

        self.vehicle.disconnect()

        if self.connected:
            try:
                self.radest.disconnect()
            except Exception:
                pass

        self.connected = False


    # --------------------------------------------------
    # RadEsT Precheck
    # --------------------------------------------------

    def run_precheck(self):
        """
        Führt den RadEsT-Precheck durch:

        1. Polarisation bestimmen
        2. Frequenzbereich bestimmen
        3. Leistung messen

        Aktuell noch ohne Grenzwertbewertung.
        """

        self._check_connection()

        self.precheck_done = False

        # 1. Polarisation
        self.polarization = (
            self.radest.measure_get_polarization_77ghz()
        )

        # 2. Frequenzbereich
        self.frequency_range = (
            self.radest.measure_get_frequencyrange()
        )

        # 3. Leistung
        self.power = (
            self.radest.measure_get_77ghz_eirp()
        )

        self.precheck_done = True

        return {
            "polarization": self.polarization,
            "frequency_range": self.frequency_range,
            "power": self.power
        }


    # --------------------------------------------------
    # Statische Messung starten
    # --------------------------------------------------

    def start_static_measurement(
        self,
        distance_m
    ):
        """
        Stellt die gewünschte Distanz am RadEsT ein
        und liest die tatsächlich realisierte Distanz zurück.
        """

        self._check_connection()

        if not self.precheck_done:
            raise RuntimeError(
                "Vor der statischen Messung muss "
                "der Precheck durchgeführt werden"
            )

        self.requested_distance = float(
            distance_m
        )

        # Sollwert setzen
        self.radest.target_set_distance(
            self.requested_distance
        )

        # Tatsächlich realisierten Wert lesen
        self.radest_distance = (
            self.radest.target_get_distance()
        )

        self.static_test_active = True

        return {
            "requested_distance":
                self.requested_distance,

            "radest_distance":
                self.radest_distance
        }


    # --------------------------------------------------
    # Aktuellen Messwert lesen
    # --------------------------------------------------

    def read_static_measurement(self):
        """
        Liest einen aktuellen Messpunkt vom Fahrzeug.

        Es werden nur Signale abgefragt, die das
        ausgewählte Fahrzeug tatsächlich unterstützt.
        """

        self._check_connection()

        if not self.static_test_active:
            raise RuntimeError(
                "Statische Messung wurde noch nicht gestartet"
            )

        available_signals = (
            self.vehicle.get_available_signals()
        )

        wanted_signals = [
            "distance",
            "angle",
            "relative_speed",
            "relative_acceleration"
        ]

        signals_to_read = [
            signal
            for signal in wanted_signals
            if signal in available_signals
        ]

        if "distance" not in signals_to_read:
            raise RuntimeError(
                "Für dieses Fahrzeug ist kein "
                "'distance'-Signal definiert"
            )

        vehicle_values = (
            self.vehicle.read_signals(
                signals_to_read
            )
        )

        vehicle_distance = (
            vehicle_values[
                "distance"
            ]["value"]
        )

        distance_error = (
            vehicle_distance
            - self.radest_distance
        )

        return {
            "requested_distance":
                self.requested_distance,

            "radest_distance":
                self.radest_distance,

            "vehicle":
                vehicle_values,

            "distance_error":
                distance_error
        }


    # --------------------------------------------------
    # Statusinformationen
    # --------------------------------------------------

    def get_available_signals(self):
        return (
            self.vehicle.get_available_signals()
        )


    def get_precheck_result(self):
        return {
            "polarization": self.polarization,
            "frequency_range": self.frequency_range,
            "power": self.power,
            "done": self.precheck_done
        }


    # --------------------------------------------------
    # Intern
    # --------------------------------------------------

    def _check_connection(self):
        if not self.connected:
            raise RuntimeError(
                "Testsystem ist nicht verbunden"
            )