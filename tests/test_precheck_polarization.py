import unittest
from unittest import mock

from test_controller import TestController


def make_controller(measure_answer):
    controller = TestController.__new__(TestController)
    controller._check_connection = lambda: None
    controller.radest = mock.Mock()
    controller.radest.measure_get_polarization_77ghz.return_value = measure_answer
    return controller


class PrecheckPolarizationTest(unittest.TestCase):

    def test_rs_software_answer_sets_vertical(self):
        controller = make_controller("8,77.00")
        result = controller.measure_precheck_polarization()
        self.assertEqual(result["polarization_setting"], "V")
        controller.radest.system_set_polarization_77ghz.assert_called_once_with("V")
        controller.radest.system_set_tx.assert_called_once_with(6)
        controller.radest.system_set_rx.assert_called_once_with(7)

    def test_diagonal_selects_group_five(self):
        controller = make_controller("6,77.00")
        result = controller.measure_precheck_polarization()
        self.assertEqual(result["polarization_setting"], "M45")
        self.assertEqual((result["tx_antenna"], result["rx_antenna"]), (5, 5))

    def test_manual_text_answers(self):
        for answer, expected in [("V", "V"), ('"H"', "H"), ("P45", "P45")]:
            with self.subTest(answer=answer):
                controller = make_controller(answer)
                self.assertEqual(controller.measure_precheck_polarization()["polarization_setting"], expected)

    def test_no_signal_gives_clear_error_and_sets_nothing(self):
        controller = make_controller("0,0.00")
        with self.assertRaises(RuntimeError) as context:
            controller.measure_precheck_polarization()
        self.assertIn("keine Polarisation erkannt", str(context.exception))
        controller.radest.system_set_polarization_77ghz.assert_not_called()
        controller.radest.system_set_tx.assert_not_called()
        controller.radest.system_get_polarization_77ghz_setting.assert_not_called()

    def test_unknown_answer(self):
        controller = make_controller("9,77.00")
        with self.assertRaises(RuntimeError) as context:
            controller.measure_precheck_polarization()
        self.assertIn("Unbekannte Polarisationsantwort", str(context.exception))


class RcsLimitsTest(unittest.TestCase):

    def test_valid_limits(self):
        limits = TestController._parse_rcs_limits("V,20.5,-10.0,40.0")
        self.assertEqual(limits["eirp_dbm"], 20.5)

    def test_minus_inf_gives_clear_error(self):
        with self.assertRaises(RuntimeError) as context:
            TestController._parse_rcs_limits("V,-inf,-inf,-inf")
        self.assertIn("keine Radarleistung", str(context.exception))


if __name__ == "__main__":
    unittest.main()
