import time
import unittest

from demo_scripte.aeb_pruefstand_test import (
    PassiveCanMonitor,
    StandaloneUdsMonitor,
    decode_signal,
    measurement_fieldnames,
)
from demo_scripte.fahrzeugprofile import (
    PROFILES,
    STANDARD_SIGNALS,
    configured_standard_signals,
    profile_for_vehicle,
    standard_values,
    uds_active,
    uds_signals,
    validate_profile,
)


class VehicleProfileTest(unittest.TestCase):

    def test_all_profiles_are_valid(self):
        for profile in PROFILES:
            validate_profile(profile)

    def test_profile_lookup_by_vehicle_id(self):
        self.assertEqual(profile_for_vehicle(1)["name"], "Mercedes-Benz E-Klasse W213")
        self.assertEqual(profile_for_vehicle(2)["name"], "Ford Mustang Mach-E")
        with self.assertRaises(ValueError):
            profile_for_vehicle(999)

    def test_mercedes_uds_decoding_is_unchanged(self):
        profile = profile_for_vehicle(1)
        monitor = StandaloneUdsMonitor("can0", None, 0.0, profile["uds"], uds_signals(profile))
        wheel_response = bytes.fromhex("62 20 01 03 E8 03 E8 03 E8 03 E8")
        esp_response = bytearray(24)
        esp_response[0:3] = bytes.fromhex("62 20 02")
        esp_response[15:17] = (1000).to_bytes(2, "big", signed=True)
        monitor.latest_responses = {0x2001: wheel_response, 0x2002: bytes(esp_response)}
        monitor.latest_status = {0x2001: "ok", 0x2002: "ok"}

        values = monitor.snapshot()
        values.update(standard_values(profile, values))

        self.assertAlmostEqual(values["wheel_speed_fl"], 10.0)
        self.assertAlmostEqual(values["vehicle_speed"], 10.0)
        self.assertAlmostEqual(values["brake_pressure"], 10.00091556)
        self.assertIsNone(values["brake_pedal_pressed"])

    def test_mercedes_columns_keep_old_names(self):
        fieldnames = measurement_fieldnames(profile_for_vehicle(1))
        for name in ("wheel_speed_fl", "main_brake_pressure", "brake_circuit_2_pressure",
                     "diagnostic_2001_response_hex", *STANDARD_SIGNALS):
            self.assertIn(name, fieldnames)
        self.assertEqual(len(fieldnames), len(set(fieldnames)))

    def test_mustang_placeholders_run_without_values(self):
        profile = profile_for_vehicle(2)
        self.assertFalse(uds_active(profile))
        self.assertEqual(configured_standard_signals(profile), [])

        monitor = PassiveCanMonitor("can0", None, 0.0, {
            name: definition
            for name, definition in profile["signals"].items()
            if definition["source"] == "can"
        })
        values = monitor.snapshot()
        values.update(standard_values(profile, values))
        for name in STANDARD_SIGNALS:
            self.assertIsNone(values[name])

        fieldnames = measurement_fieldnames(profile)
        self.assertIn("brake_pedal_raw", fieldnames)
        self.assertNotIn("wheel_speed_fl", fieldnames)

    def test_can_signal_with_bit(self):
        definition = {"source": "can", "can_id": 0x123, "start_byte": 1, "bit": 3, "bit_length": 1}
        monitor = PassiveCanMonitor("can0", None, 0.0, {"brake_pedal_raw": definition})
        monitor.latest_frames = {0x123: (time.perf_counter(), bytes([0x00, 0b00001000]))}
        self.assertEqual(monitor.snapshot()["brake_pedal_raw"], 1.0)

    def test_decode_bit(self):
        definition = {"start_byte": 0, "bit": 7, "bit_length": 1}
        self.assertEqual(decode_signal(bytes([0x80]), definition), 1.0)
        self.assertEqual(decode_signal(bytes([0x7F]), definition), 0.0)
        self.assertIsNone(decode_signal(bytes([0x80]), {"start_byte": 0, "bit": None}))


if __name__ == "__main__":
    unittest.main()
