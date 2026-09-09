import json
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from web import results_api


class ResultsApiTests(unittest.TestCase):

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.old_test_runs_dir = results_api.TEST_RUNS_DIR
        results_api.TEST_RUNS_DIR = Path(self.temporary_directory.name)

        run_directory = results_api.TEST_RUNS_DIR / "run-1"
        run_directory.mkdir()
        run = {
            "run_id": "run-1",
            "vehicle_id": 1,
            "vehicle": {
                "manufacturer": "Mercedes-Benz",
                "model": "E-Klasse",
                "generation": "W213",
            },
            "start_time": "2026-09-09T10:00:00+02:00",
            "end_time": "2026-09-09T10:05:00+02:00",
            "status": "finished",
            "software": {"git_commit": "abc123"},
            "quick_check": {
                "identification_summary": {
                    "match": 1,
                    "mismatch": 0,
                    "read_error": 0,
                },
                "dtcs_before": [],
            },
            "precheck": {"status": "completed", "skipped": False},
            "tests": [{
                "test_id": "test-1",
                "type": "dynamic",
                "status": "finished",
                "log_file": "measurement.csv",
                "parameters": {
                    "start_distance_m": 10,
                    "end_distance_m": 5,
                    "velocity_kmh": 5,
                },
            }],
        }
        (run_directory / "run.json").write_text(
            json.dumps(run),
            encoding="utf-8",
        )
        (run_directory / "measurement.csv").write_text(
            "elapsed_s;radest_distance_m;vehicle_distance;distance_error_m;phase;sample_status\n"
            "0.0;10;10.5;0.5;pre_hold;ok\n"
            "0.2;9.5;;;moving;ok\n"
            "0.4;8;0;-8;moving;ok\n",
            encoding="utf-8",
        )

        app = FastAPI()
        app.include_router(results_api.router)
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        results_api.TEST_RUNS_DIR = self.old_test_runs_dir
        self.temporary_directory.cleanup()

    def test_overview_and_detail(self):
        overview = self.client.get("/api/results")
        self.assertEqual(overview.status_code, 200)
        result = overview.json()["results"][0]
        self.assertEqual(result["vehicle_name"], "Mercedes-Benz E-Klasse W213")
        self.assertEqual(result["test_count"], 1)

        detail = self.client.get("/api/results/run-1")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["run"]["software"]["git_commit"], "abc123")

    def test_measurement_metrics_and_downloads(self):
        response = self.client.get("/api/results/run-1/measurements/test-1")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["summary"]["sample_count"], 3)
        self.assertEqual(data["summary"]["valid_distance_points"], 2)
        self.assertEqual(data["summary"]["dropout_count"], 1)
        self.assertAlmostEqual(data["summary"]["mean_absolute_error_m"], 4.25)
        self.assertEqual(data["summary"]["max_absolute_error_m"], 8.0)
        self.assertEqual(data["points"][2]["vehicle_distance_m"], 0.0)

        csv_download = self.client.get(
            "/api/results/run-1/measurements/test-1/download"
        )
        self.assertEqual(csv_download.status_code, 200)
        self.assertIn("radest_distance_m", csv_download.text)

        json_download = self.client.get("/api/results/run-1/download")
        self.assertEqual(json_download.status_code, 200)
        self.assertEqual(json_download.json()["run_id"], "run-1")

    def test_run_directory_cannot_escape_archive(self):
        with self.assertRaises(HTTPException) as context:
            results_api._run_directory("../outside")
        self.assertEqual(context.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
