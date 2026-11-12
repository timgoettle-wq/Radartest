import unittest
from unittest import mock

from test_controller import TestController


def make_controller(answers):
    controller = TestController.__new__(TestController)
    controller._check_connection = lambda: None
    controller.radest = mock.Mock()
    controller.radest.measure_get_polarization_77ghz.side_effect = list(answers)
    controller.POLARIZATION_RETRY_DELAY_S = 0
    return controller


class PrecheckPolarizationTest(unittest.TestCase):

    def test_known_code_sets_polarization(self):
        controller = make_controller(["5,-20.31"])
        result = controller.measure_precheck_polarization()
        self.assertEqual(result["polarization_setting"], "H")
        controller.radest.system_set_polarization_77ghz.assert_called_once_with("H")

    def test_no_signal_is_retried(self):
        controller = make_controller(["0,0.00", "0,0.00", "8,-18.5"])
        result = controller.measure_precheck_polarization()
        self.assertEqual(result["polarization_setting"], "V")
        self.assertEqual(controller.radest.measure_get_polarization_77ghz.call_count, 3)

    def test_no_signal_gives_clear_error(self):
        controller = make_controller(["0,0.00"] * 3)
        with self.assertRaises(RuntimeError) as context:
            controller.measure_precheck_polarization()
        self.assertIn("kein Radarsignal", str(context.exception))
        controller.radest.system_set_polarization_77ghz.assert_not_called()

    def test_unknown_code_is_not_retried(self):
        controller = make_controller(["9,1.00"])
        with self.assertRaises(RuntimeError) as context:
            controller.measure_precheck_polarization()
        self.assertIn("Unbekannte Polarisationsantwort", str(context.exception))
        self.assertEqual(controller.radest.measure_get_polarization_77ghz.call_count, 1)


if __name__ == "__main__":
    unittest.main()
