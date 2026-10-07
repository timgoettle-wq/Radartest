import unittest

from demo_scripte import aeb_pruefstand_web as web


class FakeController:
    def run_precheck(self):
        return {"status": "completed", "skipped": False, "polarization": "5", "frequency_range": "76-77", "power": "20"}

    def skip_precheck(self):
        return {"status": "skipped", "skipped": True}


class ExclusiveSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.saved = []
        self.original_save = web.save_precheck
        web.save_precheck = lambda vehicle_id, result: self.saved.append(result) or result

    def tearDown(self):
        web.save_precheck = self.original_save

    def test_precheck_response_is_not_busy(self):
        runner = web.AebWebRunner()
        runner.controller = FakeController()
        runner.vehicle_id = 1
        for skip in (False, True):
            snapshot = runner.run_precheck(skip)
            self.assertIsNone(snapshot["busy"])
            self.assertEqual(snapshot["sequence"], runner.snapshot()["sequence"])
        self.assertEqual(len(self.saved), 2)


if __name__ == "__main__":
    unittest.main()
