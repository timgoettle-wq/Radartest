import time
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from web import system_time


class SystemTimeTests(unittest.TestCase):

    def client(self, running=False):
        app = FastAPI()
        app.include_router(system_time.make_system_time_router(lambda: running))
        return TestClient(app)

    def test_small_deviation_keeps_clock(self):
        with mock.patch.object(system_time, "set_system_time") as set_time:
            response = self.client().post(
                "/api/system-time", json={"unix_ms": int(time.time() * 1000)}
            )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["changed"])
        set_time.assert_not_called()

    def test_large_deviation_sets_clock(self):
        target_ms = int(time.time() * 1000) + 3600_000
        with mock.patch.object(system_time, "set_system_time") as set_time:
            response = self.client().post(
                "/api/system-time", json={"unix_ms": target_ms}
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["changed"])
        set_time.assert_called_once_with(target_ms / 1000)

    def test_running_measurement_blocks_change(self):
        target_ms = int(time.time() * 1000) + 3600_000
        with mock.patch.object(system_time, "set_system_time") as set_time:
            response = self.client(running=True).post(
                "/api/system-time", json={"unix_ms": target_ms}
            )
        self.assertEqual(response.status_code, 409)
        set_time.assert_not_called()


if __name__ == "__main__":
    unittest.main()
