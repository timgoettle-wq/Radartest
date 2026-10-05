"""Vergleichsreihe: identischer Testablauf fuer den Fahrzeugvergleich.

Jedes Fahrzeug durchlaeuft exakt denselben Plan. Alle RCS-Werte werden ueber
einen Ziel-attSet festgelegt, damit der RadEsT bei jedem Fahrzeug gleich
ausgesteuert ist, auch wenn die Fahrzeuge unterschiedlich stark senden.

    K1  Kontrollpunkt Anfang: statische Leiter 15 m, attSet 5 -> 1 (0,5er)
    S50 statische Leiter 50 m, attSet 6 -> 2 (0,5er)
    G   Geisterbeginn Modus 0: weg 15 -> 100 m, attSet 3 / 4 / 5 / 6
    ST  Startabstand egal? weg 30 / 40 -> 100 m, attSet 4
    M1  Modus 1: weg 15 -> 100 m, attSet 2 / 3 / 4 / 5
    H   hinfahrend 90 -> 15 m, Modus 0 und 1, attSet 5 bei 15 m
    K2  Kontrollpunkt Ende: wie K1, zeigt Drift waehrend der Reihe

Nach jedem Geist folgt automatisch ein Reset bei 15 m / 0 dBsm. Am Ende
wird der TestRun-Ordner als ZIP gepackt, der Name enthaelt --name.

Start aus dem Projektordner (Geraet vorher warm laufen lassen):
    python demo_scripte/vergleichsreihe.py --name kuga
    python demo_scripte/vergleichsreihe.py --name mustang --wiederholungen 2
    python demo_scripte/vergleichsreihe.py --plan
"""

import argparse
import re
import shutil
import sys
import time
import traceback
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from demo_scripte import geister_testreihe as gt


# ======================================================
# KONFIGURATION
# ======================================================

VEHICLE_ID = 2

# Unter dieser Detektortemperatur ist der RadEsT vermutlich noch nicht
# warm. Die Geisterschwellen verschieben sich dann.
MIN_TEMPERATURE_C = 35.0

PLAN_VERSION = 1


def _steps(start, stop, step=0.5):
    """attSet-Werte von start bis stop (absteigend), exakt im 0,25-Raster."""
    count = int(round(abs(start - stop) / step))
    sign = -1 if stop < start else 1
    return [round(start + sign * step * index, 2) for index in range(count + 1)]


def build_plan():
    plan = []

    def ladder(block, distance_m, attsets, title):
        for attset in attsets:
            plan.append(gt.static_test(
                block, f"{title}: statisch {distance_m:g} m, attSet {attset:g}",
                distance_m, attset,
            ))

    ladder("K1", 15.0, _steps(5.0, 1.0), "Kontrolle Anfang")
    ladder("S50", 50.0, _steps(6.0, 2.0), "Leiter 50 m")

    for attset in (6.0, 5.0, 4.0, 3.0):
        plan.append(gt.dynamic_test(
            "G", f"weg 15->100 m, Modus 0, attSet {attset:g}",
            15, 100, 0, attset,
        ))

    for start_m in (30, 40):
        plan.append(gt.dynamic_test(
            "ST", f"weg {start_m}->100 m, Modus 0, attSet 4",
            start_m, 100, 0, 4.0,
        ))

    for attset in (5.0, 4.0, 3.0, 2.0):
        plan.append(gt.dynamic_test(
            "M1", f"weg 15->100 m, Modus 1, attSet {attset:g}",
            15, 100, 1, attset,
        ))

    for mode in (0, 1):
        plan.append(gt.dynamic_test(
            "H", f"hin 90->15 m, Modus {mode}, attSet 5 bei 15 m",
            90, 15, mode, 5.0, attset_distance_m=15,
        ))

    ladder("K2", 15.0, _steps(5.0, 1.0), "Kontrolle Ende")
    return plan


def safe_name(name):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", default="",
                        help="Fahrzeugname fuer Ordner und ZIP, z. B. kuga")
    parser.add_argument("--fahrzeug", type=int, default=VEHICLE_ID,
                        help="Fahrzeug-ID aus der Datenbank")
    parser.add_argument("--wiederholungen", type=int, default=1,
                        help="Wie oft der ganze Plan laufen soll")
    parser.add_argument("--plan", action="store_true",
                        help="Nur den Plan anzeigen, nichts verbinden")
    return parser.parse_args()


