import csv
import tempfile
import unittest
from pathlib import Path

from demo_scripte.aeb_pruefstand_test import save_precheck


class SavePrecheckTest(unittest.TestCase):
    def test_every_precheck_is_appended(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sub" / "aeb_prechecks.csv"
            first = save_precheck(
                1,
                {"skipped": False, "polarization": "5", "frequency_range": "76-77", "power": "20.1"},
                path,
            )
            save_precheck(1, {"skipped": False, "polarization": "8", "frequency_range": "76-81", "power": "19.5"}, path)
            save_precheck(2, {"status": "skipped", "skipped": True}, path)

            with path.open(encoding="utf-8") as file:
                rows = list(csv.DictReader(file, delimiter=";"))

        self.assertEqual(first["polarization"], "5")
        self.assertIn("time", first)
        self.assertEqual(len(rows), 3)
        self.assertEqual([row["polarization"] for row in rows], ["5", "8", ""])
        self.assertEqual(rows[2]["status"], "uebersprungen")
        self.assertEqual(rows[2]["vehicle_id"], "2")


if __name__ == "__main__":
    unittest.main()
