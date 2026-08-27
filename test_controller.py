from diagnostics.vehicle import VehicleDiagnostic
from radest.device import RadestDevice


class TestController:

    def __init__(
        self,
        vehicle_id,
        parameter_name,
        radest_ip="192.168.0.10",
        radest_port=2101
    ):
        self.vehicle = VehicleDiagnostic(
            vehicle_id=vehicle_id,
            parameter_name=parameter_name
        )

        self.radest = RadestDevice(
            ip_address=radest_ip,
            port=radest_port
        )

        self.requested_distance = None
        self.realized_distance = None

        self.connected = False

        self.precheck_done = False
        self.polarization = None
        self.frequency_range = None
        self.power = None


    def connect(self):
        self.vehicle.connect()

        if not self.radest.connect():
            self.vehicle.disconnect()

            raise ConnectionError(
                "Verbindung zum RadEsT fehlgeschlagen"
            )

        self.connected = True


    def disconnect(self):
        self.vehicle.disconnect()

        if self.connected:
            self.radest.disconnect()

        self.connected = False


    def run_precheck(self):
        if not self.connected:
            raise RuntimeError(
                "Testsystem nicht verbunden"
            )

        print("\n--- RadEsT Precheck ---")

        # 1. Polarisation bestimmen
        print("Polarisation wird bestimmt...")

        self.polarization = (
            self.radest.measure_get_polarization_77ghz()
        )

        print(
            f"Erkannte Polarisation: "
            f"{self.polarization}"
        )

        # Erkannte Polarisation direkt einstellen
        self.radest.system_set_polarization_77ghz(
            self.polarization
        )

        print(
            f"Polarisation eingestellt: "
            f"{self.polarization}"
        )

        # 2. Frequenzbereich bestimmen
        print("Frequenzbereich wird bestimmt...")

        self.frequency_range = (
            self.radest.measure_get_frequencyrange()
        )

        print(
            f"Frequenzbereich: "
            f"{self.frequency_range}"
        )

        # 3. Leistung messen
        print("Leistung wird gemessen...")

        self.power = (
            self.radest.measure_get_77ghz_eirp()
        )

        print(
            f"Gemessene Leistung: "
            f"{self.power}"
        )

        self.precheck_done = True

        return {
            "polarization": self.polarization,
            "frequency_range": self.frequency_range,
            "power": self.power
        }


    def set_velocity(
        self,
        velocity_kmh,
        towards=True
    ):
        if not self.connected:
            raise RuntimeError(
                "Testsystem nicht verbunden"
            )

        self.radest.set_velocity_to_value(
            abs(velocity_kmh),
            towards
        )


    def read_once(self):
        if not self.connected:
            raise RuntimeError(
                "Testsystem nicht verbunden"
            )

        vehicle_values = self.vehicle.read()

        result = {
            "requested_distance":
                self.requested_distance,

            "radest_distance":
                self.realized_distance,

            "vehicle":
                vehicle_values
        }

        # Nur vergleichen, wenn dieses Fahrzeug
        # überhaupt einen distance-Wert liefert
        if (
            self.realized_distance is not None
            and "distance" in vehicle_values
        ):
            vehicle_distance = (
                vehicle_values["distance"]["value"]
            )

            result["distance_error"] = (
                vehicle_distance
                - self.realized_distance
            )

        else:
            result["distance_error"] = None

        return result