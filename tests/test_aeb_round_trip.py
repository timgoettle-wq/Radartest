import threading
import unittest

from demo_scripte.aeb_pruefstand_test import (
    RadestScenarioRunner,
    dynamic_movement_duration,
    expected_dynamic_distance,
    prepare_return_leg,
)


class FakeRadest:
    def __init__(self):
        self.calls = []
        self.start = 40.0
        self.end = 5.0
        self.trigger_started = threading.Event()

    def scenario_trigger(self):
        self.calls.append(("trigger", self.start, self.end))
        self.trigger_started.set()

    def scenario_distance_start(self, value):
        self.calls.append(("start", value))
        self.start = value

    def scenario_distance_end(self, value):
        self.calls.append(("end", value))
        self.end = value

    def scenario_get_distance_start(self):
        return self.start

    def scenario_get_distance_end(self):
        return self.end

    def scenario_get_velocity(self):
        return 10.0

    def scenario_set_rcs(self, rcs):
        self.calls.append(("rcs", rcs))


class FakeController:
    def __init__(self):
        self.radest = FakeRadest()


def scenario(round_trip):
    return {
        "type": "dynamic",
        "round_trip": round_trip,
        "actual": {"start_distance_m": 40.0, "end_distance_m": 5.0, "velocity_kmh": 10.0},
    }


class AebRoundTripTest(unittest.TestCase):

    def test_return_leg_swaps_distances_without_new_rcs(self):
        controller = FakeController()
        leg = prepare_return_leg(controller, scenario(True)["actual"])

        self.assertEqual(leg["start_distance_m"], 5.0)
        self.assertEqual(leg["end_distance_m"], 40.0)
        self.assertNotIn("rcs", [call[0] for call in controller.radest.calls])
        self.assertEqual(expected_dynamic_distance(leg, 0.0), 5.0)
        self.assertEqual(expected_dynamic_distance(leg, dynamic_movement_duration(leg)), 40.0)

    def test_round_trip_triggers_return_directly(self):
        controller = FakeController()
        runner = RadestScenarioRunner(controller, scenario(True))
        runner.start()
        runner.join(2.0)

        self.assertFalse(runner.is_alive())
        self.assertIsNone(runner.error)
        self.assertTrue(runner.return_started.is_set())
        self.assertEqual(runner.wait_for_return()["end_distance_m"], 40.0)
        triggers = [call for call in controller.radest.calls if call[0] == "trigger"]
        self.assertEqual(triggers, [("trigger", 40.0, 5.0), ("trigger", 5.0, 40.0)])

    def test_single_direction_triggers_once(self):
        controller = FakeController()
        runner = RadestScenarioRunner(controller, scenario(False))
        runner.start()
        runner.join(2.0)

        self.assertFalse(runner.is_alive())
        self.assertEqual([call[0] for call in controller.radest.calls], ["trigger"])

    def test_stop_during_outbound_skips_return(self):
        controller = FakeController()
        stop_event = threading.Event()
        stop_event.set()
        runner = RadestScenarioRunner(controller, scenario(True), stop_event)
        runner.start()
        runner.join(2.0)

        self.assertFalse(runner.is_alive())
        self.assertEqual([call[0] for call in controller.radest.calls], ["trigger"])
        with self.assertRaises(RuntimeError):
            runner.wait_for_return()


if __name__ == "__main__":
    unittest.main()
