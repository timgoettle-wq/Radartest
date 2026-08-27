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


    def set_distance(self, distance_m):
        if not self.connected:
            raise RuntimeError(
                "Testsystem nicht verbunden"
            )

        self.requested_distance = distance_m

        self.radest.target_set_distance(
            distance_m
        )

        # tatsächlich realisierten Wert holen
        self.realized_distance = (
            self.radest.target_get_distance()
        )

        return self.realized_distance


    def set_rcs(self, rcs_dbsm):
        if not self.connected:
            raise RuntimeError(
                "Testsystem nicht verbunden"
            )

        self.radest.target_set_rcs(
            rcs_dbsm
        )


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