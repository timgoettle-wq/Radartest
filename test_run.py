import json
import subprocess
import threading
from datetime import datetime
from pathlib import Path


RESULT_SCHEMA_VERSION = 2


class TestRun:

    def __init__(
        self,
        vehicle_id,
        vehicle_data=None,
        base_directory=None
    ):

        self.vehicle_id = vehicle_id
        self.vehicle_data = vehicle_data
        self._lock = threading.RLock()

        # --------------------------------------------------
        # Basisordner
        # --------------------------------------------------

        if base_directory is None:

            base_directory = (
                Path(__file__).resolve().parent
                / "test_runs"
            )

        else:

            base_directory = Path(
                base_directory
            )


        base_directory.mkdir(
            parents=True,
            exist_ok=True
        )


        # --------------------------------------------------
        # Eindeutige TestRun-ID
        # --------------------------------------------------

        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S_%f"
        )


        self.run_id = (
            f"{timestamp}_vehicle_{vehicle_id}"
        )


        # --------------------------------------------------
        # Eigener Ordner für diesen Prüflauf
        # --------------------------------------------------

        self.directory = (
            base_directory
            / self.run_id
        )


        self.directory.mkdir(
            parents=True,
            exist_ok=True
        )


        self.metadata_file = (
            self.directory
            / "run.json"
        )


        # --------------------------------------------------
        # Interner Zustand
        # --------------------------------------------------

        self.active_test_index = None


        self.data = {

            "schema_version":
                RESULT_SCHEMA_VERSION,

            "run_id":
                self.run_id,

            "vehicle_id":
                self.vehicle_id,

            "vehicle":
                self.vehicle_data,

            "software": {
                "git_commit": self._get_git_commit()
            },

            "start_time":
                self._now(),

            "end_time":
                None,

            "status":
                "running",

            # Später:
            # DTCs, HW/SW-Version usw.
            "quick_check":
                None,

            "precheck":
                None,

            "tests":
                []
        }


        self._save()


    # ==================================================
    # PRECHECK
    # ==================================================

    def set_precheck(
        self,
        result
    ):

        self.data[
            "precheck"
        ] = result


        self._save()


    # ==================================================
    # QUICK CHECK
    #
    # Wird später benutzt für:
    # - Fehlerspeicher
    # - Softwareversion
    # - Hardwareversion
    # ==================================================

    def set_quick_check(
        self,
        result
    ):

        self.data[
            "quick_check"
        ] = result


        self._save()


    # ==================================================
    # STATISCHEN TEST REGISTRIEREN
    # ==================================================

    def start_static_test(
        self,
        requested_distance,
        radest_distance,
        rcs_configuration,
        log_file
    ):

        # Falls vorher noch ein Test läuft:
        # diesen zuerst abschließen.
        self.finish_active_test()


        test_id = self._next_test_id()

        test = {

            "test_id":
                test_id,

            "type":
                "static",

            "start_time":
                self._now(),

            "end_time":
                None,

            "status":
                "running",

            "requested_distance":
                requested_distance,

            "radest_distance":
                radest_distance,

            "rcs":
                rcs_configuration,

            "log_file":
                Path(
                    log_file
                ).name
        }


        self.data[
            "tests"
        ].append(
            test
        )


        self.active_test_index = (
            len(
                self.data["tests"]
            )
            - 1
        )


        self._save()

        return test_id


    # ==================================================
    # DYNAMISCHER TEST
    #
    # Noch nicht verwendet.
    # Ist aber schon vorbereitet.
    # ==================================================

    def start_dynamic_test(
        self,
        parameters,
        log_file
    ):

        self.finish_active_test()


        test_id = self._next_test_id()

        test = {

            "test_id":
                test_id,

            "type":
                "dynamic",

            "start_time":
                self._now(),

            "end_time":
                None,

            "status":
                "running",

            "parameters":
                parameters,

            "log_file":
                Path(
                    log_file
                ).name
        }


        self.data[
            "tests"
        ].append(
            test
        )


        self.active_test_index = (
            len(
                self.data["tests"]
            )
            - 1
        )


        self._save()

        return test_id


    # ==================================================
    # AKTIVEN TEST ERGÄNZEN
    # ==================================================

    def update_active_test(self, values):

        if self.active_test_index is None:
            return

        with self._lock:
            self.data["tests"][self.active_test_index].update(values)
            self._save()


    # ==================================================
    # AKTIVEN TEST ABSCHLIESSEN
    # ==================================================

    def finish_active_test(
        self,
        status="finished",
        reason=None,
        error=None
    ):

        if self.active_test_index is None:
            return


        test = self.data[
            "tests"
        ][
            self.active_test_index
        ]


        if test["status"] == "running":

            test[
                "end_time"
            ] = self._now()


            test[
                "status"
            ] = status

            if reason is not None:
                test["end_reason"] = reason

            if error is not None:
                test["error"] = error


        self.active_test_index = None


        self._save()


    # ==================================================
    # KOMPLETTEN TESTRUN ABSCHLIESSEN
    # ==================================================

    def finish(
        self,
        status=None,
        reason=None
    ):

        self.finish_active_test()


        self.data[
            "end_time"
        ] = self._now()


        if status is None:
            test_statuses = {
                test.get("status")
                for test in self.data["tests"]
            }

            status = (
                "completed_with_errors"
                if "failed" in test_statuses
                else (
                    "aborted"
                    if "aborted" in test_statuses
                    else "finished"
                )
            )

        self.data[
            "status"
        ] = status

        if reason is not None:
            self.data["end_reason"] = reason


        self._save()


    # ==================================================
    # INFORMATIONEN
    # ==================================================

    def get_directory(self):

        return str(
            self.directory
        )


    def get_metadata_file(self):

        return str(
            self.metadata_file
        )


    def get_run_id(self):

        return self.run_id


    # ==================================================
    # SPEICHERN
    # ==================================================

    def _save(self):

        # Erst temporäre Datei schreiben.
        # Danach ersetzen.
        # Dadurch wird run.json nicht halb geschrieben,
        # falls während des Schreibens etwas passiert.

        with self._lock:
            temp_file = (
                self.metadata_file
                .with_suffix(".tmp")
            )


            with open(
                temp_file,
                "w",
                encoding="utf-8"
            ) as file:

                json.dump(
                    self.data,
                    file,
                    indent=4,
                    ensure_ascii=False
                )


            temp_file.replace(
                self.metadata_file
            )


    def _next_test_id(self):

        return (
            f"{self.run_id}_test_"
            f"{len(self.data['tests']) + 1:03d}"
        )


    def _get_git_commit(self):

        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=Path(__file__).resolve().parent,
                capture_output=True,
                text=True,
                check=True,
                timeout=2,
            )
            return result.stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            return None


    # ==================================================
    # ZEIT
    # ==================================================

    def _now(self):

        return (
            datetime.now()
            .astimezone()
            .isoformat(
                timespec="microseconds"
            )
        )
