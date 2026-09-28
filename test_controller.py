import copy
import threading
import time

from diagnostics.vehicle import VehicleDiagnostic
from database.database import get_vehicle
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
        self.precheck_skipped = False

        self.static_test_active = False

        self.dynamic_test_active = False

        self._measurement_mode = None


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

        self.static_rcs_limits = None
        self.static_rcs_dbsm = None
        self._static_rcs_prepared_distance = None


        # ==================================================
        # Dynamische Messung
        # ==================================================

        self.dynamic_start_distance = None

        self.dynamic_end_distance = None

        self.dynamic_velocity_kmh = None

        self.dynamic_duration_s = None
        self.dynamic_pre_hold_s = 2.0
        self.dynamic_post_hold_s = 2.0
        self.dynamic_total_duration_s = None
        self.dynamic_direction = None
        self.dynamic_pre_hold_distance = None

        self.dynamic_rcs_limits = None
        self.dynamic_rcs_dbsm = None
        self.dynamic_rcs_constant_state = None
        self._dynamic_rcs_prepared_configuration = None

        self._scenario_thread = None

        self._dynamic_sequence_start_ns = None
        self._scenario_start_ns = None
        self._scenario_trigger_requested_ns = None
        self._scenario_trigger_call_ns = None
        self._scenario_trigger_returned_ns = None


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

        measurement_was_active = (
            self.static_test_active
            or self.dynamic_test_active
            or self.is_measurement_running()
        )

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

        self.stop_logging(
            status=(
                "aborted"
                if measurement_was_active
                else "finished"
            ),
            reason=(
                "system_disconnected"
                if measurement_was_active
                else None
            )
        )


        # --------------------------------------------------
        # TestRun abschließen
        # --------------------------------------------------

        self.finish_test_run()


        self.static_test_active = False

        self.dynamic_test_active = False

        self._measurement_mode = None


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
            vehicle_id=self.vehicle_id,
            vehicle_data=get_vehicle(self.vehicle_id)
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

    def finish_test_run(
        self,
        status=None,
        reason=None
    ):

        if self.test_run is None:
            return


        try:

            self.test_run.finish(
                status=status,
                reason=reason
            )

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
    # QUICK CHECK
    # ==================================================

    # ==================================================
