import sqlite3
import time
from pathlib import Path

from diagnostics.vehicle import VehicleDiagnostic
from radest.device import RadestDevice


# --------------------------------------------------
# Einstellungen
# --------------------------------------------------

DATABASE_PATH = (
    Path(__file__).parent
    / "database"
    / "radar_test.db"
)

RADEST_IP = "192.168.0.10"
RADEST_PORT = 2101

MEASUREMENT_INTERVAL = 0.5


# Standardisierte Signale, die wir versuchen zu lesen
RADAR_SIGNALS = [
    "distance",
    "angle",
    "relative_speed",
    "relative_acceleration"
]


# --------------------------------------------------
# Fahrzeuge aus SQLite laden
# --------------------------------------------------

def get_vehicles():
    connection = sqlite3.connect(
        DATABASE_PATH
    )

    connection.row_factory = sqlite3.Row

    cursor = connection.cursor()

    cursor.execute(
        "SELECT * FROM vehicles ORDER BY id"
    )

    vehicles = [
        dict(row)
        for row in cursor.fetchall()
    ]

    connection.close()

    return vehicles


def get_vehicle_display_name(vehicle):
    """
    Versucht aus den vorhandenen DB-Spalten
    einen sinnvollen Fahrzeugnamen zu erzeugen.

    Funktioniert z. B. mit:
    name
    oder
    manufacturer + model
    oder
    brand + model
    """

    if vehicle.get("name"):
        return vehicle["name"]

    parts = []

    for column in [
        "manufacturer",
        "brand",
        "make",
        "model",
        "variant"
    ]:
        value = vehicle.get(column)

        if value and value not in parts:
            parts.append(str(value))

    if parts:
        return " ".join(parts)

    return f"Fahrzeug ID {vehicle['id']}"


def select_vehicle():
    vehicles = get_vehicles()

    if not vehicles:
        raise RuntimeError(
            "Keine Fahrzeuge in der Datenbank gefunden"
        )

    print("\nVerfügbare Fahrzeuge:")
    print("---------------------")

    for index, vehicle in enumerate(
        vehicles,
        start=1
    ):
        name = get_vehicle_display_name(
            vehicle
        )

        print(
            f"{index}: {name} "
            f"(ID {vehicle['id']})"
        )

    while True:
        try:
            selection = int(
                input(
                    "\nFahrzeug auswählen: "
                )
            )

            if (
                1
                <= selection
                <= len(vehicles)
            ):
                return vehicles[
                    selection - 1
                ]

        except ValueError:
            pass

        print(
            "Ungültige Auswahl."
        )


# --------------------------------------------------
# RadEsT Precheck
# --------------------------------------------------

def run_radest_precheck(radest):

    print("\n")
    print("=" * 50)
    print("RADEST PRECHECK")
    print("=" * 50)

    # ----------------------------------------------
    # 1. Polarisation
    # ----------------------------------------------

    print(
        "\n1. Polarisation wird bestimmt..."
    )

    polarization = (
        radest.measure_get_polarization_77ghz()
    )

    print(
        f"   Erkannte Polarisation: "
        f"{polarization}"
    )

    print(
        "   Polarisation wird eingestellt..."
    )

    radest.system_set_polarization_77ghz(
        polarization
    )

    print(
        f"   Eingestellt: {polarization}"
    )

    # ----------------------------------------------
    # 2. Frequenzbereich
    # ----------------------------------------------

    print(
        "\n2. Frequenzbereich wird bestimmt..."
    )

    frequency_range = (
        radest.measure_get_frequencyrange()
    )

    print(
        f"   Frequenzbereich: "
        f"{frequency_range}"
    )

    # ----------------------------------------------
    # 3. Leistung
    # ----------------------------------------------

    print(
        "\n3. Leistung wird gemessen..."
    )

    power = (
        radest.measure_get_77ghz_eirp()
    )

    print(
        f"   Gemessene Leistung: "
        f"{power}"
    )

    print(
        "\nRadEsT Precheck abgeschlossen."
    )

    return {
        "polarization": polarization,
        "frequency_range": frequency_range,
        "power": power
    }


# --------------------------------------------------
# Statische Messung
# --------------------------------------------------

