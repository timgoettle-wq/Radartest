"""Pruefstandsprofil Mercedes-Benz E-Klasse W213.

ESP-Diagnosedaten aus den mitgeschnittenen Diagnosetests:
  0x7E2  22 20 01 -> 0x7EA  62 20 01 ...  (Raddrehzahlen)
  0x7E2  22 20 02 -> 0x7EA  62 20 02 ...  (Brems-/ESP-Sensoren)
"""


def _uds(did, start_byte, signed, factor, unit):
    return {
        "source": "uds",
        "did": did,
        "start_byte": start_byte,
        "length": 2,
        "byte_order": "big",
        "signed": signed,
        "factor": factor,
        "offset": 0.0,
        "unit": unit,
    }


PROFILE = {
    "name": "Mercedes-Benz E-Klasse W213",
    "vehicle_ids": (1,),
    "uds": {
        "enabled": True,
        "request_id": 0x7E2,
        "response_id": 0x7EA,
        "service": 0x22,
        "dids": (0x2001, 0x2002),
        "tx_padding": 0x00,
    },
    "signals": {
        "wheel_speed_fl": _uds(0x2001, 3, False, 0.01, "km/h"),
        "wheel_speed_fr": _uds(0x2001, 5, False, 0.01, "km/h"),
        "wheel_speed_rl": _uds(0x2001, 7, False, 0.01, "km/h"),
        "wheel_speed_rr": _uds(0x2001, 9, False, 0.01, "km/h"),
        "main_brake_pressure": _uds(0x2002, 15, True, 0.01000091556, "bar"),
        "brake_circuit_2_pressure": _uds(0x2002, 18, True, 0.01000091556, "bar"),
        "steering_angle": _uds(0x2002, 12, True, 0.04375133518, "deg"),
        "longitudinal_acceleration": _uds(0x2002, 3, True, 0.0980999176, "m/s^2"),
        "lateral_acceleration": _uds(0x2002, 6, True, 0.0980999176, "m/s^2"),
        "yaw_rate": _uds(0x2002, 9, True, 0.002859889523, "deg/s"),
    },
    "standard": {
        "vehicle_speed": {
            "mean_of": ("wheel_speed_fl", "wheel_speed_fr", "wheel_speed_rl", "wheel_speed_rr"),
        },
        "brake_pressure": {"from": "main_brake_pressure"},
        "brake_pedal_pressed": None,
        "longitudinal_acceleration": {"from": "longitudinal_acceleration"},
        "steering_angle": {"from": "steering_angle"},
        "yaw_rate": {"from": "yaw_rate"},
    },
    "brake_onset": {
        "pressure_bar": 2.0,
        "deceleration_mps2": -1.5,
    },
}
