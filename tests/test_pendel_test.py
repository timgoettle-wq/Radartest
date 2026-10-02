import unittest

from demo_scripte import pendel_test


class PendelTestTest(unittest.TestCase):

    def test_builds_legs_from_start_and_cycles(self):
        legs = pendel_test.build_legs(15.0, 35.0, 25.0, 2)

        self.assertEqual(
            legs,
            [(15.0, 35.0), (35.0, 25.0), (25.0, 35.0), (35.0, 25.0), (25.0, 35.0)],
        )

    def test_snapshot_interpolates_current_leg(self):
        state = pendel_test.PendelState(15.0, 36.0)  # 10 m/s

        state.start_leg(1, 35.0, 25.0, trigger_ns=0)
        snap = state.snapshot(now_ns=500_000_000)

        self.assertEqual(snap["phase"], "hin_1")
        self.assertEqual(snap["direction"], "approaching")
        self.assertAlmostEqual(snap["target_m"], 30.0)

    def test_snapshot_holds_end_distance_while_turning(self):
        state = pendel_test.PendelState(15.0, 36.0)
        state.start_leg(0, 15.0, 35.0, trigger_ns=0)

        state.finish_leg()
        snap = state.snapshot(now_ns=state.phase_start_ns)

        self.assertEqual(snap["phase"], "umkehr")
        self.assertEqual(snap["target_m"], 35.0)


if __name__ == "__main__":
    unittest.main()
