import copy
import threading
import time

from diagnostics.vehicle import VehicleDiagnostic
from radest.device import RadestDevice
from measurement_logger import MeasurementLogger
from test_run import TestRun


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
        # TestRun
        # ==================================================

        self.test_run = None


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

            # Falls RadEsT nicht verbunden werden konnte,
            # Fahrzeugverbindung wieder schließen.

            self.vehicle.disconnect()

            raise


        self.connected = True


    # ==================================================
    # TRENNEN
    # ==================================================

    def disconnect(self):

        # --------------------------------------------------
        # Hintergrundmessung stoppen
        # --------------------------------------------------

        self.stop_measurement_loop()


        # --------------------------------------------------
        # Logger schließen
        #
        # Dadurch wird auch der aktuell aktive Test
        # im TestRun abgeschlossen.
        # --------------------------------------------------

        self.stop_logging()


        # --------------------------------------------------
        # TestRun abschließen
        # --------------------------------------------------

        self.finish_test_run()


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
    # TESTRUN STARTEN
    # ==================================================

    def start_test_run(self):

        self._check_connection()


        # --------------------------------------------------
        # Wenn bereits ein TestRun existiert,
        # diesen zurückgeben.
        # --------------------------------------------------

        if self.test_run is not None:

            return {

                "run_id":
                    self.test_run.get_run_id(),

                "directory":
                    self.test_run.get_directory()
            }


        # --------------------------------------------------
        # Neuen TestRun erzeugen
        # --------------------------------------------------

        self.test_run = TestRun(
            vehicle_id=self.vehicle_id
        )


        return {

            "run_id":
                self.test_run.get_run_id(),

            "directory":
                self.test_run.get_directory()
        }


    # ==================================================
    # TESTRUN ABSCHLIESSEN
    # ==================================================

    def finish_test_run(self):

        if self.test_run is None:
            return


        try:

            self.test_run.finish()

        except Exception:

            pass


    # ==================================================
    # TESTRUN INFORMATIONEN
    # ==================================================

    def get_test_run_info(self):

        if self.test_run is None:

            return None


        return {

            "run_id":
                self.test_run.get_run_id(),

            "directory":
                self.test_run.get_directory(),

            "metadata_file":
                self.test_run.get_metadata_file()
        }


    # ==================================================
    # PRECHECK
    # ==================================================

    def run_precheck(self):

        self._check_connection()


        self.precheck_done = False


        # --------------------------------------------------
        # Polarisation
        # --------------------------------------------------

        self.polarization = (
            self.radest
            .measure_get_polarization_77ghz()
        )


        # --------------------------------------------------
        # Frequenzbereich
        # --------------------------------------------------

        self.frequency_range = (
            self.radest
            .measure_get_frequencyrange()
        )


        # --------------------------------------------------
        # Leistung / EIRP
        # --------------------------------------------------

        self.power = (
            self.radest
            .measure_get_77ghz_eirp()
        )


        self.precheck_done = True


        result = {

            "polarization":
                self.polarization,

            "frequency_range":
                self.frequency_range,

            "power":
                self.power
        }


        # --------------------------------------------------
        # Precheck im TestRun speichern
        # --------------------------------------------------

        if self.test_run is not None:

            self.test_run.set_precheck(
                result
            )


        return result


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
        # Eventuell noch laufende alte Messung stoppen
        # --------------------------------------------------

        self.stop_measurement_loop()


        # --------------------------------------------------
        # Alten Logger schließen
        #
        # Dadurch wird auch der vorherige statische Test
        # im TestRun abgeschlossen.
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
        # RadEsT-Distanz setzen
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
        # Abstand wird für statischen Test benötigt
        # --------------------------------------------------

        if "distance" not in signals_to_read:

            raise RuntimeError(
                "Für dieses Fahrzeug ist "
                "kein 'distance'-Signal definiert"
            )


        # --------------------------------------------------
        # Fahrzeug EINMAL abfragen
        #
        # VehicleDiagnostic entscheidet intern,
        # welche DIDs dafür gelesen werden müssen.
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
        # Differenz zur realisierten RadEsT-Distanz
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
        # Monotone Startzeit
        # --------------------------------------------------

        self._measurement_start_ns = (
            time.perf_counter_ns()
        )


        # --------------------------------------------------
        # Stop-Event zurücksetzen
        # --------------------------------------------------

        self._measurement_stop_event.clear()


        # --------------------------------------------------
        # Hintergrundthread erzeugen
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

            cycle_start = (
                time.perf_counter()
            )


            try:

                # ------------------------------------------
                # Fahrzeug EINMAL abfragen
                # ------------------------------------------

                measurement = (
                    self.read_static_measurement()
                )


                # ------------------------------------------
                # Zeitstempel
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


                    # --------------------------------------
                    # Laufende Messpunktnummer
                    # --------------------------------------

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
                    # Absolute Unix-Zeit
                    # --------------------------------------

                    measurement[
                        "timestamp_unix_ns"
                    ] = timestamp_unix_ns


                    # --------------------------------------
                    # Zeit seit Messbeginn
                    # --------------------------------------

                    measurement[
                        "elapsed_s"
                    ] = elapsed_s


                    # --------------------------------------
                    # Aktuellen Messwert bereitstellen
                    #
                    # Derselbe Messwert wird vom
                    # WebSocket und vom Logger verwendet.
                    # --------------------------------------

                    self._latest_measurement = (
                        measurement
                    )


                    self._measurement_error = None


                # ------------------------------------------
                # CSV LOGGING
                #
                # Keine zweite Fahrzeugabfrage.
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


                # Bei Diagnose- oder Loggingfehler
                # Hintergrundmessung beenden.

                break


            # ----------------------------------------------
            # Möglichst festes Messintervall einhalten
            # ----------------------------------------------

            elapsed_cycle = (
                time.perf_counter()
                - cycle_start
            )


            remaining = (
                self._measurement_interval_s
                - elapsed_cycle
            )


            if remaining > 0:

                # Event.wait statt time.sleep:
                # dadurch kann der Thread beim Trennen
                # sofort beendet werden.

                self._measurement_stop_event.wait(
                    remaining
                )


    # ==================================================
    # HINTERGRUND-MESSLOOP STOPPEN
    # ==================================================

    def stop_measurement_loop(self):

        # --------------------------------------------------
        # Stop-Signal setzen
        # --------------------------------------------------

        self._measurement_stop_event.set()


        thread = self._measurement_thread


        # --------------------------------------------------
        # Kurz auf sauberes Ende warten
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
            # Noch kein Messpunkt vorhanden
            # ----------------------------------------------

            if self._latest_measurement is None:

                return None


            # ----------------------------------------------
            # Kopie zurückgeben
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
        # Wenn Logger bereits aktiv:
        # vorhandene Datei zurückgeben.
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
        # Speicherort bestimmen
        #
        # Wenn TestRun vorhanden:
        # CSV direkt in dessen Ordner speichern.
        # --------------------------------------------------

        if self.test_run is not None:

            log_directory = (
                self.test_run
                .get_directory()
            )

        else:

            log_directory = None


        # --------------------------------------------------
        # Logger erstellen
        # --------------------------------------------------

        self.measurement_logger = (
            MeasurementLogger(
                vehicle_id=self.vehicle_id,
                log_directory=log_directory
            )
        )


        # --------------------------------------------------
        # CSV öffnen
        # --------------------------------------------------

        self.measurement_logger.start()


        self.logging_active = True


        log_file = (
            self.measurement_logger
            .get_file_path()
        )


        # --------------------------------------------------
        # Statischen Test im TestRun registrieren
        # --------------------------------------------------

        if (
            self.test_run is not None
            and
            self.static_test_active
        ):

            self.test_run.start_static_test(

                requested_distance=
                    self.requested_distance,

                radest_distance=
                    self.radest_distance,

                log_file=
                    log_file
            )


        return log_file


    # ==================================================
    # LOGGING STOPPEN
    # ==================================================

    def stop_logging(self):

        # --------------------------------------------------
        # CSV schließen
        # --------------------------------------------------

        if self.measurement_logger is not None:

            try:

                self.measurement_logger.stop()

            except Exception:

                pass


        self.logging_active = False


        # --------------------------------------------------
        # Aktiven Test im TestRun abschließen
        # --------------------------------------------------

        if self.test_run is not None:

            try:

                self.test_run.finish_active_test()

            except Exception:

                pass


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
    # VERBINDUNG PRÜFEN
    # ==================================================

    def _check_connection(self):

        if not self.connected:

            raise RuntimeError(
                "Testsystem ist nicht verbunden"
            )