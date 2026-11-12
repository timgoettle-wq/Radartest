import tempfile
import unittest
from pathlib import Path
from unittest import mock

import test_controller as controller_module
from radest import settings
from test_controller import TestController


class FakeRadest:
    def __init__(self, readback=None):
        self.commands = []
        self.airgap = 0.0
        self.readback = readback

    def set_airgap_distance(self, distance):
        self.commands.append(f"SYSTEM:SET:AIRGAP {distance}")
        self.airgap = float(distance)

    def get_airgap_distance(self):
        return self.airgap if self.readback is None else self.readback


def make_controller(radest):
    controller = TestController.__new__(TestController)
    controller.connected = True
    controller.radest = radest
    controller.test_run = None
    return controller


class PrecheckAirgapTest(unittest.TestCase):

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "radest_settings.json"
        for name, function in (("load_airgap_m", settings.load_airgap_m), ("save_airgap_m", settings.save_airgap_m)):
            patcher = mock.patch.object(
                controller_module, name,
                lambda *args, _f=function: _f(*args, path=self.path),
            )
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_default_airgap_is_set_before_precheck(self):
        radest = FakeRadest()
        result = make_controller(radest).start_precheck()

        self.assertEqual(radest.commands, ["SYSTEM:SET:AIRGAP 0.60"])
        self.assertEqual(result["airgap_m"], 0.6)

    def test_chosen_airgap_is_remembered(self):
        make_controller(FakeRadest()).start_precheck(0.85)
        radest = FakeRadest()
        controller = make_controller(radest)
        controller.start_precheck()

        self.assertEqual(radest.commands, ["SYSTEM:SET:AIRGAP 0.85"])
        self.assertEqual(controller.get_precheck_result()["airgap_m"], 0.85)

    def test_rejects_airgap_that_device_did_not_take(self):
        with self.assertRaisesRegex(RuntimeError, "Airgap"):
            make_controller(FakeRadest(readback=0.0)).start_precheck(0.6)

    def test_rejects_invalid_airgap(self):
        radest = FakeRadest()
        with self.assertRaises(ValueError):
            make_controller(radest).start_precheck(0)
        self.assertEqual(radest.commands, [])


if __name__ == "__main__":
    unittest.main()
