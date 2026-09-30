"""Fahrzeugprofile fuer den AEB-Rollenpruefstandstest.

Jedes Profil beschreibt, wie die ESP-/Bremswerte eines Fahrzeugs gelesen
werden (UDS-Adressen, DIDs, CAN-IDs, Bytepositionen, Faktoren) und wie daraus
die fahrzeugunabhaengigen Standardsignale entstehen. Die Pruefstandsskripte
verwenden fuer Anzeige, Diagramm und Bremsbeginn nur die Standardsignale.

Neues Fahrzeug: Profildatei anlegen und unten in PROFILES eintragen. Die
Zuordnung erfolgt ueber die Vehicle-ID aus der Datenbank.
"""

from . import ford_mustang_mache, mercedes_w213


PROFILES = (
    mercedes_w213.PROFILE,
    ford_mustang_mache.PROFILE,
)

# Standardsignal -> Einheit. Diese Spalten stehen immer in der Mess-CSV.
STANDARD_SIGNALS = {
    "vehicle_speed": "km/h",
    "brake_pressure": "bar",
    "brake_pedal_pressed": "",
    "longitudinal_acceleration": "m/s^2",
    "steering_angle": "deg",
    "yaw_rate": "deg/s",
}


def validate_profile(profile):
    signals = profile.get("signals", {})
    for name, definition in signals.items():
        if definition.get("source") not in {"uds", "can"}:
            raise ValueError(f"{profile['name']}: Signal '{name}' braucht source 'uds' oder 'can'.")

    for name, rule in profile.get("standard", {}).items():
        if name not in STANDARD_SIGNALS:
            raise ValueError(f"{profile['name']}: Unbekanntes Standardsignal '{name}'.")
        if rule is None:
            continue
        sources = rule.get("mean_of") or (rule.get("from"),)
        for source in sources:
            if source not in signals:
                raise ValueError(
                    f"{profile['name']}: Standardsignal '{name}' verweist auf unbekanntes Signal '{source}'."
                )

    # Ein Rohsignal darf nur dann wie ein Standardsignal heissen, wenn es
    # dieses unveraendert liefert. Sonst waere die CSV-Spalte doppeldeutig.
    for name in signals:
        if name in STANDARD_SIGNALS:
            rule = profile.get("standard", {}).get(name)
            if rule != {"from": name}:
                raise ValueError(
                    f"{profile['name']}: Rohsignal '{name}' kollidiert mit dem gleichnamigen Standardsignal."
                )


def profile_for_vehicle(vehicle_id):
    for profile in PROFILES:
        if vehicle_id in profile["vehicle_ids"]:
            validate_profile(profile)
            return profile
    raise ValueError(f"Kein Pruefstandsprofil fuer Vehicle-ID {vehicle_id} vorhanden.")


def uds_signals(profile):
    return {
        name: definition
        for name, definition in profile["signals"].items()
        if definition["source"] == "uds"
    }


def can_signals(profile):
    return {
        name: definition
        for name, definition in profile["signals"].items()
        if definition["source"] == "can"
    }


def uds_active(profile):
    uds = profile["uds"]
    return bool(
        uds.get("enabled")
        and uds.get("request_id") is not None
        and uds.get("response_id") is not None
        and uds.get("dids")
    )


def uds_dids(profile):
    return tuple(profile["uds"]["dids"]) if uds_active(profile) else ()


def standard_values(profile, values):
    result = {}
    for name in STANDARD_SIGNALS:
        rule = profile.get("standard", {}).get(name)
        if rule is None:
            result[name] = None
        elif "mean_of" in rule:
            available = [values.get(source) for source in rule["mean_of"] if values.get(source) is not None]
            result[name] = sum(available) / len(available) if available else None
        else:
            result[name] = values.get(rule["from"])
    return result


def configured_standard_signals(profile):
    """Standardsignale, deren Quelle vollstaendig konfiguriert ist."""
    configured = []
    for name in STANDARD_SIGNALS:
        rule = profile.get("standard", {}).get(name)
        if rule is None:
            continue
        sources = rule.get("mean_of") or (rule["from"],)
        if any(_signal_configured(profile, profile["signals"][source]) for source in sources):
            configured.append(name)
    return configured


def _signal_configured(profile, definition):
    if definition.get("start_byte") is None:
        return False
    if "bit" in definition and definition["bit"] is None:
        return False
    if definition["source"] == "can":
        return definition.get("can_id") is not None
    return uds_active(profile) and definition.get("did") in profile["uds"]["dids"]


def profile_summary(profile):
    configured = configured_standard_signals(profile)
    uds_text = "UDS an" if uds_active(profile) else "UDS aus"
    return (
        f"Profil {profile['name']}, {uds_text}, "
        f"{len(configured)} von {len(STANDARD_SIGNALS)} Standardsignalen konfiguriert"
    )
