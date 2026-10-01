import unittest

from demo_scripte import geister_testreihe as reihe


class GeisterTestreiheTest(unittest.TestCase):

    def test_rcs_matches_ford_measurements(self):
        # Ford 1.10.: 15 m / 20 dBsm ergab attSet 2,25 bei Referenz 7,25.
        self.assertEqual(reihe.rcs_for_attset(2.25, 15.0, 7.25), 20.0)
        # Gleicher attSet bei 50 m braucht 40*log10(50/15) dB mehr.
        self.assertEqual(reihe.rcs_for_attset(5.0, 50.0, 7.25), 29.9)

    def test_classifies_ghost_ratios(self):
        self.assertEqual(reihe.classify_ratio(1.02), "1")
        self.assertEqual(reihe.classify_ratio(0.49), "1/2")
        self.assertEqual(reihe.classify_ratio(0.25), "1/4")
        self.assertEqual(reihe.classify_ratio(11.25 / 180), "1/16")
        self.assertEqual(reihe.classify_ratio(0.7), "other")
        self.assertEqual(reihe.classify_ratio(None), "none")

    def test_ignores_carry_over_at_test_start(self):
        samples = [(15.0, 7.5), (15.0, 7.5)] + [(15.0, 15.0)] * 10

        summary = reihe.summarize_samples(samples)

        self.assertFalse(summary["has_ghost"])
        self.assertEqual(summary["counts"]["1/2"], 2)

    def test_reports_first_ghost_and_loss(self):
        samples = (
            [(15.0, 15.0)] * 3
            + [(40.0, 20.0), (44.0, 22.0), (48.0, 12.0)]
            + [(60.0, 200.0), (62.0, 200.0)]
        )

        summary = reihe.summarize_samples(samples)

        self.assertTrue(summary["has_ghost"])
        self.assertEqual(summary["dominant_ghost"], "1/2")
        self.assertEqual(summary["first_ghost_target_m"], 40.0)
        self.assertTrue(summary["has_loss"])
        self.assertEqual(summary["first_loss_target_m"], 60.0)
        self.assertEqual(reihe.result_text(summary), "1/2+Verlust")

    def test_plan_contains_all_blocks(self):
        plan = reihe.build_plan(set("ABCDE"))
        blocks = {test["block"] for test in plan}

        self.assertEqual(blocks, set("ABCDE"))
        approaching = [test for test in plan if test["block"] == "D"]
        self.assertTrue(all(test["attset_distance_m"] == 15 for test in approaching))


if __name__ == "__main__":
    unittest.main()