def main(controller_factory=None):
    args = parse_args()
    if args.wiederholungen < 1:
        raise SystemExit("--wiederholungen muss mindestens 1 sein")

    name = safe_name(args.name)
    one_pass = build_plan()
    plan = []
    for repetition in range(1, args.wiederholungen + 1):
        for test in one_pass:
            test = dict(test)
            test["repetition"] = repetition
            if args.wiederholungen > 1:
                test["label"] = f"[{repetition}] {test['label']}"
            plan.append(test)

    print("Vergleichsreihe")
    print(f"Fahrzeug: {name or '(ohne Namen)'}   Fahrzeug-ID: {args.fahrzeug}   "
          f"Wiederholungen: {args.wiederholungen}")
    gt.print_plan(plan, gt.FALLBACK_REFERENCE_ATTSET)

    if args.plan:
        return

    if not name:
        print("\nHinweis: Ohne --name lassen sich ZIPs von Fahrzeugen mit "
              "gleicher Fahrzeug-ID spaeter schlecht auseinanderhalten.")
    print(f"\nVorher: RadEsT warm laufen lassen (Detektor >= "
          f"{MIN_TEMPERATURE_C:g} °C) und den Aufbau nicht mehr anfassen.")
    input("Enter startet die Vergleichsreihe, Ctrl+C bricht ab: ")

    if controller_factory is None:
        from test_controller import TestController
        controller_factory = TestController

    controller = controller_factory(vehicle_id=args.fahrzeug)
    reihe = gt.Testreihe(controller)
    run_directory = None
    started = time.monotonic()

    try:
        controller.connect()
        test_run = controller.start_test_run()
        run_directory = test_run["directory"]
        controller.test_run.data["vergleichsreihe"] = {
            "name": name,
            "plan_version": PLAN_VERSION,
            "repetitions": args.wiederholungen,
        }
        print(f"\nTestRun: {test_run['run_id']}")
        controller.skip_precheck()

        summary = reihe.run_reference("Kalibrierung", gt.CALIBRATION_DURATION_S)
        temperature = getattr(controller, "radest_temperature_c", None)
        print(f"   Referenz-attSet: {reihe.reference_attset}   "
              f"Detektortemperatur: {temperature} °C")
        controller.test_run.data["vergleichsreihe"].update({
            "reference_attset": reihe.reference_attset,
            "start_temperature_c": temperature,
        })

        if temperature is not None and temperature < MIN_TEMPERATURE_C:
            print(f"\n   ACHTUNG: RadEsT erst {temperature:.1f} °C warm. Die "
                  "Ergebnisse sind dann nicht mit warmen Sitzungen vergleichbar.")
            if not gt.ask_yes("Trotzdem starten?"):
                return

        if summary["has_ghost"]:
            print("\n   ACHTUNG: Schon die Referenz (15 m / 0 dBsm) zeigt Geister."
                  " Der Aufbau ist vermutlich schlecht ausgerichtet.")
            if not gt.ask_yes("Trotzdem weitermachen?"):
                return

        current_block = None
        for index, test in enumerate(plan, start=1):
            block_key = (test["repetition"], test["block"])
            if block_key != current_block:
                current_block = block_key
                print("\n" + "=" * 70)
                print(f"BLOCK {test['block']}  (Durchlauf {test['repetition']})")
                print("=" * 70)
                if index > 1 and not reihe.last_was_reference:
                    reihe.run_reference("Referenz Blockstart", gt.RESET_DURATION_S)

            reihe.run_test(index, len(plan), test)

        print("\nVergleichsreihe abgeschlossen.")

    except KeyboardInterrupt:
        print("\nVergleichsreihe mit Ctrl+C abgebrochen.")
        try:
            controller.stop_active_measurement()
        except Exception:
            pass

    except Exception as error:
        traceback.print_exc()
        print(f"\nFEHLER: {error}")

    finally:
        print("Verbindungen werden getrennt...")
        try:
            controller.disconnect()
        except Exception as error:
            print(f"Fehler beim Trennen: {error}")

        if run_directory is not None:
            summary_file = reihe.write_summary(run_directory)
            run_path = Path(run_directory)
            archive_base = str(run_path) + (f"_{name}" if name else "")
            archive = shutil.make_archive(
                archive_base, "zip",
                root_dir=run_path.parent, base_dir=run_path.name,
            )
            minutes = (time.monotonic() - started) / 60
            print(f"\nDauer: {minutes:.0f} min")
            if summary_file:
                print(f"Uebersicht: {summary_file}")
            print("Hinweis: Beim Kuga erscheinen die abwechselnden "
                  "'200'-Werte in der Uebersicht als Verlust. Fuer die "
                  "Auswertung werden sie herausgefiltert.")
            print(f"ZIP zum Verschicken: {archive}")


if __name__ == "__main__":
    main()
