"""Pruefstandsprofil Ford Mustang Mach-E.

Die ESP-/Bremssignale werden noch per Reverse Engineering ermittelt. Alle Werte
mit "None" sind Platzhalter (TODO). Solange start_byte bzw. can_id auf None
steht, bleibt die zugehoerige Spalte leer; der Test laeuft trotzdem und
can_raw.csv enthaelt alle Frames fuer die Auswertung.

Signalquellen:
  "can": passiv mitgelesener CAN-Frame, start_byte zaehlt ab Datenbyte 0.
  "uds": Antwort auf 22 DID, start_byte 3 ist das erste Datenbyte nach
         "62 DID_H DID_L" (wie beim W213).
Bitsignale: "bit" (0 = niederwertigstes Bit von start_byte) und "bit_length".
"""


PROFILE = {
    "name": "Ford Mustang Mach-E",
    "vehicle_ids": (2,),
    "uds": {
        "enabled": True,
        "request_id": 0x760,
        "response_id": 0x768,
        "service": 0x22,
        "dids": (0xDD09, 0x2B0D, 0x2B11, 0x2B0B),
        "tx_padding": 0x00,
    },
    "signals": {
        "vehicle_speed_raw": {
        "source": "uds",
        "did": 0xDD09,
        "start_byte": 3,
        "length": 1, "byte_order": "big", "signed": False,
        "factor": 1.0, "offset": 0.0, "unit": "km/h",
        },
        "brake_pressure_raw": {
        "source": "uds",
        "did": 0x2B0D,
        "start_byte": 3,  
        "length": 2, "byte_order": "big", "signed": True,
        "factor": 0.333332316, "offset": 0.0, "unit": "bar",
        },
        "longitudinal_acceleration_car": {
        "source": "uds",
        "did": 0x2B11,
        "start_byte": 3,  
        "length": 2, "byte_order": "big", "signed": True,
        "factor": 0.00980665, "offset": 0.0, "unit": "m/s^2",
        },
        "yaw_rate_car": {
        "source": "uds",
        "did": 0x2B0B,
        "start_byte": 3,  
        "length": 2, "byte_order": "big", "signed": True,
        "factor": 0.2, "offset": 0.0, "unit": "deg/s",
        },
    },

    "standard": {
        "vehicle_speed": {"from": "vehicle_speed_raw"},
        "brake_pressure": {"from": "brake_pressure_raw"},
        "brake_pedal_pressed": None,
        "longitudinal_acceleration": {"from": "longitudinal_acceleration_car"}, 
        "steering_angle": None,  
        "yaw_rate": {"from": "yaw_rate_car"},  
    },
    "brake_onset": {
        "pressure_bar": 2.0,
        "deceleration_mps2": -1.5,
    },
}
