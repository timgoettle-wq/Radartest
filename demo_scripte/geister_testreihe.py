"""Automatische Testreihe: Wann entstehen Geisterziele (1/2, 1/4, 1/8)?

Die Reihe klaert, welche Einstellungen zuverlaessig ohne Geister messen:

    A  statische attSet-Leiter bei 15 m, 50 m und 150 m
    B  dynamisch wegfahrend, Modus 0, verschiedene Laengen
    C  dieselben Fahrten in Modus 1
    D  dynamisch hinfahrend, Modus 0 gegen Modus 1
    E  Ausrichtung: dieselben Tests an mehreren Aufbaupositionen

Alle RCS-Werte werden ueber einen Ziel-attSet festgelegt und nicht fest
vorgegeben. Eine Kalibriermessung bei 15 m / 0 dBsm liefert den attSet des
aktuellen Aufbaus. Daraus berechnet das Skript fuer jeden Test das RCS
(1 attSet-Schritt entspricht ca. 4 dB). Dadurch funktioniert die Reihe
mit jedem Fahrzeug.

Alle Tests landen in einem einzigen TestRun unter test_runs/. Am Ende wird
der Ordner automatisch als ZIP gepackt.

Start aus dem Projektordner:
    python demo_scripte/geister_testreihe.py
    python demo_scripte/geister_testreihe.py --fahrzeug 1 --bloecke A,B
    python demo_scripte/geister_testreihe.py --plan     (nur Plan anzeigen)

Block E braucht Handarbeit: vor jeder Aufbauposition wartet das Skript auf
Enter. Ohne Block E laeuft die Reihe komplett ohne Eingaben durch.
"""

import argparse
import csv
import math
import shutil
import sys
import time
import traceback
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ======================================================
# KONFIGURATION
# ======================================================

VEHICLE_ID = 2

# Precheck wie in den bisherigen Messungen ueberspringen.
SKIP_PRECHECK = True

# Referenz fuer die attSet-Kalibrierung und fuer jeden Reset.
REFERENCE_DISTANCE_M = 15.0
REFERENCE_RCS_DBSM = 0.0

# Faustwert aus den Ford-Messungen, falls der RadEsT keinen attSet liefert.
FALLBACK_REFERENCE_ATTSET = 7.25

# Ein attSet-Schritt entspricht ca. 4 dB Daempfung.
DB_PER_ATTSET = 4.0

STATIC_DURATION_S = 20.0
RESET_DURATION_S = 10.0
CALIBRATION_DURATION_S = 20.0

VELOCITY_KMH = 20.0
PRE_HOLD_S = 5.0
POST_HOLD_S = 5.0

MEASUREMENT_INTERVAL_S = 0.2
SETTLE_TIME_S = 1.0

# Die ersten Messpunkte koennen noch vom vorherigen Test stammen.
IGNORE_FIRST_SAMPLES = 2

# Ab so vielen Geister-Messpunkten gilt ein Test als "Geist".
MIN_GHOST_SAMPLES = 2

# Nach so vielen Fehlern in Folge wird die Reihe abgebrochen.
MAX_CONSECUTIVE_ERRORS = 3

STATIC_LADDER_DISTANCES_M = [15.0, 50.0, 150.0]
STATIC_LADDER_ATTSETS = [5.0, 4.0, 3.0, 2.0, 1.0, 0.0]

ALIGNMENT_POSITIONS = [
    "gut ausgerichtet (Referenz)",
    "2 Grad nach links gedreht",
    "2 Grad nach rechts gedreht",
    "3 Grad nach unten gekippt",
    "10 cm seitlich versetzt",
]

GHOST_CLASSES = ("1/2", "1/4", "1/8", "1/16")
HIGH_ORDER_GHOSTS = ("1/4", "1/8", "1/16")


# ======================================================
# TESTPLAN
# ======================================================

def static_test(block, label, distance_m, attset, row=None):
    return {
        "block": block,
        "label": label,
        "kind": "static",
        "distance_m": distance_m,
        "target_attset": attset,
        "attset_distance_m": distance_m,
        "ladder_row": row,
    }


def dynamic_test(block, label, start_m, end_m, mode, attset, attset_distance_m=None):
    return {
        "block": block,
        "label": label,
        "kind": "dynamic",
        "start_distance_m": start_m,
        "end_distance_m": end_m,
        "mode": mode,
        "target_attset": attset,
        # Bei Annaeherung wird der attSet fuer das nahe Ende geplant.
        "attset_distance_m": (
            start_m if attset_distance_m is None else attset_distance_m
        ),
    }


