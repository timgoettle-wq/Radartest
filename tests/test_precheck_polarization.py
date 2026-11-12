import unittest
from unittest import mock

from test_controller import TestController


def make_controller(measure_answer, setting_answer):
    controller = TestController.__new__(TestController)
    controller._check_connection = lambda: None
    controller.radest = mock.Mock()
    controller.radest.measure_get_polarization_77ghz.return_value = measure_answer
    controller.radest.system_get_polarization_77ghz_setting.return_value = setting_answer
    return controller


class PrecheckPolarizationTest(unittest.TestCase):

    def test_setting_used_when_measure_answer_is_zero(self):
        controller = make_controller("0,0.00", "V")
        result = controller.measure_precheck_polarization()
        self.assertEqual(result["polarization_setting"], "V")
        self.assertEqual((result["tx_antenna"], result["rx_antenna"]), (6, 7))
        controller.radest.system_set_tx.assert_called_once_with(6)
        controller.radest.system_set_rx.assert_called_once_with(7)
        controller.radest.system_set_polarization_77ghz.assert_not_called()

    def test_diagonal_setting_selects_group_five(self):
        controller = make_controller("0,0.00", "M45")
        result = controller.measure_precheck_polarization()
        self.assertEqual(result["polarization_setting"], "M45")
        self.assertEqual((result["tx_antenna"], result["rx_antenna"]), (5, 5))

    def test_numeric_and_verbose_setting_answers(self):
        for answer, expected in [("5", "H"), ("7,0", "P45"), ("POLARIZATION:77GHZ:-45", "M45"), ('"H"', "H")]:
            with self.subTest(answer=answer):
                controller = make_controller("0,0.00", answer)
                self.assertEqual(controller.measure_precheck_polarization()["polarization_setting"], expected)

    def test_falls_back_to_measure_answer(self):
        controller = make_controller("8,-18.5", "")
        self.assertEqual(controller.measure_precheck_polarization()["polarization_setting"], "V")

    def test_unknown_answers_show_both_raw_values(self):
        controller = make_controller("0,0.00", "XYZ")
        with self.assertRaises(RuntimeError) as context:
            controller.measure_precheck_polarization()
        self.assertIn("0,0.00", str(context.exception))
        self.assertIn("XYZ", str(context.exception))
        controller.radest.system_set_tx.assert_not_called()


if __name__ == "__main__":
    unittest.main()
