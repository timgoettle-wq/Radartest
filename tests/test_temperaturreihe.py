import unittest

from demo_scripte import temperaturreihe as tr


class TemperaturreiheTest(unittest.TestCase):

    def test_ladder_steps(self):
        self.assertEqual(tr.ladder_steps(2.0), [2.0, 1.5, 1.0, 0.5])
        self.assertEqual(tr.ladder_steps(6.0)[0], 6.0)
        self.assertEqual(tr.ladder_steps(6.0)[-1], 0.5)

    def test_next_ladder_top_starts_above_last_threshold(self):
        self.assertEqual(tr.next_ladder_top(None), 6.0)
        self.assertEqual(tr.next_ladder_top(1.5), 3.5)
        self.assertEqual(tr.next_ladder_top(5.0), 6.0)

    def test_threshold_from_results(self):
        results = [(3.0, False), (2.5, False), (2.0, True), (1.5, True)]
        self.assertEqual(tr.threshold_from_results(results), (2.5, 2.0))
        self.assertEqual(tr.threshold_from_results([(3.0, False)]), (3.0, None))
        self.assertEqual(tr.threshold_from_results([(3.0, True)]), (None, 3.0))

    def test_temperature_is_stable(self):
        self.assertFalse(tr.temperature_is_stable([30.0, 34.0]))
        self.assertFalse(tr.temperature_is_stable([33.0, 35.0, 36.0]))
        self.assertTrue(tr.temperature_is_stable([30.0, 37.9, 38.0, 38.1]))
        self.assertFalse(tr.temperature_is_stable([37.9, None, 38.0]))


if __name__ == "__main__":
    unittest.main()