# QUICK CHECK
# ==================================================

    def run_quick_check(self):

        self._check_connection()

        try:
            dtcs_before = self.vehicle.read_dtcs()
            dtc_error = None

        except Exception as error:
            dtcs_before = []
            dtc_error = str(error)

        identification = (
            self.vehicle.read_identification()
        )

        identification_summary = {
            "configured": len(identification),
            "match": 0,
            "mismatch": 0,
            "unknown": 0,
            "read_error": 0,
        }

        for item in identification:

            if item["read_status"] != "ok":
                item["status"] = "read_error"

            else:
                accepted_values = [
                    entry["value"]
                    for entry in item["accepted_values"]
                ]

                if not accepted_values:
                    item["status"] = "unknown"

                else:
                    actual_value = str(
                        item["value"]
                    ).strip().casefold()

                    normalized_references = {
                        str(value).strip().casefold()
                        for value in accepted_values
                    }

                    item["status"] = (
                        "match"
                        if actual_value in normalized_references
                        else "mismatch"
                    )

            identification_summary[
                item["status"]
            ] += 1

        result = {
            "timestamp_unix_ns": time.time_ns(),
            "dtcs_before": dtcs_before,
            "dtc_error": dtc_error,
            "identification": identification,
            "identification_summary": identification_summary
        }

        if self.test_run is not None:

            self.test_run.set_quick_check(
                result
            )

        return result

    # ==================================================
    # PRECHECK
    # ==================================================

    def run_precheck(self):

        self.start_precheck()
        self.measure_precheck_polarization()
        self.measure_precheck_frequency()
        return self.measure_precheck_power()


    def start_precheck(self):

        self._check_connection()

        self.precheck_done = False
        self.precheck_skipped = False
        self.polarization = None
        self.frequency_range = None
        self.power = None
        self.static_rcs_limits = None
        self.static_rcs_dbsm = None
        self._static_rcs_prepared_distance = None
        self.dynamic_rcs_limits = None
        self.dynamic_rcs_dbsm = None
        self.dynamic_rcs_constant_state = None
        self._dynamic_rcs_prepared_configuration = None

        return {
            "status": "running",
            "phase": "polarization"
        }


    def measure_precheck_polarization(self):

        self._check_connection()

        self.polarization = (
            self.radest
            .measure_get_polarization_77ghz()
        )

        detected_code = (
            str(self.polarization)
            .strip()
            .strip('"')
            .split(",")[0]
            .strip()
            .upper()
        )

        polarization_setting = {
            "5": "H",
            "8": "V",
            "7": "P45",
            "6": "M45",
            "H": "H",
            "V": "V",
            "P45": "P45",
            "M45": "M45"
        }.get(detected_code)

        if polarization_setting is None:
            raise RuntimeError(
                "Unbekannte Polarisationsantwort des RadEsT: "
                f"{self.polarization}"
            )

        self.radest.system_set_polarization_77ghz(
            polarization_setting
        )

        tx_antenna, rx_antenna = (
            (6, 7)
            if polarization_setting in {"H", "V"}
            else (5, 5)
        )
        self.radest.system_set_tx(tx_antenna)
        self.radest.system_set_rx(rx_antenna)

        return {
            "status": "running",
            "phase": "frequency",
            "polarization": self.polarization,
            "polarization_setting": polarization_setting,
            "tx_antenna": tx_antenna,
            "rx_antenna": rx_antenna
        }


    def measure_precheck_frequency(self):

        self._check_connection()

        self.frequency_range = (
            self.radest
            .measure_get_frequencyrange()
        )

        return {
            "status": "running",
            "phase": "power",
            "polarization": self.polarization,
            "frequency_range": self.frequency_range
        }


    def measure_precheck_power(self):

        self._check_connection()

        self.power = (
            self.radest
            .measure_get_77ghz_eirp()
        )

        self.precheck_done = True
        self.precheck_skipped = False

        result = {
            "status": "completed",
            "skipped": False,
            "polarization": self.polarization,
            "frequency_range": self.frequency_range,
            "power": self.power
        }

        if self.test_run is not None:
            self.test_run.set_precheck(
                result
            )

        return result


    def skip_precheck(self):

        self._check_connection()

        self.precheck_done = True
        self.precheck_skipped = True

        self.polarization = None
        self.frequency_range = None
        self.power = None
        self.static_rcs_limits = None
        self.static_rcs_dbsm = None
        self._static_rcs_prepared_distance = None
        self.dynamic_rcs_limits = None
        self.dynamic_rcs_dbsm = None
        self.dynamic_rcs_constant_state = None
        self._dynamic_rcs_prepared_configuration = None

        result = {
            "status": "skipped",
            "skipped": True,
            "reason": "skipped_by_user"
        }

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
                self.precheck_done,

            "skipped":
                self.precheck_skipped
        }


    @staticmethod
    def _parse_rcs_limits(answer):

        values = [
            value.strip().strip('"')
            for value in str(answer).strip().split(",")
        ]

        if len(values) != 4:
            raise RuntimeError(
                "RadEsT hat ungültige RCS-Grenzen zurückgegeben: "
                f"{answer}"
            )

        return {
            "polarization": values[0],
            "eirp_dbm": float(values[1]),
            "rcs_min_dbsm": float(values[2]),
            "rcs_max_dbsm": float(values[3])
        }


    @staticmethod
    def _validate_rcs_value(rcs_dbsm, limits):

        rcs_dbsm = float(rcs_dbsm)

        if not (
            limits["rcs_min_dbsm"]
            <= rcs_dbsm
            <= limits["rcs_max_dbsm"]
        ):
            raise ValueError(
                f"RCS muss zwischen "
                f"{limits['rcs_min_dbsm']:.2f} und "
                f"{limits['rcs_max_dbsm']:.2f} dBsm liegen"
            )

        return rcs_dbsm


    # ==================================================
    # STATISCHE MESSUNG VORBEREITEN
    # ==================================================

    def prepare_static_measurement(
        self,
        distance_m
    ):

        self._check_connection()


        if not self.precheck_done:

            raise RuntimeError(
                "Vor der statischen Messung "
                "muss der Precheck durchgeführt werden"
            )


        if (
            self._scenario_thread is not None
            and
            self._scenario_thread.is_alive()
        ):

            raise RuntimeError(
                "Das dynamische RadEsT-Szenario läuft noch"
            )

        distance_m = float(distance_m)

        if distance_m <= 0:
            raise ValueError(
                "Distanz muss größer als 0 m sein"
            )

        self.static_rcs_limits = None
        self.static_rcs_dbsm = None
        self._static_rcs_prepared_distance = None

        self.dynamic_rcs_limits = None
        self.dynamic_rcs_dbsm = None
        self.dynamic_rcs_constant_state = None
        self._dynamic_rcs_prepared_configuration = None


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

        self.static_rcs_limits = self._parse_rcs_limits(
            self.radest.target_get_rcs_limits()
        )

        self.static_rcs_dbsm = None
        self._static_rcs_prepared_distance = (
            self.requested_distance
        )

        self.static_test_active = False
        self.dynamic_test_active = False
        self._measurement_mode = None


        return {

            "test_type":
                "static",

            "requested_distance":
                self.requested_distance,

            "radest_distance":
                self.radest_distance,

            "rcs_limits":
                self.static_rcs_limits
        }


    # ==================================================
    # STATISCHE MESSUNG STARTEN
    # ==================================================

    def start_static_measurement(
        self,
        distance_m,
        rcs_dbsm
    ):

        self._check_connection()

        distance_m = float(distance_m)

        if (
            self.static_rcs_limits is None
            or self._static_rcs_prepared_distance != distance_m
        ):
            raise RuntimeError(
                "RCS-Grenzen müssen für diese Distanz zuerst "
                "ermittelt werden"
            )

        self.static_rcs_dbsm = self._validate_rcs_value(
            rcs_dbsm,
            self.static_rcs_limits
        )

        self.radest.target_set_rcs(
            self.static_rcs_dbsm
        )


        self.static_test_active = True

        self.dynamic_test_active = False

        self._measurement_mode = "static"


        return {

            "test_type":
                "static",

            "requested_distance":
                self.requested_distance,

            "radest_distance":
                self.radest_distance,

            "rcs_dbsm":
                self.static_rcs_dbsm,

            "rcs_limits":
                self.static_rcs_limits
        }


    # ==================================================
    # DYNAMISCHE MESSUNG VORBEREITEN
    # ==================================================

    def prepare_dynamic_measurement(
        self,
        start_distance_m,
        end_distance_m,
        velocity_kmh,
        rcs_constant_state,
        pre_hold_s=2.0,
        post_hold_s=2.0
    ):

        self._check_connection()


        if not self.precheck_done:

            raise RuntimeError(
                "Vor der dynamischen Messung "
                "muss der Precheck durchgeführt werden"
            )


        if (
            self._scenario_thread is not None
            and
            self._scenario_thread.is_alive()
        ):

            raise RuntimeError(
                "Das dynamische RadEsT-Szenario läuft bereits"
            )


        start_distance_m = float(
            start_distance_m
        )

        end_distance_m = float(
            end_distance_m
        )

        velocity_kmh = float(
            velocity_kmh
        )

        rcs_constant_state = int(
            rcs_constant_state
        )

        pre_hold_s = float(
            pre_hold_s
        )

        post_hold_s = float(
            post_hold_s
        )


        if start_distance_m <= 0:

            raise ValueError(
                "Startdistanz muss größer als 0 m sein"
            )


        if end_distance_m <= 0:

            raise ValueError(
                "Enddistanz muss größer als 0 m sein"
            )


        if start_distance_m == end_distance_m:

            raise ValueError(
                "Start- und Enddistanz müssen unterschiedlich sein"
            )


        if velocity_kmh <= 0:

            raise ValueError(
                "Geschwindigkeit muss größer als 0 km/h sein"
            )

        if rcs_constant_state not in (0, 1):

            raise ValueError(
                "RCS-Modus muss 0 (konstant) oder 1 (variabel) sein"
            )

        if pre_hold_s < 0 or post_hold_s < 0:

            raise ValueError(
                "Vorhalte- und Nachhaltezeit dürfen "
                "nicht negativ sein"
            )

        self.dynamic_rcs_limits = None
        self.dynamic_rcs_dbsm = None
        self.dynamic_rcs_constant_state = None
        self._dynamic_rcs_prepared_configuration = None

        self.static_rcs_limits = None
        self.static_rcs_dbsm = None
        self._static_rcs_prepared_distance = None


        self.stop_measurement_loop()

        self.stop_logging()


        with self._measurement_lock:

            self._latest_measurement = None

            self._measurement_error = None

            self._measurement_sequence = 0


        # --------------------------------------------------
        # Scenario im RadEsT konfigurieren
        # --------------------------------------------------

        self.radest.scenario_distance_start(
            start_distance_m
        )

        self.radest.scenario_distance_end(
            end_distance_m
        )

        self.radest.scenario_velocity(
            velocity_kmh
        )

        self.radest.scenario_constant_rcs(
            rcs_constant_state
        )


        # --------------------------------------------------
        # Tatsächlich übernommene Werte zurücklesen
        # --------------------------------------------------

        self.dynamic_start_distance = (
            self.radest.scenario_get_distance_start()
        )

        self.dynamic_end_distance = (
            self.radest.scenario_get_distance_end()
        )

        self.dynamic_velocity_kmh = float(
            self.radest.scenario_get_velocity()
        )

        self.dynamic_pre_hold_s = pre_hold_s
        self.dynamic_post_hold_s = post_hold_s

        self.dynamic_direction = (
            "approaching"
            if self.dynamic_end_distance
            < self.dynamic_start_distance
            else "receding"
        )

        self.radest.target_set_distance(
            self.dynamic_start_distance
        )

        self.dynamic_pre_hold_distance = (
            self.radest.target_get_distance()
        )

        self.dynamic_rcs_limits = self._parse_rcs_limits(
            self.radest.scenario_get_rcs_limits()
        )

        self.dynamic_rcs_dbsm = None
        self.dynamic_rcs_constant_state = (
            rcs_constant_state
        )

        self._dynamic_rcs_prepared_configuration = (
            start_distance_m,
            end_distance_m,
            velocity_kmh,
            rcs_constant_state
        )


        if self.dynamic_velocity_kmh <= 0:

            raise RuntimeError(
                "RadEsT hat keine gültige "
                "Scenario-Geschwindigkeit übernommen"
            )


        velocity_mps = (
            self.dynamic_velocity_kmh
            / 3.6
        )

        self.dynamic_duration_s = (
            abs(
                self.dynamic_end_distance
                - self.dynamic_start_distance
            )
            / velocity_mps
        )

        self.dynamic_total_duration_s = (
            self.dynamic_pre_hold_s
            + self.dynamic_duration_s
            + self.dynamic_post_hold_s
        )


        self.requested_distance = (
            self.dynamic_start_distance
        )

        self.radest_distance = (
            self.dynamic_start_distance
        )

        self.static_test_active = False
        self.dynamic_test_active = False
        self._measurement_mode = None


        return {

            "start_distance":
                self.dynamic_start_distance,

            "end_distance":
                self.dynamic_end_distance,

            "velocity_kmh":
                self.dynamic_velocity_kmh,

            "duration_s":
                self.dynamic_duration_s,

            "pre_hold_s":
                self.dynamic_pre_hold_s,

            "post_hold_s":
                self.dynamic_post_hold_s,

            "total_duration_s":
                self.dynamic_total_duration_s,

            "direction":
                self.dynamic_direction,

            "pre_hold_distance":
                self.dynamic_pre_hold_distance,

            "rcs_constant_state":
                self.dynamic_rcs_constant_state,

            "rcs_limits":
                self.dynamic_rcs_limits
        }


    # ==================================================
    # DYNAMISCHE MESSUNG STARTEN
    # ==================================================

    def start_dynamic_measurement(
        self,
        start_distance_m,
        end_distance_m,
        velocity_kmh,
        rcs_constant_state,
        rcs_dbsm
    ):

        self._check_connection()

        configuration = (
            float(start_distance_m),
            float(end_distance_m),
            float(velocity_kmh),
            int(rcs_constant_state)
        )

        if (
            self.dynamic_rcs_limits is None
            or self._dynamic_rcs_prepared_configuration
            != configuration
        ):
            raise RuntimeError(
                "RCS-Grenzen müssen für dieses Szenario zuerst "
                "ermittelt werden"
            )

        self.dynamic_rcs_dbsm = self._validate_rcs_value(
            rcs_dbsm,
            self.dynamic_rcs_limits
        )

        self.radest.scenario_set_rcs(
            self.dynamic_rcs_dbsm
        )

        self.static_test_active = False
        self.dynamic_test_active = True
        self._measurement_mode = "dynamic"

        self._dynamic_sequence_start_ns = None
        self._scenario_start_ns = None
        self._scenario_trigger_requested_ns = None
        self._scenario_trigger_call_ns = None
        self._scenario_trigger_returned_ns = None

        return {
            "start_distance": self.dynamic_start_distance,
            "end_distance": self.dynamic_end_distance,
            "velocity_kmh": self.dynamic_velocity_kmh,
            "duration_s": self.dynamic_duration_s,
            "pre_hold_s": self.dynamic_pre_hold_s,
            "post_hold_s": self.dynamic_post_hold_s,
            "total_duration_s": self.dynamic_total_duration_s,
            "direction": self.dynamic_direction,
            "pre_hold_distance": self.dynamic_pre_hold_distance,
            "rcs_constant_state": self.dynamic_rcs_constant_state,
            "rcs_dbsm": self.dynamic_rcs_dbsm,
            "rcs_limits": self.dynamic_rcs_limits
        }


    # ==================================================
    # DYNAMISCHES SCENARIO TRIGGERN
    # ==================================================

    def trigger_dynamic_scenario(self):

        self._check_connection()


        if not self.dynamic_test_active:

            raise RuntimeError(
                "Dynamische Messung wurde noch nicht vorbereitet"
            )


        if not self.is_measurement_running():

            raise RuntimeError(
                "Messloop muss vor dem Scenario gestartet werden"
            )


        self._dynamic_sequence_start_ns = (
            time.perf_counter_ns()
        )

        if self.test_run is not None:
            self.test_run.update_active_test({
                "dynamic_sequence_start_ns":
                    self._dynamic_sequence_start_ns
            })

        self._scenario_thread = (
            threading.Thread(
                target=self._run_dynamic_scenario,
                name="RadestScenario",
                daemon=True
            )
        )

        self._scenario_thread.start()


    def _run_dynamic_scenario(self):

        try:

            if self._measurement_stop_event.wait(
                self.dynamic_pre_hold_s
            ):
                return

            self._scenario_trigger_requested_ns = (
                time.perf_counter_ns()
            )

            self._scenario_trigger_call_ns = (
                time.perf_counter_ns()
            )

            self._scenario_start_ns = (
                self._scenario_trigger_call_ns
            )

            if self.test_run is not None:
                self.test_run.update_active_test({
                    "scenario_trigger_requested_ns":
                        self._scenario_trigger_requested_ns,
                    "scenario_trigger_call_ns":
                        self._scenario_trigger_call_ns
                })

            self.radest.scenario_trigger()

            self._scenario_trigger_returned_ns = (
                time.perf_counter_ns()
            )

            if self.test_run is not None:
                self.test_run.update_active_test({
                    "scenario_trigger_returned_ns":
                        self._scenario_trigger_returned_ns
                })

        except Exception as error:

            self._scenario_trigger_returned_ns = (
                time.perf_counter_ns()
            )

            with self._measurement_lock:

                self._measurement_error = (
                    "RadEsT Scenario-Fehler: "
                    + str(error)
                )

            if self.test_run is not None:
                self.test_run.update_active_test({
                    "scenario_trigger_returned_ns":
                        self._scenario_trigger_returned_ns,
                    "scenario_error": str(error)
                })

            self._write_error_measurement(
                error,
                error_type="radest_scenario"
            )

            self._measurement_stop_event.set()


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

        vehicle_request_start_ns = time.perf_counter_ns()

        vehicle_values = (
            self.vehicle.read_signals(
                signals_to_read
            )
        )

        vehicle_response_ns = time.perf_counter_ns()


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

            "test_type":
                "static",

            "sample_status":
                "ok",

            "requested_distance":
                self.requested_distance,

            "radest_distance":
                self.radest_distance,

            "radest_distance_source":
                "device_readback",

            "rcs_dbsm":
                self.static_rcs_dbsm,

            "rcs_limits":
                self.static_rcs_limits,

            "vehicle_request_start_ns":
                vehicle_request_start_ns,

            "vehicle_response_ns":
                vehicle_response_ns,

            "vehicle_read_duration_ms":
                (
                    vehicle_response_ns
                    - vehicle_request_start_ns
                ) / 1_000_000,

            "vehicle":
                vehicle_values,

            "distance_error":
                distance_error
        }


    # ==================================================
    # EINEN DYNAMISCHEN MESSPUNKT LESEN
    # ==================================================

    def read_dynamic_measurement(self):

        self._check_connection()


        if not self.dynamic_test_active:

            raise RuntimeError(
                "Dynamische Messung wurde "
                "noch nicht gestartet"
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


        if signals_to_read:

            vehicle_request_start_ns = time.perf_counter_ns()

            vehicle_values = (
                self.vehicle.read_signals(
                    signals_to_read
                )
            )

            vehicle_response_ns = time.perf_counter_ns()

        else:

            vehicle_values = {}
            vehicle_request_start_ns = None
            vehicle_response_ns = None


        # --------------------------------------------------
        # Aktuelle Sollposition des RadEsT-Scenario
        # aus Start, Ende, Geschwindigkeit und Zeit bilden.
        # Während das Scenario läuft, wird derselbe
        # RadEsT-Socket nicht parallel abgefragt.
        # --------------------------------------------------

        sample_time_ns = (
            vehicle_response_ns
            if vehicle_response_ns is not None
            else time.perf_counter_ns()
        )

        if self._dynamic_sequence_start_ns is None:
            sequence_elapsed_s = 0.0
        else:
            sequence_elapsed_s = max(
                0.0,
                (
                    sample_time_ns
                    - self._dynamic_sequence_start_ns
                ) / 1_000_000_000
            )

        if self._scenario_start_ns is None:
            phase = "pre_hold"
            phase_elapsed_s = sequence_elapsed_s
            scenario_elapsed_s = (
                sequence_elapsed_s
                - self.dynamic_pre_hold_s
            )
            progress = 0.0

        else:
            scenario_elapsed_s = max(
                0.0,
                (
                    sample_time_ns
                    - self._scenario_start_ns
                ) / 1_000_000_000
            )

            progress = min(
                1.0,
                scenario_elapsed_s
                / self.dynamic_duration_s
            )

            if progress < 1.0:
                phase = "moving"
                phase_elapsed_s = scenario_elapsed_s
            else:
                phase = "post_hold"
                phase_elapsed_s = max(
                    0.0,
                    scenario_elapsed_s
                    - self.dynamic_duration_s
                )

        radest_distance = (
            self.dynamic_start_distance
            + (
                self.dynamic_end_distance
                - self.dynamic_start_distance
            )
            * progress
        )

        scenario_done = (
            self._scenario_start_ns is not None
            and
            progress >= 1.0
            and
            phase_elapsed_s >= self.dynamic_post_hold_s
            and
            self._scenario_trigger_returned_ns is not None
        )


        vehicle_distance = (
            vehicle_values.get(
                "distance",
                {}
            ).get(
                "value"
            )
        )


        if vehicle_distance is None:

            distance_error = None

        else:

            distance_error = (
                vehicle_distance
                - radest_distance
            )


        self.requested_distance = (
            radest_distance
        )

        self.radest_distance = (
            radest_distance
        )


        return {

            "test_type":
                "dynamic",

            "sample_status":
                "ok",

            "requested_distance":
                radest_distance,

            "radest_distance":
                radest_distance,

            "radest_distance_source":
                "time_based_estimate",

            "estimated_scenario_distance":
                radest_distance,

            "rcs_dbsm":
                self.dynamic_rcs_dbsm,

            "rcs_constant_state":
                self.dynamic_rcs_constant_state,

            "rcs_limits":
                self.dynamic_rcs_limits,

            "vehicle_request_start_ns":
                vehicle_request_start_ns,

            "vehicle_response_ns":
                vehicle_response_ns,

            "vehicle_read_duration_ms":
                (
                    None
                    if vehicle_request_start_ns is None
                    else (
                        vehicle_response_ns
                        - vehicle_request_start_ns
                    ) / 1_000_000
                ),

            "vehicle":
                vehicle_values,

            "distance_error":
                distance_error,

            "scenario_start_distance":
                self.dynamic_start_distance,

            "scenario_end_distance":
                self.dynamic_end_distance,

            "scenario_velocity_kmh":
                self.dynamic_velocity_kmh,

            "scenario_duration_s":
                self.dynamic_duration_s,

            "dynamic_pre_hold_s":
                self.dynamic_pre_hold_s,

            "dynamic_post_hold_s":
                self.dynamic_post_hold_s,

            "dynamic_total_duration_s":
                self.dynamic_total_duration_s,

            "dynamic_direction":
                self.dynamic_direction,

            "phase":
                phase,

            "phase_elapsed_s":
                phase_elapsed_s,

            "sequence_elapsed_s":
                sequence_elapsed_s,

            "scenario_elapsed_s":
                scenario_elapsed_s,

            "scenario_progress":
                progress,

            "scenario_done":
                scenario_done,

            "scenario_trigger_requested_ns":
                self._scenario_trigger_requested_ns,

            "dynamic_sequence_start_ns":
                self._dynamic_sequence_start_ns,

            "scenario_trigger_call_ns":
                self._scenario_trigger_call_ns,

            "scenario_trigger_returned_ns":
                self._scenario_trigger_returned_ns
        }


    # ==================================================
    # HINTERGRUND-MESSLOOP STARTEN
    # ==================================================

    def start_measurement_loop(
        self,
        interval_s=0.2
    ):

        self._check_connection()


        if not (
            self.static_test_active
            or
            self.dynamic_test_active
        ):

            raise RuntimeError(
                "Messung wurde noch nicht vorbereitet"
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

        if self.test_run is not None:
            self.test_run.update_active_test({
                "measurement_interval_s_requested":
                    self._measurement_interval_s,
                "sampling_rate_hz_requested":
                    1.0 / self._measurement_interval_s
            })


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

                if self._measurement_mode == "dynamic":

                    measurement = (
                        self.read_dynamic_measurement()
                    )

                else:

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

                    measurement[
                        "measurement_interval_s"
                    ] = self._measurement_interval_s


                    # --------------------------------------
                    # Aktuellen Messwert bereitstellen
                    #
                    # Derselbe Messwert wird vom
                    # WebSocket und vom Logger verwendet.
                    # --------------------------------------

                    self._latest_measurement = (
                        measurement
                    )


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


                # Ein dynamisches Scenario endet automatisch,
                # sobald die berechnete Enddistanz erreicht ist.
                if measurement.get("scenario_done"):

                    break


            except Exception as error:

                # ------------------------------------------
                # Fehler für WebSocket / Anwendung speichern
                # ------------------------------------------

                with self._measurement_lock:

                    self._measurement_error = str(
                        error
                    )

                self._write_error_measurement(
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


        if self._measurement_error is not None:

            self.static_test_active = False
            self.dynamic_test_active = False

            self.stop_logging(
                status="failed",
                reason="measurement_error",
                error=self._measurement_error
            )

        elif self._measurement_mode == "dynamic":

            with self._measurement_lock:
                scenario_completed = bool(
                    self._latest_measurement
                    and self._latest_measurement.get(
                        "scenario_done"
                    )
                )

            if scenario_completed:
                self.dynamic_test_active = False

                self.stop_logging(
                    status="finished",
                    reason="scenario_completed"
                )


    def _write_error_measurement(
        self,
        error,
        error_type=None
    ):

        timestamp_ns = time.perf_counter_ns()
        timestamp_unix_ns = time.time_ns()

        elapsed_s = (
            None
            if self._measurement_start_ns is None
            else (
                timestamp_ns
                - self._measurement_start_ns
            ) / 1_000_000_000
        )

        with self._measurement_lock:
            self._measurement_sequence += 1

            measurement = {
                "test_type": self._measurement_mode,
                "sample_status": "error",
                "error_type": error_type or type(error).__name__,
                "error_message": str(error),
                "sequence": self._measurement_sequence,
                "timestamp_ns": timestamp_ns,
                "timestamp_unix_ns": timestamp_unix_ns,
                "elapsed_s": elapsed_s,
                "measurement_interval_s": self._measurement_interval_s,
                "requested_distance": self.requested_distance,
                "radest_distance": self.radest_distance,
                "radest_distance_source": (
                    "time_based_estimate"
                    if self._measurement_mode == "dynamic"
                    else "device_readback"
                ),
                "estimated_scenario_distance": (
                    self.radest_distance
                    if self._measurement_mode == "dynamic"
                    else None
                ),
                "vehicle": {},
                "scenario_start_distance": self.dynamic_start_distance,
                "scenario_end_distance": self.dynamic_end_distance,
                "scenario_velocity_kmh": self.dynamic_velocity_kmh,
                "scenario_duration_s": self.dynamic_duration_s,
                "dynamic_pre_hold_s": self.dynamic_pre_hold_s,
                "dynamic_post_hold_s": self.dynamic_post_hold_s,
                "dynamic_total_duration_s": self.dynamic_total_duration_s,
                "dynamic_direction": self.dynamic_direction,
                "phase": (
                    self._latest_measurement.get("phase")
                    if self._latest_measurement is not None
                    else None
                ),
                "phase_elapsed_s": (
                    self._latest_measurement.get("phase_elapsed_s")
                    if self._latest_measurement is not None
                    else None
                ),
                "sequence_elapsed_s": (
                    None
                    if self._dynamic_sequence_start_ns is None
                    else (
                        timestamp_ns
                        - self._dynamic_sequence_start_ns
                    ) / 1_000_000_000
                ),
                "dynamic_sequence_start_ns":
                    self._dynamic_sequence_start_ns,
                "scenario_trigger_requested_ns":
                    self._scenario_trigger_requested_ns,
                "scenario_trigger_call_ns":
                    self._scenario_trigger_call_ns,
                "scenario_trigger_returned_ns":
                    self._scenario_trigger_returned_ns,
            }

            self._latest_measurement = measurement

        if (
            self.logging_active
            and self.measurement_logger is not None
        ):
            self.measurement_logger.write_measurement(
                measurement
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
                run_id=(
                    self.test_run.get_run_id()
                    if self.test_run is not None
                    else None
                ),
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
        # Test im TestRun registrieren
        # --------------------------------------------------

        if (
            self.test_run is not None
            and
            self.static_test_active
        ):

            test_id = self.test_run.start_static_test(

                requested_distance=
                    self.requested_distance,

                radest_distance=
                    self.radest_distance,

                rcs={
                    "value_dbsm": self.static_rcs_dbsm,
                    "limits": self.static_rcs_limits
                },

                log_file=
                    log_file
            )


        elif (
            self.test_run is not None
            and
            self.dynamic_test_active
        ):

            test_id = self.test_run.start_dynamic_test(

                parameters={

                    "start_distance_m":
                        self.dynamic_start_distance,

                    "end_distance_m":
                        self.dynamic_end_distance,

                    "velocity_kmh":
                        self.dynamic_velocity_kmh,

                    "duration_s":
                        self.dynamic_duration_s,

                    "pre_hold_s":
                        self.dynamic_pre_hold_s,

                    "post_hold_s":
                        self.dynamic_post_hold_s,

                    "total_duration_s":
                        self.dynamic_total_duration_s,

                    "direction":
                        self.dynamic_direction,

                    "pre_hold_distance_m":
                        self.dynamic_pre_hold_distance,

                    "rcs_dbsm":
                        self.dynamic_rcs_dbsm,

                    "rcs_constant_state":
                        self.dynamic_rcs_constant_state,

                    "rcs_limits":
                        self.dynamic_rcs_limits
                },

                log_file=
                    log_file
            )

        else:
            test_id = None

        self.measurement_logger.set_test_id(
            test_id
        )


        return log_file


    # ==================================================
    # LOGGING STOPPEN
    # ==================================================

    def stop_logging(
        self,
        status="finished",
        reason=None,
        error=None
    ):

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

                self.test_run.update_active_test({
                    "sample_count":
                        self._measurement_sequence
                })

                self.test_run.finish_active_test(
                    status=status,
                    reason=reason,
                    error=error
                )

            except Exception:

                pass


    def stop_active_measurement(self):

        was_dynamic = self.dynamic_test_active

        self.stop_measurement_loop()

        self.static_test_active = False
        self.dynamic_test_active = False
        self._measurement_mode = None

        status = (
            "aborted"
            if was_dynamic
            else "finished"
        )

        reason = (
            "stopped_by_user_before_scenario_end"
            if was_dynamic
            else "stopped_by_user"
        )

        self.stop_logging(
            status=status,
            reason=reason
        )

        return {
            "stopped": True,
            "status": status,
            "reason": reason
        }


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
