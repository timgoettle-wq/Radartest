import json
from datetime import datetime
from pathlib import Path


class TestRun:

    def __init__(
        self,
        vehicle_id,
        base_directory=None
    ):

        self.vehicle_id = vehicle_id

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

            "run_id":
                self.run_id,

            "vehicle_id":
                self.vehicle_id,

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
        log_file
    ):

        # Falls vorher noch ein Test läuft:
        # diesen zuerst abschließen.
        self.finish_active_test()


        test = {

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


        test = {

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


    # ==================================================
    # AKTIVEN TEST ABSCHLIESSEN
    # ==================================================

    def finish_active_test(self):

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
            ] = "finished"


        self.active_test_index = None


        self._save()


    # ==================================================
    # KOMPLETTEN TESTRUN ABSCHLIESSEN
    # ==================================================

    def finish(self):

        self.finish_active_test()


        self.data[
            "end_time"
        ] = self._now()


        self.data[
            "status"
        ] = "finished"


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


    # ==================================================
    # ZEIT
    # ==================================================

    def _now(self):

        return (
            datetime.now()
            .astimezone()
            .isoformat(
                timespec="seconds"
            )
        )