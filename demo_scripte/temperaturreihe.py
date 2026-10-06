"""Temperaturreihe: Wie verschiebt sich die Geisterschwelle beim Aufwaermen?

Der RadEsT wird kalt eingeschaltet. Danach misst das Skript in festen
Abstaenden (Standard 5 min) einen Zyklus:

    Referenz 15 m / 0 dBsm   -> Temperatur und Referenz-attSet
    statische Leiter 15 m    -> attSet 6 -> 0,5 in 0,5er-Schritten,
                                Abbruch nach zwei Geistern in Folge
    optional dynamische Probe (--dynamisch): Modus 0, weg 15 -> 100 m,
                                attSet 4

Zwischen den Zyklen wird alle 30 s die Detektortemperatur protokolliert.
Die Reihe endet, wenn sich die Temperatur ueber drei Zyklen um weniger als
0,3 °C aendert (oder nach --max-minuten, Standard 240 min, 0 = unbegrenzt). Danach kann eine Gegenprobe
folgen: RadEsT per SYSTEM:SLEEP abkuehlen lassen und wieder messen.

Geht die Zuendung aus, antwortet die Diagnose nicht mehr. Das Skript
pausiert dann, bittet um Einschalten der Zuendung und wiederholt den
unterbrochenen Test. Es geht keine Messung verloren.

Ergebnisse im TestRun-Ordner:
    temperatur_zyklen.csv   Schwelle und Temperatur je Zyklus
    temperaturverlauf.csv   Temperatur ueber der Zeit
    testplan_summary.csv    jeder einzelne Test
Am Ende wird alles als ZIP gepackt.

Start aus dem Projektordner (RadEsT vorher mehrere Stunden aus):
    python demo_scripte/temperaturreihe.py --name mustang
    python demo_scripte/temperaturreihe.py --name mustang --dynamisch
    python demo_scripte/temperaturreihe.py --plan
"""

import argparse
import csv
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

LADDER_DISTANCE_M = 15.0
LADDER_TOP_ATTSET = 6.0
LADDER_BOTTOM_ATTSET = 0.5
LADDER_STEP_ATTSET = 0.5
# Die Leiter startet so weit ueber der letzten Schwelle (spart Zeit).
LADDER_HEADROOM_ATTSET = 2.0
STEP_DURATION_S = 15.0
REFERENCE_DURATION_S = 10.0
GHOSTS_TO_STOP = 2

DYNAMIC_PROBE = {"start_distance_m": 15, "end_distance_m": 100, "mode": 0}
DYNAMIC_PROBE_ATTSET = 4.0

CYCLE_INTERVAL_S = 300.0
TEMPERATURE_LOG_INTERVAL_S = 30.0

STABLE_CYCLES = 3
STABLE_DELTA_C = 0.3
MIN_CYCLES = 4
MAX_MINUTES = 240.0

COOLDOWN_MINUTES = 30.0
COOLDOWN_CYCLES = 2

MAX_RETRIES_PER_TEST = 3


# ======================================================
# HILFSFUNKTIONEN
# ======================================================

def safe_name(name):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")


def ladder_steps(top):
    steps = []
    value = top
    while value >= LADDER_BOTTOM_ATTSET - 1e-9:
        steps.append(round(value, 2))
        value -= LADDER_STEP_ATTSET
    return steps


def next_ladder_top(last_ghost_attset):
    """Startpunkt der naechsten Leiter: knapp oberhalb der letzten Schwelle."""
    if last_ghost_attset is None:
        return LADDER_TOP_ATTSET
    top = last_ghost_attset + LADDER_HEADROOM_ATTSET
    return min(LADDER_TOP_ATTSET, round(top * 2) / 2)


def temperature_is_stable(temperatures):
    if len(temperatures) < STABLE_CYCLES:
        return False
    recent = temperatures[-STABLE_CYCLES:]
    if any(value is None for value in recent):
        return False
    return max(recent) - min(recent) < STABLE_DELTA_C


def threshold_from_results(results):
    """results: Liste (attSet, Geist ja/nein), absteigender attSet.

    Liefert den niedrigsten sauberen attSet oberhalb des ersten Geists und
    den ersten attSet mit Geist. Die Schwelle liegt dazwischen."""
    first_ghost = next((att for att, ghost in results if ghost), None)
    last_clean = min(
        (att for att, ghost in results
         if not ghost and (first_ghost is None or att > first_ghost)),
        default=None,
    )
    return last_clean, first_ghost


