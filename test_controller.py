import copy
import threading
import time

from diagnostics.vehicle import VehicleDiagnostic
from radest.device import RadestDevice
from measurement_logger import MeasurementLogger


class TestController:

    def __init__(
        self,
        vehicle_id,
        radest_ip="192.168.0.10",
        radest_port=2101
    ):

        self.vehicle_id = vehicle_id

        self.vehicle = VehicleDiagnostic(
            vehicle_id=vehicle_id
        )

        self.radest = RadestDevice(
            ip_address=radest_ip,
            port=radest_port
        )


        # ==================================================
        # Allgemeiner Zustand
        # ==================================================

        self.connected = False

        self.precheck_done = False

        self.static_test_active = False


        # ==================================================
        # Precheck
        # ==================================================

        self.polarization = None

        self.frequency_range = None

        self.power = None


        # ==================================================
        # Statische Messung
        # ==================================================

        self.requested_distance = None

        self.radest_distance = None


        # ==================================================
        # Hintergrund-Messloop
        # ==================================================

        self._measurement_thread = None

        self._measurement_stop_event = (
            threading.Event()
        )

        self._measurement_lock = (
            threading.Lock()
        )

        self._measurement_interval_s = 0.2

        self._latest_measurement = None

        self._measurement_error = None

        self._measurement_sequence = 0

        self._measurement_start_ns = None


        # ==================================================
        # Logging
        # ==================================================

        self.measurement_logger = None

        self.logging_active = False


    # ==================================================
    # VERBINDEN
    # ==================================================

    def connect(self):

        if self.connected:
            return


        # --------------------------------------------------
        # Fahrzeug verbinden
        # --------------------------------------------------

        self.vehicle.connect()


        try:

            # ----------------------------------------------
            # RadEsT verbinden
            # ----------------------------------------------

            radest_connected = (
                self.radest.connect()
            )


            if not radest_connected:

                raise ConnectionError(
                    "Verbindung zum RadEsT fehlgeschlagen"
                )


        except Exception:

            # Wenn RadEsT nicht verbunden werden konnte,
            # Fahrzeugverbindung wieder schließen.

            self.vehicle.disconnect()

            raise


        self.connected = True


    # ==================================================
    # TRENNEN
    # ==================================================

    def disconnect(self):

        # --------------------------------------------------
        # Messloop zuerst stoppen
        # --------------------------------------------------

        self.stop_measurement_loop()


        # --------------------------------------------------
        # Logger danach sauber schließen
        # --------------------------------------------------

        self.stop_logging()


        self.static_test_active = False


        # --------------------------------------------------
        # Fahrzeug trennen
        # --------------------------------------------------

        try:

            self.vehicle.disconnect()

        except Exception:

            pass


        # --------------------------------------------------
        # RadEsT trennen
        # --------------------------------------------------

        if self.connected:

            try:

                self.radest.disconnect()

            except Exception:

                pass


        self.connected = False


    # ==================================================
    # PRECHECK
    # ==================================================

    def run_precheck(self):

        self._check_connection()


        self.precheck_done = False


        # --------------------------------------------------
        # Polarisation messen
        # --------------------------------------------------

        self.polarization = (
            self.radest
            .measure_get_polarization_77ghz()
        )


        # --------------------------------------------------
        # Frequenzbereich messen
        # --------------------------------------------------

        self.frequency_range = (
            self.radest
            .measure_get_frequencyrange()
        )


        # --------------------------------------------------
        # Leistung / EIRP messen
        # --------------------------------------------------

        self.power = (
            self.radest
            .measure_get_77ghz_eirp()
        )


        self.precheck_done = True


        return {

            "polarization":
                self.polarization,

            "frequency_range":
                self.frequency_range,

            "power":
                self.power
        }


    # ==================================================
    # STATISCHE MESSUNG STARTEN / VORBEREITEN
    # ==================================================

    def start_static_measurement(
        self,
        distance_m
    ):

        self._check_connection()


        if not self.precheck_done:

            raise RuntimeError(
                "Vor der statischen Messung "
                "muss der Precheck durchgeführt werden"
            )


        # --------------------------------------------------
        # Eventuell laufende alte Messung stoppen
        # --------------------------------------------------

        self.stop_measurement_loop()


        # --------------------------------------------------
        # Alten Logger schließen
        #
        # Dadurch bekommt jede neue Messung später
        # eine eigene CSV-Datei.
        # --------------------------------------------------

        self.stop_logging()


        # --------------------------------------------------
        # Alte Live-Daten zurücksetzen
        # --------------------------------------------------

        with self._measurement_lock:

            self._latest_measurement = None

            self._measurement_error = None

            self._measurement_sequence = 0


        # --------------------------------------------------
        # Gewünschte Distanz
        # --------------------------------------------------

        self.requested_distance = float(
            distance_m
        )


        # --------------------------------------------------
        # RadEsT Distanz setzen
        # --------------------------------------------------

        self.radest.target_set_distance(
            self.requested_distance
        )


        # --------------------------------------------------
        # Tatsächlich realisierte RadEsT-Distanz lesen
        # --------------------------------------------------

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


    # ==================================================
    # EINEN FAHRZEUG-MESSPUNKT LESEN
    # ==================================================

    def read_static_measurement(self):

        self._check_connection()


        if not self.static_test_active:

            raise RuntimeError(
                "Statische Messung wurde "
                "noch nicht gestartet"
            )


        # --------------------------------------------------
        # Verfügbare Fahrzeug-Signale
        # --------------------------------------------------

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


        # --------------------------------------------------
        # Abstand ist für diesen Test erforderlich
        # --------------------------------------------------

        if "distance" not in signals_to_read:

            raise RuntimeError(
                "Für dieses Fahrzeug ist "
                "kein 'distance'-Signal definiert"
            )


        # --------------------------------------------------
        # Fahrzeugdiagnose
        #
        # VehicleDiagnostic sorgt selbst dafür,
        # dass ein DID nicht unnötig mehrfach gelesen wird.
        # --------------------------------------------------

        vehicle_values = (
            self.vehicle.read_signals(
                signals_to_read
            )
        )


        vehicle_distance = (
            vehicle_values[
                "distance"
            ][
                "value"
            ]
        )


        # --------------------------------------------------
        # Differenz
        #
        # Fahrzeug wird mit der tatsächlich realisierten
        # RadEsT-Distanz verglichen.
        # --------------------------------------------------

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


    # ==================================================
    # HINTERGRUND-MESSLOOP STARTEN
    # ==================================================

    def start_measurement_loop(
        self,
        interval_s=0.2
    ):

        self._check_connection()


        if not self.static_test_active:

            raise RuntimeError(
                "Statische Messung wurde "
                "noch nicht gestartet"
            )


        # --------------------------------------------------
        # Keinen zweiten Thread starten
        # --------------------------------------------------

        if (
            self._measurement_thread is not None
            and
            self._measurement_thread.is_alive()
        ):

            return


        # --------------------------------------------------
        # Messintervall
        # --------------------------------------------------

        self._measurement_interval_s = float(
            interval_s
        )


        if self._measurement_interval_s <= 0:

            raise ValueError(
                "Messintervall muss größer "
                "als 0 Sekunden sein"
            )


        # --------------------------------------------------
        # Fehler zurücksetzen
        # --------------------------------------------------

        with self._measurement_lock:

            self._measurement_error = None


        # --------------------------------------------------
        # Startzeit der Messung
        #
        # perf_counter_ns:
        # monotone Uhr für Zeitdifferenzen
        # --------------------------------------------------

        self._measurement_start_ns = (
            time.perf_counter_ns()
        )


        # --------------------------------------------------
        # Stop-Event zurücksetzen
        # --------------------------------------------------

        self._measurement_stop_event.clear()


        # --------------------------------------------------
        # Hintergrund-Thread erzeugen
        # --------------------------------------------------

        self._measurement_thread = (
            threading.Thread(
                target=self._measurement_loop,
                name="RadarMeasurementLoop",
                daemon=True
            )
        )


        # --------------------------------------------------
        # Messloop starten
        # --------------------------------------------------

        self._measurement_thread.start()


    # ==================================================
    # INTERNER MESSLOOP
    # ==================================================

    def _measurement_loop(self):

        while not self._measurement_stop_event.is_set():

            cycle_start = time.perf_counter()


            try:

                # ------------------------------------------
                # Fahrzeug EINMAL abfragen
                # ------------------------------------------

                measurement = (
                    self.read_static_measurement()
                )


                # ------------------------------------------
                # Zeitstempel nach der Diagnoseabfrage
                # ------------------------------------------

                timestamp_ns = (
                    time.perf_counter_ns()
                )


                timestamp_unix_ns = (
                    time.time_ns()
                )


                elapsed_s = (
                    timestamp_ns
                    - self._measurement_start_ns
                ) / 1_000_000_000


                # ------------------------------------------
                # Messwert intern aktualisieren
                # ------------------------------------------

                with self._measurement_lock:

                    self._measurement_sequence += 1


                    measurement[
                        "sequence"
                    ] = (
                        self._measurement_sequence
                    )


                    # --------------------------------------
                    # Monotone Pi-Zeit
                    # --------------------------------------

                    measurement[
                        "timestamp_ns"
                    ] = timestamp_ns


                    # --------------------------------------
                    # Absolute Unix-Systemzeit
                    # --------------------------------------

                    measurement[
                        "timestamp_unix_ns"
                    ] = timestamp_unix_ns


                    # --------------------------------------
                    # Zeit seit Beginn dieser Messung
                    # --------------------------------------

                    measurement[
                        "elapsed_s"
                    ] = elapsed_s


                    # --------------------------------------
                    # Derselbe Messwert wird später sowohl
                    # vom WebSocket als auch vom Logger
                    # verwendet.
                    # --------------------------------------

                    self._latest_measurement = (
                        measurement
                    )


                    self._measurement_error = None


                # ------------------------------------------
                # LOGGING
                #
                # Keine zweite Fahrzeugabfrage.
                # Genau derselbe Messpunkt wird gespeichert.
                # ------------------------------------------

                if (
                    self.logging_active
                    and
                    self.measurement_logger is not None
                ):

                    self.measurement_logger.write_measurement(
                        measurement
                    )


            except Exception as error:

                # ------------------------------------------
                # Fehler für WebSocket / Anwendung speichern
                # ------------------------------------------

                with self._measurement_lock:

                    self._measurement_error = str(
                        error
                    )


                # Bei Diagnosefehler Loop beenden
                break


            # ----------------------------------------------
            # Möglichst festes Messintervall
            # ----------------------------------------------

            elapsed_cycle = (
                time.perf_counter()
                - cycle_start
            )


            remaining = (
                self._measurement_interval_s
                - elapsed_cycle
            )


            # Wenn die Diagnose selbst länger als das
            # gewünschte Intervall dauert, wird direkt
            # der nächste Messzyklus gestartet.

            if remaining > 0:

                # Event.wait statt sleep:
                #
                # Der Thread kann dadurch beim Trennen
                # sofort aufgeweckt und beendet werden.

                self._measurement_stop_event.wait(
                    remaining
                )


    # ==================================================
    # HINTERGRUND-MESSLOOP STOPPEN
    # ==================================================

    def stop_measurement_loop(self):

        # --------------------------------------------------
        # Thread signalisieren, dass er stoppen soll
        # --------------------------------------------------

        self._measurement_stop_event.set()


        thread = self._measurement_thread


        # --------------------------------------------------
        # Kurz auf sauberes Thread-Ende warten
        # --------------------------------------------------

        if (
            thread is not None
            and
            thread.is_alive()
        ):

            thread.join(
                timeout=2.0
            )


        self._measurement_thread = None


    # ==================================================
    # LETZTEN MESSWERT ABHOLEN
    # ==================================================

    def get_latest_measurement(self):

        with self._measurement_lock:

            # ----------------------------------------------
            # Fehler aus Hintergrundthread weitergeben
            # ----------------------------------------------

            if self._measurement_error is not None:

                raise RuntimeError(
                    "Messfehler: "
                    + self._measurement_error
                )


            # ----------------------------------------------
            # Thread hat noch keinen ersten Messpunkt erzeugt
            # ----------------------------------------------

            if self._latest_measurement is None:

                return None


            # ----------------------------------------------
            # Kopie zurückgeben
            #
            # So kann WebSocket das interne Objekt
            # nicht versehentlich verändern.
            # ----------------------------------------------

            return copy.deepcopy(
                self._latest_measurement
            )


    # ==================================================
    # STATUS DES MESSLOOPS
    # ==================================================

    def is_measurement_running(self):

        return (
            self._measurement_thread is not None
            and
            self._measurement_thread.is_alive()
        )


    # ==================================================
    # LOGGING STARTEN
    # ==================================================

    def start_logging(self):

        # --------------------------------------------------
        # Wenn Logger schon läuft, aktuelle Datei liefern
        # --------------------------------------------------

        if (
            self.logging_active
            and
            self.measurement_logger is not None
        ):

            return (
                self.measurement_logger
                .get_file_path()
            )


        # --------------------------------------------------
        # Neuen Logger erzeugen
        # --------------------------------------------------

        self.measurement_logger = (
            MeasurementLogger(
                vehicle_id=self.vehicle_id
            )
        )


        # --------------------------------------------------
        # CSV öffnen
        # --------------------------------------------------

        self.measurement_logger.start()


        self.logging_active = True


        # --------------------------------------------------
        # Dateipfad zurückgeben
        # --------------------------------------------------

        return (
            self.measurement_logger
            .get_file_path()
        )


    # ==================================================
    # LOGGING STOPPEN
    # ==================================================

    def stop_logging(self):

        if self.measurement_logger is not None:

            try:

                self.measurement_logger.stop()

            except Exception:

                pass


        self.logging_active = False


    # ==================================================
    # AKTUELLE LOGDATEI
    # ==================================================

    def get_log_file(self):

        if self.measurement_logger is None:

            return None


        return (
            self.measurement_logger
            .get_file_path()
        )


    # ==================================================
    # VERFÜGBARE FAHRZEUGSIGNALE
    # ==================================================

    def get_available_signals(self):

        return (
            self.vehicle.get_available_signals()
        )


    # ==================================================
    # PRECHECK-ERGEBNIS
    # ==================================================

    def get_precheck_result(self):

        return {

            "polarization":
                self.polarization,

            "frequency_range":
                self.frequency_range,

            "power":
                self.power,

            "done":
                self.precheck_done
        }


    # ==================================================
    # VERBINDUNG PRÜFEN
    # ==================================================

    def _check_connection(self):

        if not self.connected:

            raise RuntimeError(
                "Testsystem ist nicht verbunden"
            )