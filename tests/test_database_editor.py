import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
import database.database as database
import web.database_api as editor


class DatabaseEditorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = database.DB_PATH
        database.DB_PATH = Path(self.temp.name) / "radar_test.db"
        shutil.copy2(self.old_path, database.DB_PATH)
        self.editor_path = editor.DB_PATH
        editor.DB_PATH = database.DB_PATH
        self.locked = False
        app = FastAPI()
        app.include_router(editor.make_database_router(threading.RLock(), lambda: self.locked))
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        database.DB_PATH = self.old_path
        editor.DB_PATH = self.editor_path
        self.temp.cleanup()

    def test_crud_backup_and_lock(self):
        data = self.client.get("/api/database").json()
        self.assertEqual(len(data["tables"]), 7)
        payload = dict(manufacturer="Test", model="Test", generation=None,
                       year_from=2020, year_to=None, description=None)
        self.assertEqual(self.client.post("/api/database/vehicles", json=payload).status_code, 200)
        row = self.client.get("/api/database").json()["tables"]["vehicles"]["rows"][-1]
        self.assertTrue(list((database.DB_PATH.parent / "backups").glob("*.db")))
        payload["model"] = "Updated"
        url = "/api/database/vehicles/" + str(row["id"])
        self.assertEqual(self.client.put(url, json=payload).status_code, 200)
        self.locked = True
        self.assertEqual(self.client.delete(url).status_code, 409)
        self.locked = False
        self.assertEqual(self.client.delete(url).status_code, 200)

    def test_constraints(self):
        data = self.client.get("/api/database").json()
        ecu = data["tables"]["ecus"]["rows"][0]
        self.assertEqual(self.client.delete("/api/database/vehicles/" + str(ecu["vehicle_id"])).status_code, 422)
        payload = {key: value for key, value in ecu.items() if key != "id"}
        payload["request_id"] = "0xFFFF"
        self.assertEqual(self.client.put("/api/database/ecus/" + str(ecu["id"]), json=payload).status_code, 422)
        self.assertEqual(self.client.post("/api/database/sqlite_sequence", json={}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
