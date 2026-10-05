import unittest

from demo_scripte import vergleichsreihe


class VergleichsreiheTest(unittest.TestCase):

    def test_steps_use_half_attset_grid(self):
        self.assertEqual(
            vergleichsreihe._steps(5.0, 1.0),
            [5.0, 4.5, 4.0, 3.5, 3.0, 2.5, 2.0, 1.5, 1.0],
        )

    def test_plan_is_identical_for_every_vehicle(self):
        first = vergleichsreihe.build_plan()
        second = vergleichsreihe.build_plan()

        self.assertEqual(first, second)
        self.assertEqual(
            [block for block in dict.fromkeys(t["block"] for t in first)],
            ["K1", "S50", "G", "ST", "M1", "H", "K2"],
        )

    def test_control_ladders_match(self):
        plan = vergleichsreihe.build_plan()
        start = [t["target_attset"] for t in plan if t["block"] == "K1"]
        end = [t["target_attset"] for t in plan if t["block"] == "K2"]

        self.assertEqual(start, end)

    def test_safe_name(self):
        self.assertEqual(vergleichsreihe.safe_name("Ford Kuga!"), "Ford_Kuga")


if __name__ == "__main__":
    unittest.main()