# ======================================================
# TEMPERATURREIHE
# ======================================================

class Temperaturreihe:

    def __init__(self, controller, dynamic_probe):
        self.controller = controller
        self.dynamic_probe = dynamic_probe
        self.started = time.monotonic()
        self.reference_attset = gt.FALLBACK_REFERENCE_ATTSET
        self.summary_rows = []
        self.cycle_rows = []
        self.temperature_rows = []
        self.pauses = 0

    # ---------- Zeit und Temperatur ----------

    def minutes(self):
        return (time.monotonic() - self.started) / 60

    def read_temperature(self, phase):
        try:
            self.controller._read_radest_temperature()
        except Exception:
            pass
        temperature = getattr(self.controller, "radest_temperature_c", None)
        self.temperature_rows.append({
            "minuten": round(self.minutes(), 2),
            "temperatur_c": temperature,
            "phase": phase,
        })
        return temperature

    def wait(self, seconds, phase):
        """Wartet und protokolliert dabei die Temperatur."""
        end = time.monotonic() + seconds
        next_log = time.monotonic()
        while True:
            now = time.monotonic()
            if now >= end:
                break
            if now >= next_log:
                temperature = self.read_temperature(phase)
                remaining = end - now
                print(f"\r   warte {remaining / 60:4.1f} min  "
                      f"RadEsT {temperature} °C   ", end="", flush=True)
                next_log = now + TEMPERATURE_LOG_INTERVAL_S
            time.sleep(min(1.0, end - now))
        print()

    # ---------- Zuendung ----------

    def vehicle_responds(self):
        try:
            signals = self.controller.vehicle.get_available_signals()
            wanted = ["distance"] if "distance" in signals else signals[:1]
            self.controller.vehicle.read_signals(wanted)
            return True
        except Exception:
            return False

    def ensure_ignition(self):
        """Pausiert, bis die Diagnose wieder antwortet."""
        if self.vehicle_responds():
            return
        self.pauses += 1
        started = time.monotonic()
        while not self.vehicle_responds():
            print("\a\n>>> Keine Diagnoseantwort. Zuendung einschalten "
                  "(Radar aktiv) und Enter druecken.")
            input("    Enter, wenn die Zuendung an ist: ")
            time.sleep(2.0)
        paused_s = time.monotonic() - started
        self.temperature_rows.append({
            "minuten": round(self.minutes(), 2),
            "temperatur_c": getattr(self.controller, "radest_temperature_c", None),
            "phase": f"pause_zuendung_{paused_s:.0f}s",
        })
        print(f"   Diagnose antwortet wieder (Pause {paused_s:.0f} s).")

    # ---------- einzelne Tests ----------

    def run_with_retry(self, kind, metadata, rcs_dbsm, distance_or_test, duration_s=None):
        for attempt in range(1, MAX_RETRIES_PER_TEST + 1):
            self.ensure_ignition()
            try:
                if kind == "static":
                    samples, skip = gt.run_static(
                        self.controller, distance_or_test, rcs_dbsm,
                        duration_s, metadata,
                    )
                else:
                    samples, skip = gt.run_dynamic(
                        self.controller, distance_or_test, rcs_dbsm, metadata,
                    )
                return samples, skip
            except KeyboardInterrupt:
                raise
            except Exception as error:
                print(f"\n   Test unterbrochen: {error}")
                if self.vehicle_responds():
                    if attempt == MAX_RETRIES_PER_TEST:
                        raise
                    print("   Diagnose antwortet, Test wird wiederholt.")
                else:
                    print("   Vermutlich ist die Zuendung aus.")
        raise RuntimeError("Test auch nach mehreren Versuchen nicht moeglich")

    def record(self, cycle, label, rcs_dbsm, attset, summary, temperature, note=""):
        tests = self.controller.test_run.data.get("tests", []) if summary else []
        self.summary_rows.append({
            "test_id": tests[-1]["test_id"] if tests else "",
            "zyklus": cycle,
            "minuten": round(self.minutes(), 2),
            "temperatur_c": temperature,
            "label": label,
            "rcs_dbsm": rcs_dbsm,
            "attset": "" if attset is None else attset,
            "ergebnis": note if summary is None else gt.result_text(summary),
            "geist_punkte": "" if summary is None else summary["ghost_samples"],
            "punkte": "" if summary is None else summary["samples"],
            "geist_ab_soll_m": (
                "" if summary is None or summary["first_ghost_target_m"] is None
                else round(summary["first_ghost_target_m"], 1)
            ),
        })

    def reference(self, cycle, label):
        metadata = {"block": f"Z{cycle}", "label": label, "role": "reference"}
        samples, skip = self.run_with_retry(
            "static", metadata, gt.REFERENCE_RCS_DBSM,
            gt.REFERENCE_DISTANCE_M, REFERENCE_DURATION_S,
        )
        if skip:
            raise RuntimeError(f"Referenz nicht moeglich: {skip}")
        attset = gt.current_attset(self.controller, "static")
        if attset is not None:
            self.reference_attset = attset
        temperature = getattr(self.controller, "radest_temperature_c", None)
        self.record(cycle, label, gt.REFERENCE_RCS_DBSM, attset,
                    gt.summarize_samples(samples), temperature)
        return temperature

    def cycle(self, cycle, ladder_top, phase):
        print("\n" + "=" * 70)
        print(f"ZYKLUS {cycle}  ({phase}, {self.minutes():.1f} min seit Start)")
        print("=" * 70)

        temperature_start = self.reference(cycle, "Referenz Zyklusstart")
        print(f"   RadEsT {temperature_start} °C, Referenz-attSet "
              f"{self.reference_attset}")

        results = []
        steps = ladder_steps(ladder_top)
        index = 0
        restarted = False
        ghosts_in_row = 0

        while index < len(steps):
            attset = steps[index]
            rcs = gt.rcs_for_attset(attset, LADDER_DISTANCE_M, self.reference_attset)
            label = f"Z{cycle} statisch {LADDER_DISTANCE_M:g} m, attSet {attset:g}"
            metadata = {"block": f"Z{cycle}", "label": label,
                        "target_attset": attset, "role": "test"}
            print(f"\n   {label}  (RCS {rcs:g} dBsm)")
            samples, skip = self.run_with_retry(
                "static", metadata, rcs, LADDER_DISTANCE_M, STEP_DURATION_S,
            )
            temperature = getattr(self.controller, "radest_temperature_c", None)
            if skip:
                print(f"   uebersprungen: {skip}")
                self.record(cycle, label, rcs, None, None, temperature,
                            f"uebersprungen: {skip}")
                index += 1
                continue

            summary = gt.summarize_samples(samples)
            measured = gt.current_attset(self.controller, "static")
            self.record(cycle, label, rcs, measured, summary, temperature)
            ghost = summary["has_ghost"]
            print(f"   attSet={measured}  T={temperature} °C  ->  "
                  f"{gt.result_text(summary)}")

            if ghost:
                self.reference(cycle, "Reset nach Geist")

            # Schon die erste Stufe geistert: Leiter lag zu tief, neu von oben.
            if ghost and index == 0 and not restarted and ladder_top < LADDER_TOP_ATTSET:
                print("   Schwelle liegt hoeher als erwartet, Leiter startet neu "
                      f"bei attSet {LADDER_TOP_ATTSET:g}.")
                steps = ladder_steps(LADDER_TOP_ATTSET)
                restarted = True
                results = []
                ghosts_in_row = 0
                index = 0
                continue

            results.append((attset, ghost))
            ghosts_in_row = ghosts_in_row + 1 if ghost else 0
            if ghosts_in_row >= GHOSTS_TO_STOP:
                break
            index += 1

        last_clean, first_ghost = threshold_from_results(results)

        dynamic_onset = ""
        if self.dynamic_probe:
            test = dict(DYNAMIC_PROBE)
            rcs = gt.rcs_for_attset(DYNAMIC_PROBE_ATTSET, test["start_distance_m"],
                                    self.reference_attset)
            label = (f"Z{cycle} weg {test['start_distance_m']}->"
                     f"{test['end_distance_m']} m, Modus {test['mode']}, "
                     f"attSet {DYNAMIC_PROBE_ATTSET:g}")
            metadata = {"block": f"Z{cycle}", "label": label,
                        "target_attset": DYNAMIC_PROBE_ATTSET, "role": "test"}
            print(f"\n   {label}  (RCS {rcs:g} dBsm)")
            samples, skip = self.run_with_retry("dynamic", metadata, rcs, test)
            temperature = getattr(self.controller, "radest_temperature_c", None)
            if skip:
                self.record(cycle, label, rcs, None, None, temperature,
                            f"uebersprungen: {skip}")
            else:
                summary = gt.summarize_samples(samples)
                self.record(cycle, label, rcs,
                            gt.current_attset(self.controller, "dynamic"),
                            summary, temperature)
                print(f"   -> {gt.result_text(summary)}")
                if summary["first_ghost_target_m"] is not None:
                    dynamic_onset = round(summary["first_ghost_target_m"], 1)
                if summary["has_ghost"]:
                    self.reference(cycle, "Reset nach Geist")

        temperature_end = self.read_temperature(phase)
        row = {
            "zyklus": cycle,
            "phase": phase,
            "minuten_start": round((self.cycle_started - self.started) / 60, 2),
            "temperatur_start_c": temperature_start,
            "temperatur_ende_c": temperature_end,
            "referenz_attset": self.reference_attset,
            "sauber_bis_attset": "" if last_clean is None else last_clean,
            "geist_ab_attset": "" if first_ghost is None else first_ghost,
            "dynamisch_geist_ab_m": dynamic_onset,
        }
        self.cycle_rows.append(row)
        print(f"\n   Zyklus {cycle}: sauber bis attSet {row['sauber_bis_attset']}, "
              f"Geist ab {row['geist_ab_attset']}, "
              f"RadEsT {temperature_start} -> {temperature_end} °C")
        return first_ghost, temperature_end

    def run_phase(self, phase, first_cycle, max_cycles, stop_when_stable, max_minutes):
        cycle = first_cycle
        last_ghost = None
        temperatures = []
        while True:
            self.cycle_started = time.monotonic()
            top = LADDER_TOP_ATTSET if phase == "abgekuehlt" and cycle == first_cycle \
                else next_ladder_top(last_ghost)
            ghost, temperature = self.cycle(cycle, top, phase)
            if ghost is not None:
                last_ghost = ghost
            temperatures.append(temperature)
            done_cycles = cycle - first_cycle + 1

            if max_cycles is not None and done_cycles >= max_cycles:
                break
            if stop_when_stable and done_cycles >= MIN_CYCLES \
                    and temperature_is_stable(temperatures):
                print("\nTemperatur stabil, Aufwaermphase beendet.")
                break
            if self.minutes() >= max_minutes:
                print("\nMaximale Dauer erreicht.")
                break

            elapsed = time.monotonic() - self.cycle_started
            if elapsed < CYCLE_INTERVAL_S:
                self.wait(CYCLE_INTERVAL_S - elapsed, phase)
            cycle += 1
        return cycle

    def write_files(self, directory):
        directory = Path(directory)
        written = []
        for name, rows in (
            ("temperatur_zyklen.csv", self.cycle_rows),
            ("temperaturverlauf.csv", self.temperature_rows),
            ("testplan_summary.csv", self.summary_rows),
        ):
            if not rows:
                continue
            fieldnames = list(rows[0].keys())
            for row in rows[1:]:
                for key in row:
                    if key not in fieldnames:
                        fieldnames.append(key)
            path = directory / name
            with open(path, "w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, fieldnames=fieldnames, delimiter=";")
                writer.writeheader()
                writer.writerows(rows)
            written.append(path)
        return written


# ======================================================
# HAUPTPROGRAMM
# ======================================================

def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", default="", help="Fahrzeugname fuer das ZIP")
    parser.add_argument("--fahrzeug", type=int, default=VEHICLE_ID)
    parser.add_argument("--dynamisch", action="store_true",
                        help="pro Zyklus zusaetzlich eine Fahrt Modus 0, attSet 4")
    parser.add_argument("--intervall-minuten", type=float,
                        default=CYCLE_INTERVAL_S / 60)
    parser.add_argument("--max-minuten", type=float, default=MAX_MINUTES,
                        help="Hoechstdauer der Aufwaermphase, 0 = unbegrenzt")
    parser.add_argument("--ohne-gegenprobe", action="store_true",
                        help="nach dem Aufwaermen nicht abkuehlen lassen")
    parser.add_argument("--abkuehl-minuten", type=float, default=COOLDOWN_MINUTES)
    parser.add_argument("--plan", action="store_true",
                        help="nur den Ablauf anzeigen")
    return parser.parse_args()


def print_plan(args):
    print("Temperaturreihe")
    print(f"  Zyklus alle {args.intervall_minuten:g} min, Leiter "
          f"{LADDER_DISTANCE_M:g} m statisch, attSet {LADDER_TOP_ATTSET:g} -> "
          f"{LADDER_BOTTOM_ATTSET:g} in {LADDER_STEP_ATTSET:g}er-Schritten "
          f"({STEP_DURATION_S:g} s je Stufe)")
    print(f"  Leiter bricht nach {GHOSTS_TO_STOP} Geistern in Folge ab und "
          f"startet im naechsten Zyklus {LADDER_HEADROOM_ATTSET:g} attSet "
          "ueber der letzten Schwelle")
    if args.dynamisch:
        print(f"  Dynamische Probe: Modus 0, weg 15 -> 100 m, attSet "
              f"{DYNAMIC_PROBE_ATTSET:g}")
    print(f"  Ende Aufwaermen: Temperatur aendert sich ueber {STABLE_CYCLES} "
          f"Zyklen um < {STABLE_DELTA_C} °C (mind. {MIN_CYCLES} Zyklen, "
          + ("ohne Zeitlimit)" if args.max_minuten <= 0 or args.max_minuten == float("inf")
             else f"max. {args.max_minuten:g} min)"))
    if args.ohne_gegenprobe:
        print("  Keine Gegenprobe")
    else:
        print(f"  Gegenprobe: RadEsT {args.abkuehl_minuten:g} min im Sleep, "
              f"dann {COOLDOWN_CYCLES} Zyklen")
    print("  Zuendung aus? Das Skript pausiert und wartet auf Enter.")


def main(controller_factory=None):
    args = parse_args()
    if args.max_minuten <= 0:
        args.max_minuten = float("inf")
    global CYCLE_INTERVAL_S
    CYCLE_INTERVAL_S = args.intervall_minuten * 60
    name = safe_name(args.name)

    print_plan(args)
    if args.plan:
        return

    print("\nVorher: RadEsT mehrere Stunden aus (kalt), Fahrzeug-Radar schon "
          "30 min an, Aufbau nicht mehr anfassen.")
    input("RadEsT jetzt einschalten, dann Enter: ")

    if controller_factory is None:
        from test_controller import TestController
        controller_factory = TestController

    controller = controller_factory(vehicle_id=args.fahrzeug)
    reihe = Temperaturreihe(controller, args.dynamisch)
    run_directory = None

    try:
        controller.connect()
        test_run = controller.start_test_run()
        run_directory = test_run["directory"]
        controller.test_run.data["temperaturreihe"] = {
            "name": name,
            "intervall_minuten": args.intervall_minuten,
            "dynamische_probe": args.dynamisch,
        }
        controller.skip_precheck()
        print(f"\nTestRun: {test_run['run_id']}")

        next_cycle = reihe.run_phase(
            "aufwaermen", 1, None, True, args.max_minuten,
        )

        if not args.ohne_gegenprobe:
            print(f"\nGegenprobe: RadEsT geht fuer {args.abkuehl_minuten:g} min "
                  "in den Sleep-Modus.")
            try:
                controller.radest.sleep(True)
                reihe.temperature_rows.append({
                    "minuten": round(reihe.minutes(), 2),
                    "temperatur_c": None, "phase": "sleep_an",
                })
                end = time.monotonic() + args.abkuehl_minuten * 60
                while time.monotonic() < end:
                    remaining = (end - time.monotonic()) / 60
                    print(f"\r   Abkuehlen, noch {remaining:4.1f} min   ",
                          end="", flush=True)
                    time.sleep(5)
                print()
                controller.radest.sleep(False)
                time.sleep(10)
                reihe.run_phase(
                    "abgekuehlt", next_cycle + 1, COOLDOWN_CYCLES, False,
                    float("inf"),
                )
            except Exception as error:
                print(f"\nGegenprobe nicht moeglich: {error}")

        print("\nTemperaturreihe abgeschlossen.")

    except KeyboardInterrupt:
        print("\nTemperaturreihe mit Ctrl+C abgebrochen.")
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
            for path in reihe.write_files(run_directory):
                print(f"Datei: {path}")
            run_path = Path(run_directory)
            archive = shutil.make_archive(
                str(run_path) + (f"_{name}" if name else ""), "zip",
                root_dir=run_path.parent, base_dir=run_path.name,
            )
            print(f"\nDauer: {reihe.minutes():.0f} min, "
                  f"Zuendungspausen: {reihe.pauses}")
            print(f"ZIP zum Verschicken: {archive}")


if __name__ == "__main__":
    main()