def build_plan(blocks):
    plan = []

    if "A" in blocks:
        for distance_m in STATIC_LADDER_DISTANCES_M:
            for attset in STATIC_LADDER_ATTSETS:
                plan.append(static_test(
                    "A",
                    f"statisch {distance_m:g} m, attSet {attset:g}",
                    distance_m,
                    attset,
                    row=distance_m,
                ))

    if "B" in blocks:
        for start_m, end_m, attset in (
            (15, 30, 5.0), (15, 45, 5.0), (15, 60, 5.0), (15, 90, 5.0),
            (15, 60, 6.5), (15, 90, 6.5),
            (30, 60, 5.0), (30, 90, 5.0), (30, 120, 5.0),
        ):
            plan.append(dynamic_test(
                "B",
                f"weg {start_m}->{end_m} m, Modus 0, attSet {attset:g}",
                start_m, end_m, 0, attset,
            ))

    if "C" in blocks:
        for start_m, end_m, attset in (
            (15, 30, 5.0), (15, 60, 5.0), (15, 90, 5.0), (30, 120, 5.0),
        ):
            plan.append(dynamic_test(
                "C",
                f"weg {start_m}->{end_m} m, Modus 1, attSet {attset:g}",
                start_m, end_m, 1, attset,
            ))

    if "D" in blocks:
        for start_m in (90, 60):
            for mode in (0, 1):
                plan.append(dynamic_test(
                    "D",
                    f"hin {start_m}->15 m, Modus {mode}, attSet 5 bei 15 m",
                    start_m, 15, mode, 5.0, attset_distance_m=15,
                ))

    if "E" in blocks:
        for position in ALIGNMENT_POSITIONS:
            tests = [
                static_test("E", "statisch 15 m, attSet 6", 15.0, 6.0),
                static_test("E", "statisch 50 m, attSet 5", 50.0, 5.0),
                dynamic_test("E", "weg 15->45 m, Modus 0, attSet 5", 15, 45, 0, 5.0),
                dynamic_test("E", "weg 15->45 m, Modus 1, attSet 5", 15, 45, 1, 5.0),
            ]
            for index, test in enumerate(tests):
                test["position"] = position
                test["confirm_position"] = index == 0
            plan.extend(tests)

    return plan


def rcs_for_attset(target_attset, distance_m, reference_attset):
    """Berechnet das RCS, bei dem der RadEsT den gewuenschten attSet waehlt."""

    rcs_dbsm = (
        REFERENCE_RCS_DBSM
        + DB_PER_ATTSET * (reference_attset - target_attset)
        + 40.0 * math.log10(distance_m / REFERENCE_DISTANCE_M)
    )
    return round(rcs_dbsm, 1)


def estimate_duration_s(test):
    if test["kind"] == "static":
        return STATIC_DURATION_S + SETTLE_TIME_S + 3.0
    distance_m = abs(test["end_distance_m"] - test["start_distance_m"])
    return (
        PRE_HOLD_S + POST_HOLD_S
        + distance_m / (VELOCITY_KMH / 3.6)
        + SETTLE_TIME_S + 4.0
    )


# ======================================================
# AUSWERTUNG EINES TESTS
# ======================================================

def classify_ratio(ratio):
    if ratio is None or ratio <= 0:
        return "none"
    for name, value in (
        ("1", 1.0), ("1/2", 0.5), ("1/4", 0.25),
        ("1/8", 0.125), ("1/16", 0.0625),
    ):
        if abs(ratio - value) <= 0.15 * value:
            return name
    return "other"


def result_text(summary):
    parts = []
    if summary["has_ghost"]:
        parts.append(summary["dominant_ghost"])
    if summary["has_loss"]:
        parts.append("Verlust")
    return "+".join(parts) if parts else "sauber"


