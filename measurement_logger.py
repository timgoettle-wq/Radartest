import csv
import threading
from datetime import datetime
from pathlib import Path


class MeasurementLogger:

    def __init__(
        self,
        vehicle_id,
        run_id=None,
        log_directory=None
    ):

        self.vehicle_id = vehicle_id
        self.run_id = run_id
        self.test_id = None

        if log_directory is None:

            log_directory = (
                Path(__file__).resolve().parent
                / "logs"
            )

        else:

            log_directory = Path(
                log_directory
            )


        log_directory.mkdir(
            parents=True,
            exist_ok=True
        )


        timestamp = datetime.now().strftime(
            "%Y-%m-%d_%H-%M-%S"
        )


        self.file_path = (
            log_directory
            / (
                f"measurement_"
                f"{timestamp}_"
                f"vehicle_{vehicle_id}.csv"
            )
        )


        self._file = None
        self._writer = None
        self._fieldnames = None

        self._lock = threading.Lock()

        self.active = False


    def set_test_id(self, test_id):

        self.test_id = test_id


    # ==================================================
    # START
    # ==================================================

    def start(self):

        with self._lock:

            if self.active:
                return


            self._file = open(
                self.file_path,
                "w",
                newline="",
                encoding="utf-8"
            )


            self.active = True


    # ==================================================
    # MESSPUNKT SCHREIBEN
    # ==================================================

    def write_measurement(
        self,
        measurement
    ):

        with self._lock:

            if not self.active:
                return


            row = self._flatten_measurement(
                measurement
            )


            # Beim ersten Messpunkt Header erzeugen
            if self._writer is None:

                self._fieldnames = list(
                    row.keys()
                )


                self._writer = csv.DictWriter(
                    self._file,
                    fieldnames=self._fieldnames,
                    delimiter=";"
                )


                self._writer.writeheader()


            self._writer.writerow(
                row
            )


            # Direkt auf Datenträger schreiben
            self._file.flush()


    # ==================================================
    # MESSPUNKT FLACH MACHEN
    # ==================================================

    def _flatten_measurement(
        self,
        measurement
    ):

        row = {
            "run_id":
                self.run_id,

            "test_id":
                self.test_id,

            "test_type":
                measurement.get(
                    "test_type"
                ),

            "sample_status":
                measurement.get(
                    "sample_status",
                    "ok"
                ),

            "error_type":
                measurement.get(
                    "error_type"
                ),

            "error_message":
                measurement.get(
                    "error_message"
                ),

            "sequence":
                measurement.get(
                    "sequence"
                ),

            "timestamp_ns":
                measurement.get(
                    "timestamp_ns"
                ),

            "timestamp_unix_ns":
                measurement.get(
                    "timestamp_unix_ns"
                ),

            "elapsed_s":
                measurement.get(
                    "elapsed_s"
                ),

            "measurement_interval_s":
                measurement.get(
                    "measurement_interval_s"
                ),

            "vehicle_request_start_ns":
                measurement.get(
                    "vehicle_request_start_ns"
                ),

            "vehicle_response_ns":
                measurement.get(
                    "vehicle_response_ns"
                ),

            "vehicle_read_duration_ms":
                measurement.get(
                    "vehicle_read_duration_ms"
                ),

            "requested_distance_m":
                measurement.get(
                    "requested_distance"
                ),

            "radest_distance_m":
                measurement.get(
                    "radest_distance"
                ),

            "radest_distance_source":
                measurement.get(
                    "radest_distance_source"
                ),

            "estimated_scenario_distance_m":
                measurement.get(
                    "estimated_scenario_distance"
                ),

            "distance_error_m":
                measurement.get(
                    "distance_error"
                ),

            "scenario_start_distance_m":
                measurement.get(
                    "scenario_start_distance"
                ),

            "scenario_end_distance_m":
                measurement.get(
                    "scenario_end_distance"
                ),

            "scenario_velocity_kmh":
                measurement.get(
                    "scenario_velocity_kmh"
                ),

            "scenario_duration_s":
                measurement.get(
                    "scenario_duration_s"
                ),

            "dynamic_pre_hold_s":
                measurement.get(
                    "dynamic_pre_hold_s"
                ),

            "dynamic_post_hold_s":
                measurement.get(
                    "dynamic_post_hold_s"
                ),

            "dynamic_total_duration_s":
                measurement.get(
                    "dynamic_total_duration_s"
                ),

            "dynamic_direction":
                measurement.get(
                    "dynamic_direction"
                ),

            "phase":
                measurement.get(
                    "phase"
                ),

            "phase_elapsed_s":
                measurement.get(
                    "phase_elapsed_s"
                ),

            "sequence_elapsed_s":
                measurement.get(
                    "sequence_elapsed_s"
                ),

            "scenario_elapsed_s":
                measurement.get(
                    "scenario_elapsed_s"
                ),

            "scenario_progress":
                measurement.get(
                    "scenario_progress"
                ),

            "scenario_done":
                measurement.get(
                    "scenario_done"
                ),

            "scenario_trigger_requested_ns":
                measurement.get(
                    "scenario_trigger_requested_ns"
                ),

            "dynamic_sequence_start_ns":
                measurement.get(
                    "dynamic_sequence_start_ns"
                ),

            "scenario_trigger_call_ns":
                measurement.get(
                    "scenario_trigger_call_ns"
                ),

            "scenario_trigger_returned_ns":
                measurement.get(
                    "scenario_trigger_returned_ns"
                )
        }


        # --------------------------------------------------
        # Fahrzeugwerte dynamisch hinzufügen
        # --------------------------------------------------

        vehicle = measurement.get(
            "vehicle",
            {}
        )


        for signal_name, signal in vehicle.items():

            row[
                f"vehicle_{signal_name}"
            ] = signal.get(
                "value"
            )


            row[
                f"vehicle_{signal_name}_unit"
            ] = signal.get(
                "unit"
            )


        return row


    # ==================================================
    # STOP
    # ==================================================

    def stop(self):

        with self._lock:

            if not self.active:
                return


            if self._file is not None:

                self._file.flush()

                self._file.close()


            self._file = None
            self._writer = None

            self.active = False


    # ==================================================
    # DATEINAME
    # ==================================================

    def get_file_path(self):

        return str(
            self.file_path
        )
