"""Kurzer Test der RadEsT-Polarisationserkennung.

Start aus dem Projektordner:
    python demo_scripte/polarization_test.py
"""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from radest.device import RadestDevice


RADEST_IP = "192.168.0.10"
RADEST_PORT = 2101


def main():
    radest = RadestDevice(RADEST_IP, RADEST_PORT)
    connected = False

    try:
        print("Verbindung zum RadEsT wird hergestellt ...")
        connected = radest.connect()

        if not connected:
            raise ConnectionError("Verbindung zum RadEsT fehlgeschlagen.")

        raw_answer = radest.measure_get_polarization_77ghz()

        print("\nPolarisationserkennung:")
        print(f"Rohantwort: {raw_answer!r}")
        print("Felder:", [value.strip() for value in raw_answer.split(",")])

        setting = radest.system_get_polarization_77ghz_setting()

        print("\nAktuelle 77-GHz-Polarisationseinstellung:")
        print(f"Rohantwort: {setting!r}")

    finally:
        if connected:
            radest.disconnect()
            print("\nVerbindung getrennt.")


if __name__ == "__main__":
    main()
