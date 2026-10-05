import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from database import database
from web import results_api, vehicle_overview


class VehicleOverviewTests(unittest.TestCase):

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        base = Path(self.temporary_directory.name)

        self.old_db_path = database.DB_PATH
        self.old_test_runs_dir = results_api.TEST_RUNS_DIR
        database.DB_PATH = base / "test.db"
        results_api.TEST_RUNS_DIR = base / "test_runs"

        connection = sqlite3.connect(database.DB_PATH)
        connection.executescript("""
            CREATE TABLE vehicles (id INTEGER PRIMARY KEY, manufacturer TEXT,
                model TEXT, generation TEXT, year_from INTEGER, year_to INTEGER,
                description TEXT);
            CREATE TABLE ecus (id INTEGER PRIMARY KEY, vehicle_id INTEGER,
                name TEXT, interface TEXT, channel TEXT, bitrate INTEGER,
                request_id INTEGER, response_id INTEGER, transport TEXT,
                tx_padding INTEGER);
            CREATE TABLE diagnostic_parameters (id INTEGER PRIMARY KEY,
                ecu_id INTEGER, name TEXT, service INTEGER, did INTEGER);
            INSERT INTO vehicles VALUES (1, 'Mercedes-Benz', 'E-Klasse', 'W213', 2016, 2023, NULL);
            INSERT INTO ecus VALUES (1, 1, 'Front Radar', 'can', 'can0', 500000, 1857, 1825, 'isotp', 0);
            INSERT INTO diagnostic_parameters VALUES (1, 1, 'Objekt', 34, 4096);
        """)
        connection.close()

        self.write_run("old", "2026-09-01T10:00:00+02:00", {
            "skipped": False, "polarization": "5",
            "frequency_range": ["76.0", "77.0"], "power": "-20.0",
        })
        self.write_run("new", "2026-09-02T10:00:00+02:00", {"skipped": True})
        self.write_run("other", "2026-09-03T10:00:00+02:00", {}, vehicle_id=2)

        app = FastAPI()
        app.include_router(vehicle_overview.router)
        self.client = TestClient(app)

    def tearDown(self):
        database.DB_PATH = self.old_db_path
        results_api.TEST_RUNS_DIR = self.old_test_runs_dir
        self.temporary_directory.cleanup()

    def write_run(self, run_id, start_time, precheck, vehicle_id=1):
        directory = results_api.TEST_RUNS_DIR / run_id
        directory.mkdir(parents=True)
        (directory / "run.json").write_text(json.dumps({
            "run_id": run_id,
            "vehicle_id": vehicle_id,
            "start_time": start_time,
            "precheck": precheck,
            "tests": [{"test_id": "t1", "type": "static"}],
        }), encoding="utf-8")

    def test_overview_combines_database_and_runs(self):
        response = self.client.get("/api/vehicles/1/overview")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["vehicle"]["generation"], "W213")
        self.assertEqual(data["ecus"][0]["name"], "Front Radar")
        self.assertEqual(data["ecus"][0]["parameter_count"], 1)
        self.assertEqual(data["run_count"], 2)
        self.assertEqual(data["last_run"]["run_id"], "new")
        # Der neueste Precheck wurde uebersprungen, also kommen die Werte vom aelteren.
        self.assertEqual(data["last_precheck"]["run_id"], "old")
        self.assertEqual(data["last_precheck"]["power"], "-20.0")

    def test_runs_are_sorted_by_instant_not_text(self):
        # 02:15+01:00 liegt nach 02:30+02:00 (Zeitumstellung).
        self.write_run("summer", "2026-10-25T02:30:00+02:00", {"skipped": True})
        self.write_run("winter", "2026-10-25T02:15:00+01:00", {"skipped": True})

        data = self.client.get("/api/vehicles/1/overview").json()

        self.assertEqual(data["last_run"]["run_id"], "winter")

    def test_unknown_vehicle_returns_404(self):
        response = self.client.get("/api/vehicles/99/overview")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
