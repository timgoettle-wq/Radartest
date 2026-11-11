import threading
import unittest
from unittest import mock

from fastapi import HTTPException

from web import app as web_app


class StatusWhileBusyTest(unittest.TestCase):

    def test_status_answers_503_instead_of_hanging(self):
        release = threading.Event()
        holding = threading.Event()

        @web_app.serialized_controller_access
        def run_precheck():
            holding.set()
            release.wait(5)

        worker = threading.Thread(target=run_precheck)
        worker.start()
        self.addCleanup(worker.join, 5)
        self.addCleanup(release.set)
        self.assertTrue(holding.wait(2))

        with mock.patch.object(web_app, "STATUS_LOCK_TIMEOUT_S", 0.1):
            with self.assertRaises(HTTPException) as context:
                web_app.get_system_status()

        self.assertEqual(context.exception.status_code, 503)
        self.assertIn("run_precheck", context.exception.detail)

    def test_status_without_controller(self):
        with mock.patch.object(web_app, "controller", None):
            self.assertEqual(web_app.get_system_status(), {"connected": False})


if __name__ == "__main__":
    unittest.main()