def get_vehicle_distance(measurement):
    value = (
        measurement.get("vehicle", {})
        .get("distance", {})
        .get("value")
    )
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def summarize_samples(samples):
    """samples: Liste aus (Soll-Distanz, Fahrzeug-Distanz)."""

    classes = []
    for target_m, vehicle_m in samples:
        ratio = (
            vehicle_m / target_m
            if target_m and vehicle_m is not None
            else None
        )
        classes.append((target_m, classify_ratio(ratio)))

    counts = Counter(name for _, name in classes)
    evaluated = classes[IGNORE_FIRST_SAMPLES:]
    ghost_counts = Counter(
        name for _, name in evaluated if name in GHOST_CLASSES
    )
    ghost_samples = sum(ghost_counts.values())
    has_ghost = ghost_samples >= MIN_GHOST_SAMPLES

    first_ghost_target_m = next(
        (target for target, name in evaluated if name in GHOST_CLASSES),
        None,
    )

    # Kein Objekt oder ein Wert ohne Bezug zur Soll-Distanz, z. B. ein
    # Objektverlust bei der Annaeherung.
    lost_samples = sum(
        1 for _, name in evaluated if name in ("none", "other")
    )
    has_loss = lost_samples >= MIN_GHOST_SAMPLES
    first_loss_target_m = next(
        (target for target, name in evaluated if name in ("none", "other")),
        None,
    )
    dominant_ghost = (
        ghost_counts.most_common(1)[0][0] if ghost_counts else None
    )

    return {
        "samples": len(classes),
        "counts": dict(counts),
        "ghost_samples": ghost_samples,
        "has_ghost": has_ghost,
        "dominant_ghost": dominant_ghost if has_ghost else None,
        "first_ghost_target_m": first_ghost_target_m if has_ghost else None,
        "lost_samples": lost_samples,
        "has_loss": has_loss,
        "first_loss_target_m": first_loss_target_m if has_loss else None,
    }


# ======================================================
# EINZELNEN TEST AUSFUEHREN
# ======================================================

def collect_samples(controller, samples, timeout_s, stop_after_s=None):
    """Sammelt Messpunkte, bis die Zeit um ist oder der Messloop endet."""

    started = time.monotonic()
    last_sequence = None

    while True:
        elapsed = time.monotonic() - started

        if stop_after_s is not None and elapsed >= stop_after_s:
            break
        if elapsed >= timeout_s:
            raise RuntimeError("Zeitueberschreitung beim Messen")

        running = controller.is_measurement_running()
        measurement = controller.get_latest_measurement()

        if (
            measurement is not None
            and measurement.get("sequence") != last_sequence
        ):
            last_sequence = measurement.get("sequence")
            vehicle_m = get_vehicle_distance(measurement)
            target_m = measurement.get("radest_distance")
            samples.append((target_m, vehicle_m))

            vehicle_text = "--" if vehicle_m is None else f"{vehicle_m:6.1f}"
            target_text = "--" if target_m is None else f"{target_m:6.1f}"
            print(
                f"\r   t={elapsed:5.1f} s  Soll={target_text} m  "
                f"Fahrzeug={vehicle_text} m   ",
                end="",
                flush=True,
            )

        if not running:
            break

        time.sleep(0.05)

    print()


def run_static(controller, distance_m, rcs_dbsm, duration_s, metadata):
    prepared = controller.prepare_static_measurement(distance_m)
    limits = prepared["rcs_limits"]

    if not limits["rcs_min_dbsm"] <= rcs_dbsm <= limits["rcs_max_dbsm"]:
        return None, (
            f"RCS {rcs_dbsm:g} dBsm ausserhalb "
            f"[{limits['rcs_min_dbsm']:.1f}, {limits['rcs_max_dbsm']:.1f}]"
        )

    controller.start_static_measurement(distance_m, rcs_dbsm)
    controller.start_logging()
    controller.test_run.update_active_test({"testplan": metadata})
    controller.start_measurement_loop(interval_s=MEASUREMENT_INTERVAL_S)

    samples = []
    try:
        collect_samples(
            controller,
            samples,
            timeout_s=duration_s + 10.0,
            stop_after_s=duration_s,
        )
    finally:
        controller.stop_measurement_loop()
        controller.stop_logging(status="finished", reason="testplan_completed")

    if not samples:
        raise RuntimeError("Keine Messwerte erhalten")

    return samples, None