def run_static_test(
    vehicle,
    radest
):

    print("\n")
    print("=" * 50)
    print("STATISCHE MESSUNG")
    print("=" * 50)

    # ----------------------------------------------
    # Prüfen welche Signale das Fahrzeug unterstützt
    # ----------------------------------------------

    available_signals = (
        vehicle.get_available_signals()
    )

    signals_to_read = [
        signal
        for signal in RADAR_SIGNALS
        if signal in available_signals
    ]

    print(
        "\nVerfügbare Radarsignale:"
    )

    for signal in signals_to_read:
        print(
            f"   - {signal}"
        )

    if "distance" not in signals_to_read:
        raise RuntimeError(
            "Für dieses Fahrzeug ist kein "
            "'distance'-Signal definiert"
        )

    # ----------------------------------------------
    # Distanz auswählen
    # ----------------------------------------------

    while True:
        try:
            requested_distance = float(
                input(
                    "\nGewünschte Distanz [m]: "
                ).replace(",", ".")
            )

            break

        except ValueError:
            print(
                "Bitte eine gültige Zahl eingeben."
            )

    # ----------------------------------------------
    # RadEsT einstellen
    # ----------------------------------------------

    print(
        f"\nRadEsT wird auf "
        f"{requested_distance:.2f} m gesetzt..."
    )

    radest.target_set_distance(
        requested_distance
    )

    time.sleep(0.5)

    # Tatsächlich realisierte Distanz
    realized_distance = (
        radest.target_get_distance()
    )

    print(
        f"Angefordert: "
        f"{requested_distance:.2f} m"
    )

    print(
        f"RadEsT realisiert: "
        f"{realized_distance:.2f} m"
    )

    # ----------------------------------------------
    # Live-Messung
    # ----------------------------------------------

    print(
        "\nMessung läuft."
    )

    print(
        "Mit Ctrl+C Messung beenden.\n"
    )

    try:

        while True:

            values = vehicle.read_signals(
                signals_to_read
            )

            # --------------------------------------
            # Ausgabe
            # --------------------------------------

            output = []

            output.append(
                f"RadEsT: "
                f"{realized_distance:.2f} m"
            )

            # Distanz
            if "distance" in values:

                vehicle_distance = (
                    values[
                        "distance"
                    ]["value"]
                )

                distance_error = (
                    vehicle_distance
                    - realized_distance
                )

                output.append(
                    f"Distanz: "
                    f"{vehicle_distance:.2f} m"
                )

                output.append(
                    f"Δ: "
                    f"{distance_error:+.2f} m"
                )

            # Winkel
            if "angle" in values:

                angle = (
                    values[
                        "angle"
                    ]["value"]
                )

                unit = (
                    values[
                        "angle"
                    ]["unit"]
                )

                output.append(
                    f"Winkel: "
                    f"{angle:.2f} {unit}"
                )

            # Relativgeschwindigkeit
            if "relative_speed" in values:

                speed = (
                    values[
                        "relative_speed"
                    ]["value"]
                )

                unit = (
                    values[
                        "relative_speed"
                    ]["unit"]
                )

                output.append(
                    f"v_rel: "
                    f"{speed:.2f} {unit}"
                )

            # Relativbeschleunigung
            if (
                "relative_acceleration"
                in values
            ):

                acceleration = (
                    values[
                        "relative_acceleration"
                    ]["value"]
                )

                unit = (
                    values[
                        "relative_acceleration"
                    ]["unit"]
                )

                output.append(
                    f"a_rel: "
                    f"{acceleration:.2f} {unit}"
                )

            print(
                " | ".join(output)
            )

            time.sleep(
                MEASUREMENT_INTERVAL
            )

    except KeyboardInterrupt:

        print(
            "\nStatische Messung beendet."
        )


# --------------------------------------------------
# Hauptprogramm
# --------------------------------------------------

def main():

    print("\n")
    print("=" * 50)
    print("RADAR TESTSYSTEM")
    print("=" * 50)

    # ----------------------------------------------
    # Fahrzeug auswählen
    # ----------------------------------------------

    selected_vehicle = (
        select_vehicle()
    )

    vehicle_id = (
        selected_vehicle["id"]
    )

    vehicle_name = (
        get_vehicle_display_name(
            selected_vehicle
        )
    )

    print(
        f"\nAusgewählt: "
        f"{vehicle_name}"
    )

    # ----------------------------------------------
    # Objekte erzeugen
    # ----------------------------------------------

    vehicle = VehicleDiagnostic(
        vehicle_id=vehicle_id
    )

    radest = RadestDevice(
        ip_address=RADEST_IP,
        port=RADEST_PORT
    )

    try:

        # ------------------------------------------
        # Fahrzeug verbinden
        # ------------------------------------------

        print(
            "\nFahrzeugdiagnose wird verbunden..."
        )

        vehicle.connect()

        print(
            "Fahrzeugdiagnose verbunden."
        )

        # ------------------------------------------
        # RadEsT verbinden
        # ------------------------------------------

        print(
            "\nVerbindung zum RadEsT..."
        )

        if not radest.connect():

            raise ConnectionError(
                "Verbindung zum RadEsT fehlgeschlagen"
            )

        print(
            "RadEsT verbunden."
        )

        # ------------------------------------------
        # Precheck
        # ------------------------------------------

        precheck = (
            run_radest_precheck(
                radest
            )
        )

        print("\n")
        print("-" * 50)
        print("PRECHECK ERGEBNIS")
        print("-" * 50)

        print(
            f"Polarisation: "
            f"{precheck['polarization']}"
        )

        print(
            f"Frequenzbereich: "
            f"{precheck['frequency_range']}"
        )

        print(
            f"Leistung: "
            f"{precheck['power']}"
        )

        # ------------------------------------------
        # Statische Messung
        # ------------------------------------------

        run_static_test(
            vehicle,
            radest
        )

    except Exception as error:

        print(
            f"\nFEHLER: {error}"
        )

    finally:

        print(
            "\nVerbindungen werden getrennt..."
        )

        vehicle.disconnect()

        try:
            radest.disconnect()
        except Exception:
            pass

        print(
            "Testsystem beendet."
        )


if __name__ == "__main__":
    main()