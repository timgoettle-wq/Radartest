import csv
import threading
from datetime import datetime
from pathlib import Path


class MeasurementLogger:

    def __init__(
        self,
        vehicle_id,
        log_directory=None
    ):

        self.vehicle_id = vehicle_id

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
            "test_type":
                measurement.get(
                    "test_type"
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

            "requested_distance_m":
                measurement.get(
                    "requested_distance"
                ),

            "radest_distance_m":
                measurement.get(
                    "radest_distance"
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