def run_dynamic(controller, test, rcs_dbsm, metadata):
    prepared = controller.prepare_dynamic_measurement(
        start_distance_m=test["start_distance_m"],
        end_distance_m=test["end_distance_m"],
        velocity_kmh=VELOCITY_KMH,
        rcs_constant_state=test["mode"],
        pre_hold_s=PRE_HOLD_S,
        post_hold_s=POST_HOLD_S,
    )
    limits = prepared["rcs_limits"]

    if not limits["rcs_min_dbsm"] <= rcs_dbsm <= limits["rcs_max_dbsm"]:
        return None, (
            f"RCS {rcs_dbsm:g} dBsm ausserhalb "
            f"[{limits['rcs_min_dbsm']:.1f}, {limits['rcs_max_dbsm']:.1f}]"
        )

    controller.start_dynamic_measurement(
        start_distance_m=test["start_distance_m"],
        end_distance_m=test["end_distance_m"],
        velocity_kmh=VELOCITY_KMH,
        rcs_constant_state=test["mode"],
        rcs_dbsm=rcs_dbsm,
    )
    controller.start_logging()
    controller.test_run.update_active_test({"testplan": metadata})
    controller.start_measurement_loop(interval_s=MEASUREMENT_INTERVAL_S)
    controller.trigger_dynamic_scenario()

    samples = []
    try:
        collect_samples(
            controller,
            samples,
            timeout_s=prepared["total_duration_s"] + 30.0,
        )
        # Gibt einen Fehler aus dem Hintergrundthread weiter.
        final = controller.get_latest_measurement()
        if final is None or not final.get("scenario_done", False):
            raise RuntimeError("Szenario wurde vorzeitig beendet")
    finally:
        controller.stop_measurement_loop()
        controller.stop_logging(status="finished", reason="testplan_completed")

    return samples, None


def current_attset(controller, kind):
    setting = (
        controller.static_rcs_setting
        if kind == "static"
        else controller.dynamic_rcs_setting
    ) or {}
    return setting.get("values", {}).get("attSet")


# ======================================================
# TESTREIHE
# ======================================================

