from .device import RadestDevice


class RadEstClient:

    def __init__(
        self,
        ip_address="192.168.0.10",
        port=2101
    ):
        self.device = RadestDevice(
            ip_address=ip_address,
            port=port
        )

        self.connected = False


    def connect(self):
        self.connected = self.device.connect()

        if not self.connected:
            raise ConnectionError(
                "Verbindung zum RadEsT fehlgeschlagen"
            )

        return True


    def disconnect(self):
        if self.connected:
            self.device.disconnect()
            self.connected = False


    def _check_connection(self):
        if not self.connected:
            raise RuntimeError(
                "RadEsT ist nicht verbunden"
            )


    def set_distance(self, distance_m):
        self._check_connection()

        return self.device.target_set_distance(
            distance_m
        )


    def get_distance(self):
        self._check_connection()

        return self.device.target_get_distance()


    def set_velocity(
        self,
        velocity_kmh,
        towards=True
    ):
        self._check_connection()

        return self.device.set_velocity_to_value(
            abs(velocity_kmh),
            towards
        )


    def set_rcs(self, rcs_dbsm):
        self._check_connection()

        return self.device.target_set_rcs(
            rcs_dbsm
        )