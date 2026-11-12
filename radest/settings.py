"""Gespeicherte RadEsT-Einstellungen, die der Pruefer selbst festlegt.

Der Airgap (Abstand Radarsensor zur RadEsT-Antenne) ist nach einem Neustart
des RadEsT 0.00 m. Damit liefert die Polarisationsmessung "0,0.00" und die
RCS-Grenzen werden -inf. Deshalb setzt jeder Precheck vorher den hier
gespeicherten Wert. Die Datei liegt nur auf dem Pi und ist nicht im Git.
"""

import json
import math
from pathlib import Path

SETTINGS_FILE = Path(__file__).resolve().parent.parent / "radest_settings.json"

# Wert, den auch die R&S-Software beim Start setzt.
DEFAULT_AIRGAP_M = 0.6
MIN_AIRGAP_M = 0.01
MAX_AIRGAP_M = 10.0


def validate_airgap_m(value):
    try:
        value = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        raise ValueError("Airgap muss eine Zahl in Metern sein.") from None
    if not math.isfinite(value) or not MIN_AIRGAP_M <= value <= MAX_AIRGAP_M:
        raise ValueError(
            f"Airgap muss zwischen {MIN_AIRGAP_M:g} m und {MAX_AIRGAP_M:g} m liegen."
        )
    return round(value, 2)


def _read(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_airgap_m(path=SETTINGS_FILE):
    """Zuletzt festgelegter Airgap in m, sonst 0.6 m."""
    try:
        return validate_airgap_m(_read(path).get("airgap_m", DEFAULT_AIRGAP_M))
    except ValueError:
        return DEFAULT_AIRGAP_M


def save_airgap_m(value, path=SETTINGS_FILE):
    value = validate_airgap_m(value)
    data = _read(path)
    data["airgap_m"] = value
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return value
