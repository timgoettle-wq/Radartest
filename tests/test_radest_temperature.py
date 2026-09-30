import unittest

from test_controller import TestController


class FakeRadest:

    def __init__(self, result):
        self.result = result

    def start_temperature_measurement_detector(self):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def controller_with(radest):
    controller = TestController.__new__(TestController)
    controller.radest = radest
    return controller


class RadestTemperatureTest(unittest.TestCase):

    def test_stores_temperature(self):
        controller = controller_with(FakeRadest(41.234))

        controller._read_radest_temperature()

        self.assertEqual(controller.radest_temperature_c, 41.23)
        self.assertIsNone(controller.radest_temperature_error)

    def test_keeps_error_instead_of_failing(self):
        controller = controller_with(FakeRadest(IndexError("no value")))

        controller._read_radest_temperature()

        self.assertIsNone(controller.radest_temperature_c)
        self.assertEqual(controller.radest_temperature_error, "no value")


if __name__ == "__main__":
    unittest.main()