class Testreihe:

    def __init__(self, controller):
        self.controller = controller
        self.reference_attset = None
        self.results = []
        self.consecutive_errors = 0
        self.skipped_rows = set()
        self.high_order_in_row = {}
        self.last_was_reference = False

    def run_reference(self, label, duration_s):
        """Statische Referenz 15 m / 0 dBsm: Reset und Kalibrierung."""

        print(f"\n-- {label}: {REFERENCE_DISTANCE_M:g} m, "
              f"{REFERENCE_RCS_DBSM:g} dBsm, {duration_s:g} s")

        metadata = {"block": "-", "label": label, "role": "reference"}
        samples, skip_reason = run_static(
            self.controller,
            REFERENCE_DISTANCE_M,
            REFERENCE_RCS_DBSM,
            duration_s,
            metadata,
        )
        if skip_reason:
            raise RuntimeError(f"Referenzmessung nicht moeglich: {skip_reason}")

        summary = summarize_samples(samples)
        attset = current_attset(self.controller, "static")

        if attset is not None:
            self.reference_attset = attset
        elif self.reference_attset is None:
            self.reference_attset = FALLBACK_REFERENCE_ATTSET
            print("   WARNUNG: RadEsT liefert keinen attSet, "
                  f"nehme Faustwert {FALLBACK_REFERENCE_ATTSET}")

        self.record(metadata, REFERENCE_RCS_DBSM, attset, summary)
        self.last_was_reference = True
        return summary

    def record(self, metadata, rcs_dbsm, attset, summary, note=""):
        test_info = None
        if summary is not None and self.controller.test_run is not None:
            tests = self.controller.test_run.data.get("tests", [])
            test_info = tests[-1]["test_id"] if tests else None

        row = {
            "test_id": test_info or "",
            "block": metadata.get("block", ""),
            "position": metadata.get("position", ""),
            "label": metadata.get("label", ""),
            "rcs_dbsm": rcs_dbsm,
            "target_attset": metadata.get("target_attset", ""),
            "attset": "" if attset is None else attset,
            "result": note if summary is None else result_text(summary),
            "ghost_samples": "" if summary is None else summary["ghost_samples"],
            "samples": "" if summary is None else summary["samples"],
            "first_ghost_target_m": (
                "" if summary is None or summary["first_ghost_target_m"] is None
                else round(summary["first_ghost_target_m"], 1)
            ),
            "lost_samples": "" if summary is None else summary["lost_samples"],
            "first_loss_target_m": (
                "" if summary is None or summary["first_loss_target_m"] is None
                else round(summary["first_loss_target_m"], 1)
            ),
        }
        self.results.append(row)

        if summary is not None:
            parts = []
            if summary["has_ghost"]:
                parts.append(
                    f"GEIST {summary['dominant_ghost']} "
                    f"({summary['ghost_samples']}/{summary['samples']}), "
                    f"ab Soll {summary['first_ghost_target_m']:.1f} m"
                )
            if summary["has_loss"]:
                parts.append(
                    f"VERLUST/ABWEICHUNG ({summary['lost_samples']}/"
                    f"{summary['samples']}), "
                    f"ab Soll {summary['first_loss_target_m']:.1f} m"
                )
            print(f"   attSet={attset}  ->  {' | '.join(parts) or 'sauber'}")

    def run_test(self, index, total, test):
        row = test.get("ladder_row")
        if row is not None and row in self.skipped_rows:
            print(f"\n[{index}/{total}] {test['label']}: uebersprungen "
                  "(zweimal hintereinander 1/4 oder hoeher)")
            self.record(test, None, None, None, "uebersprungen (Reihe beendet)")
            return

        rcs_dbsm = rcs_for_attset(
            test["target_attset"],
            test["attset_distance_m"],
            self.reference_attset,
        )
        metadata = {
            key: test[key] for key in (
                "block", "label", "target_attset", "position"
            ) if key in test
        }
        metadata["role"] = "test"
        metadata["reference_attset"] = self.reference_attset

        print(f"\n[{index}/{total}] Block {test['block']}: {test['label']}"
              f"  (RCS {rcs_dbsm:g} dBsm)")

        time.sleep(SETTLE_TIME_S)

        try:
            if test["kind"] == "static":
                samples, skip_reason = run_static(
                    self.controller, test["distance_m"], rcs_dbsm,
                    STATIC_DURATION_S, metadata,
                )
            else:
                samples, skip_reason = run_dynamic(
                    self.controller, test, rcs_dbsm, metadata,
                )
        except KeyboardInterrupt:
            raise
        except Exception as error:
            self.last_was_reference = False
            self.consecutive_errors += 1
            print(f"\n   FEHLER: {error}")
            self.record(metadata, rcs_dbsm, None, None, f"Fehler: {error}")
            if self.consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                raise RuntimeError(
                    f"{MAX_CONSECUTIVE_ERRORS} Fehler in Folge, Abbruch"
                ) from error
            return

        self.consecutive_errors = 0
        self.last_was_reference = False

        if skip_reason:
            print(f"   uebersprungen: {skip_reason}")
            self.record(metadata, rcs_dbsm, None, None,
                        f"uebersprungen: {skip_reason}")
            return

        summary = summarize_samples(samples)
        attset = current_attset(self.controller, test["kind"])
        self.record(metadata, rcs_dbsm, attset, summary)

        if row is not None:
            if summary["dominant_ghost"] in HIGH_ORDER_GHOSTS:
                self.high_order_in_row[row] = self.high_order_in_row.get(row, 0) + 1
            else:
                self.high_order_in_row[row] = 0
            if self.high_order_in_row[row] >= 2:
                self.skipped_rows.add(row)

        # Geisterzustand kann in den naechsten Test nachwirken.
        if summary["has_ghost"]:
            self.run_reference("Reset nach Geist", RESET_DURATION_S)

    def write_summary(self, directory):
        if not self.results:
            return None
        summary_file = Path(directory) / "testplan_summary.csv"
        with open(summary_file, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(
                file, fieldnames=list(self.results[0].keys()), delimiter=";"
            )
            writer.writeheader()
            writer.writerows(self.results)
        return summary_file


def ask_yes(question):
    return input(f"{question} [j/N]: ").strip().lower() in ("j", "ja", "y")


def print_plan(plan, reference_attset):
    total_s = CALIBRATION_DURATION_S + 5
    print(f"Geplante Tests: {len(plan)} (Resets nach Geistern kommen dazu)")
    for index, test in enumerate(plan, start=1):
        rcs = rcs_for_attset(
            test["target_attset"], test["attset_distance_m"], reference_attset
        )
        position = f" [{test['position']}]" if "position" in test else ""
        print(f"  {index:3d}. {test['block']}  {test['label']:45s} "
              f"RCS ~{rcs:5.1f} dBsm{position}")
        total_s += estimate_duration_s(test)
    print(f"Geschaetzte Dauer ohne Resets: ca. {total_s / 60:.0f} min")
    print(f"(RCS-Werte geschaetzt mit attSet {reference_attset} bei "
          f"{REFERENCE_DISTANCE_M:g} m / {REFERENCE_RCS_DBSM:g} dBsm; "
          "die Kalibrierung passt sie an.)")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fahrzeug", type=int, default=VEHICLE_ID)
    parser.add_argument(
        "--bloecke", default="A,B,C,D",
        help="Kommagetrennt aus A,B,C,D,E (Standard: A,B,C,D)",
    )
    parser.add_argument("--precheck", action="store_true",
                        help="Precheck ausfuehren statt ueberspringen")
    parser.add_argument("--plan", action="store_true",
                        help="Nur den Plan anzeigen, nichts verbinden")
    return parser.parse_args()


def main(controller_factory=None):
    args = parse_args()
    blocks = {
        block.strip().upper() for block in args.bloecke.split(",")
        if block.strip()
    }
    unknown = blocks - set("ABCDE")
    if unknown:
        raise SystemExit(f"Unbekannte Bloecke: {', '.join(sorted(unknown))}")

    plan = build_plan(blocks)
    print("Geister-Testreihe")
    print(f"Fahrzeug-ID: {args.fahrzeug}   Bloecke: {', '.join(sorted(blocks))}")
    print_plan(plan, FALLBACK_REFERENCE_ATTSET)

    if args.plan:
        return

    print("\nVorher: RadEsT >= 30 min warm, Aufbau fuer die Bloecke A-D "
          "nicht mehr anfassen.")
    input("Enter startet die Testreihe, Ctrl+C bricht ab: ")

    if controller_factory is None:
        from test_controller import TestController
        controller_factory = TestController

    controller = controller_factory(vehicle_id=args.fahrzeug)
    reihe = Testreihe(controller)
    run_directory = None
    started = time.monotonic()

    try:
        controller.connect()
        test_run = controller.start_test_run()
        run_directory = test_run["directory"]
        print(f"\nTestRun: {test_run['run_id']}")

        if args.precheck:
            print("Precheck wird ausgefuehrt...")
            controller.run_precheck()
        else:
            controller.skip_precheck()

        summary = reihe.run_reference("Kalibrierung", CALIBRATION_DURATION_S)
        print(f"   Referenz-attSet: {reihe.reference_attset}")

        if summary["has_ghost"]:
            print("\n   ACHTUNG: Schon die Referenz (15 m / 0 dBsm) zeigt Geister."
                  " Der Aufbau ist vermutlich schlecht ausgerichtet.")
            if not ask_yes("Trotzdem weitermachen?"):
                return

        current_block = None
        for index, test in enumerate(plan, start=1):
            if test["block"] != current_block:
                current_block = test["block"]
                print("\n" + "=" * 70)
                print(f"BLOCK {current_block}")
                print("=" * 70)
                # Frischer Referenzpunkt am Blockanfang gleicht Drift aus.
                if index > 1 and not reihe.last_was_reference:
                    reihe.run_reference("Referenz Blockstart", RESET_DURATION_S)

            if test.get("confirm_position"):
                print(f"\n>>> Aufbau jetzt auf Position bringen: "
                      f"{test['position']}")
                answer = input("Enter wenn fertig, s ueberspringt "
                               "diese Position: ").strip().lower()
                if answer == "s":
                    test["skip_position"] = True
                    reihe.record(test, None, None, None,
                                 "Position uebersprungen")
                    continue
                reihe.run_reference("Referenz neue Position", RESET_DURATION_S)

            if test.get("position") and any(
                other.get("skip_position") and other["position"] == test["position"]
                for other in plan
            ):
                continue

            reihe.run_test(index, len(plan), test)

        print("\nTestreihe abgeschlossen.")

    except KeyboardInterrupt:
        print("\nTestreihe mit Ctrl+C abgebrochen.")
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
            archive = shutil.make_archive(
                str(run_path), "zip",
                root_dir=run_path.parent, base_dir=run_path.name,
            )
            minutes = (time.monotonic() - started) / 60
            print(f"\nDauer: {minutes:.0f} min")
            if summary_file:
                print(f"Uebersicht: {summary_file}")
            print(f"ZIP zum Verschicken: {archive}")


if __name__ == "__main__":
    main()
