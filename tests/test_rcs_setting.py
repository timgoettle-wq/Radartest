import unittest

from test_controller import TestController


class RcsSettingParserTest(unittest.TestCase):

    def test_parses_working_point_answer(self):
        answer = (
            '"setRCS = 41.80, maxRCS = 53.74, minRCS = 29.86, '
            'currentEIRP = -14.44, currentTx = 6, txValue = 10.50, '
            'attSet = 2.75, uiIdx = 53, startRCS = 53.74!"'
        )

        setting = TestController._parse_rcs_setting(answer)

        self.assertEqual(setting["raw_answer"], answer)
        self.assertEqual(setting["values"]["txValue"], 10.5)
        self.assertEqual(setting["values"]["attSet"], 2.75)
        self.assertEqual(setting["values"]["currentEIRP"], -14.44)
        self.assertEqual(setting["values"]["currentTx"], 6.0)

    def test_keeps_unknown_answer_without_values(self):
        setting = TestController._parse_rcs_setting('0,"OK"')

        self.assertEqual(setting["raw_answer"], '0,"OK"')
        self.assertEqual(setting["values"], {})

    def test_handles_missing_answer(self):
        setting = TestController._parse_rcs_setting(None)

        self.assertIsNone(setting["raw_answer"])
        self.assertEqual(setting["values"], {})


if __name__ == "__main__":
    unittest.main()
