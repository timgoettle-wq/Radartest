"""Pendeltest: Ziel faehrt weg und pendelt danach zwischen zwei Distanzen.

Ablauf (Standardwerte):

    Vorhalten bei 15 m  ->  weg bis 35 m  ->  35 -> 25 -> 35 -> 25 ...

Damit laesst sich pruefen, ob ein Sensor ein Ziel, das er beim Wegfahren
erfasst hat, auch beim Herankommen weiter meldet. Der Mercedes erfasst
herankommende Ziele sonst gar nicht.

Der RadEsT kann waehrend eines Szenarios nicht umgesteuert werden. Jede
Strecke ist deshalb ein eigenes Szenario. Zwischen zwei Strecken entsteht
eine kurze Umkehrpause, in der das Ziel an der Umkehrdistanz steht. Die
Fahrzeugdaten werden durchgehend aufgezeichnet, auch in den Pausen.

Alle Strecken landen als ein dynamischer Test in einer CSV. Die Strecken
mit ihren Zeitpunkten und dem attSet stehen in run.json unter "legs".
Am Ende wird der TestRun-Ordner als ZIP gepackt.

Start aus dem Projektordner:
    python demo_scripte/pendel_test.py
    python demo_scripte/pendel_test.py --unten 20 --oben 35 --zyklen 8
    python demo_scripte/pendel_test.py --modus 0 --rcs 15 --v 20
"""

import argparse
import shutil
import sys
import threading
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ======================================================
# KONFIGURATION (per Kommandozeile ueberschreibbar)
# ======================================================

VEHICLE_ID = 1

START_DISTANCE_M = 15.0
UPPER_DISTANCE_M = 35.0
LOWER_DISTANCE_M = 25.0

# Ein Zyklus = oben -> unten -> oben
CYCLES = 5

VELOCITY_KMH = 10.0

# 0 = konstantes RCS (Daempfung wird nachgeregelt), 1 = feste Daempfung
RCS_CONSTANT_STATE = 1
RCS_DBSM = 10.0

PRE_HOLD_S = 5.0
POST_HOLD_S = 5.0

MEASUREMENT_INTERVAL_S = 0.2

WANTED_SIGNALS = [
    "distance",
    "angle",
    "relative_speed",
    "relative_acceleration",
]


def build_legs(start_m, upper_m, lower_m, cycles):
    legs = [(start_m, upper_m)]
    for _ in range(cycles):
        legs.append((upper_m, lower_m))
        legs.append((lower_m, upper_m))
    return legs


# ======================================================
# GEMEINSAMER ZUSTAND FUER DEN MESSTHREAD
# ======================================================

class PendelState:
    """Haelt fest, was der RadEsT gerade tut, damit der Messthread die
    Sollposition berechnen kann, ohne den RadEsT-Socket zu benutzen."""

    def __init__(self, start_m, velocity_kmh):
        self.lock = threading.Lock()
        self.velocity_mps = velocity_kmh / 3.6
        self.phase = "pre_hold"
        self.leg_index = None
        self.leg_start_m = start_m
        self.leg_end_m = start_m
        self.leg_start_ns = None
        self.hold_distance_m = start_m
        self.phase_start_ns = time.perf_counter_ns()

    def start_leg(self, index, start_m, end_m, trigger_ns):
        with self.lock:
            self.phase = "moving"
            self.leg_index = index
            self.leg_start_m = start_m
            self.leg_end_m = end_m
            self.leg_start_ns = trigger_ns
            self.phase_start_ns = trigger_ns

    def finish_leg(self, phase="umkehr"):
        with self.lock:
            self.phase = phase
            self.hold_distance_m = self.leg_end_m
            self.phase_start_ns = time.perf_counter_ns()

    def snapshot(self, now_ns):
        with self.lock:
            phase_elapsed_s = (now_ns - self.phase_start_ns) / 1e9

            if self.phase != "moving":
                return {
                    "phase": self.phase,
                    "progress": None,
                    "phase_elapsed_s": phase_elapsed_s,
                    "leg_index": self.leg_index,
                    "leg_start_m": self.leg_start_m,
                    "leg_end_m": self.leg_end_m,
                    "target_m": self.hold_distance_m,
                    "direction": None,
                }

            length_m = abs(self.leg_end_m - self.leg_start_m)
            duration_s = length_m / self.velocity_mps
            progress = min(1.0, phase_elapsed_s / duration_s)
            target_m = (
                self.leg_start_m
                + (self.leg_end_m - self.leg_start_m) * progress
            )
            approaching = self.leg_end_m < self.leg_start_m
            return {
                # Phase traegt die Streckennummer, damit sie im
                # Ergebnisdiagramm als Marke erscheint, z. B. "hin_3".
                "phase": f"{'hin' if approaching else 'weg'}_{self.leg_index}",
                "progress": progress,
                "phase_elapsed_s": phase_elapsed_s,
                "leg_index": self.leg_index,
                "leg_start_m": self.leg_start_m,
                "leg_end_m": self.leg_end_m,
                "target_m": target_m,
                "direction": "approaching" if approaching else "receding",
            }


# ======================================================
# MESSTHREAD (nur Fahrzeug, kein RadEsT-Zugriff)
# ======================================================

def measurement_loop(vehicle, logger, state, settings, stop_event, start_ns):
    available = vehicle.get_available_signals()
    signals = [name for name in WANTED_SIGNALS if name in available]
    sequence = 0

    while not stop_event.is_set():
        cycle_start = time.perf_counter()
        sequence += 1

        request_ns = time.perf_counter_ns()
        error_message = None
        try:
            vehicle_values = vehicle.read_signals(signals) if signals else {}
        except Exception as error:
            vehicle_values = {}
            error_message = str(error)
        response_ns = time.perf_counter_ns()

        snap = state.snapshot(response_ns)
        vehicle_distance = vehicle_values.get("distance", {}).get("value")

        measurement = {
            "test_type": "dynamic",
            "sample_status": "ok" if error_message is None else "error",
            "error_type": None if error_message is None else "vehicle",
            "error_message": error_message,
            "sequence": sequence,
            "timestamp_ns": response_ns,
            "timestamp_unix_ns": time.time_ns(),
            "elapsed_s": (response_ns - start_ns) / 1e9,
            "measurement_interval_s": MEASUREMENT_INTERVAL_S,
            "vehicle_request_start_ns": request_ns,
            "vehicle_response_ns": response_ns,
            "vehicle_read_duration_ms": (response_ns - request_ns) / 1e6,
            "requested_distance": snap["target_m"],
            "radest_distance": snap["target_m"],
            "radest_distance_source": "pendel_estimate",
            "estimated_scenario_distance": snap["target_m"],
            "rcs_dbsm": settings["rcs_dbsm"],
            "rcs_constant_state": settings["mode"],
            "rcs_limits": settings.get("rcs_limits"),
            "distance_error": (
                None if vehicle_distance is None
                else vehicle_distance - snap["target_m"]
            ),
            "scenario_start_distance": snap["leg_start_m"],
            "scenario_end_distance": snap["leg_end_m"],
            "scenario_velocity_kmh": settings["velocity_kmh"],
            "dynamic_direction": snap["direction"],
            "phase": snap["phase"],
            "phase_elapsed_s": snap["phase_elapsed_s"],
            "scenario_progress": snap["progress"],
            "vehicle": vehicle_values,
        }
        logger.write_measurement(measurement)

        vehicle_text = (
            "--" if vehicle_distance is None else f"{vehicle_distance:6.1f}"
        )
        speed = vehicle_values.get("relative_speed", {}).get("value")
        speed_text = "--" if speed is None else f"{speed:6.2f}"
        leg_text = "-" if snap["leg_index"] is None else snap["leg_index"]
        print(
            f"\r  Strecke {leg_text:>2} {snap['phase']:9s} "
            f"Soll={snap['target_m']:6.1f} m  Fahrzeug={vehicle_text} m  "
            f"v={speed_text}   ",
            end="",
            flush=True,
        )

        remaining = MEASUREMENT_INTERVAL_S - (time.perf_counter() - cycle_start)
        if remaining > 0:
            stop_event.wait(remaining)


# ======================================================
# RADEST-STRECKEN
# ======================================================

def configure_leg(controller, start_m, end_m, settings):
    """Stellt eine Strecke ein und liefert Grenzen und Arbeitspunkt."""

    radest = controller.radest
    radest.scenario_distance_start(start_m)
    radest.scenario_distance_end(end_m)
    radest.scenario_velocity(settings["velocity_kmh"])
    radest.scenario_constant_rcs(settings["mode"])

    limits = controller._parse_rcs_limits(radest.scenario_get_rcs_limits())
    rcs_dbsm = settings["rcs_dbsm"]
    if not limits["rcs_min_dbsm"] <= rcs_dbsm <= limits["rcs_max_dbsm"]:
        raise ValueError(
            f"RCS {rcs_dbsm:g} dBsm fuer {start_m:g} -> {end_m:g} m "
            f"ausserhalb [{limits['rcs_min_dbsm']:.2f}, "
            f"{limits['rcs_max_dbsm']:.2f}]"
        )

    setting = controller._parse_rcs_setting(radest.scenario_set_rcs(rcs_dbsm))
    return limits, setting


def check_all_legs(controller, legs, settings):
    """Prueft vor dem Start alle Strecken gegen die RCS-Grenzen."""

    checked = set()
    for start_m, end_m in legs:
        if (start_m, end_m) in checked:
            continue
        checked.add((start_m, end_m))
        limits, _ = configure_leg(controller, start_m, end_m, settings)
        print(
            f"  {start_m:g} -> {end_m:g} m: RCS-Grenzen "
            f"[{limits['rcs_min_dbsm']:.1f}, {limits['rcs_max_dbsm']:.1f}] ok"
        )


def run_trigger_in_thread(radest):
    """SCENARIO:TRIGGER blockiert bis zum Szenarioende. Im eigenen Thread
    bleibt der Hauptthread fuer Ctrl+C ansprechbar, ohne die laufende
    Socket-Abfrage zu unterbrechen."""

    result = {}

    def worker():
        try:
            radest.scenario_trigger()
        except Exception as error:
            result["error"] = error

    thread = threading.Thread(target=worker, name="PendelTrigger", daemon=True)
    thread.start()
    return thread, result


def wait_for_thread(thread, stop_request):
    while thread.is_alive():
        try:
            thread.join(timeout=0.2)
        except KeyboardInterrupt:
            if not stop_request.is_set():
                stop_request.set()
                print("\n  Abbruch angefordert: die laufende Strecke wird "
                      "noch zu Ende gefahren (RadEsT laesst sich nicht "
                      "unterbrechen).")


# ======================================================
# HAUPTPROGRAMM
# ======================================================

def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fahrzeug", type=int, default=VEHICLE_ID)
    parser.add_argument("--start", type=float, default=START_DISTANCE_M)
    parser.add_argument("--oben", type=float, default=UPPER_DISTANCE_M)
    parser.add_argument("--unten", type=float, default=LOWER_DISTANCE_M)
    parser.add_argument("--zyklen", type=int, default=CYCLES)
    parser.add_argument("--v", type=float, default=VELOCITY_KMH,
                        help="Geschwindigkeit in km/h")
    parser.add_argument("--modus", type=int, choices=(0, 1),
                        default=RCS_CONSTANT_STATE)
    parser.add_argument("--rcs", type=float, default=RCS_DBSM)
    parser.add_argument("--plan", action="store_true",
                        help="Nur den Ablauf anzeigen, nichts verbinden")
    return parser.parse_args()


def main(controller_factory=None):
    args = parse_args()

    if not args.unten < args.oben:
        raise SystemExit("--unten muss kleiner als --oben sein")
    if args.start == args.oben:
        raise SystemExit("--start und --oben muessen verschieden sein")

    legs = build_legs(args.start, args.oben, args.unten, args.zyklen)
    settings = {
        "velocity_kmh": args.v,
        "mode": args.modus,
        "rcs_dbsm": args.rcs,
    }
    velocity_mps = args.v / 3.6
    moving_s = sum(abs(end - start) for start, end in legs) / velocity_mps

    print("Pendeltest")
    print(f"Fahrzeug-ID: {args.fahrzeug}   {args.v:g} km/h   "
          f"Modus {args.modus}   RCS {args.rcs:g} dBsm")
    print("Strecken: " + ", ".join(f"{s:g}->{e:g}" for s, e in legs))
    print(f"Fahrzeit ca. {moving_s + PRE_HOLD_S + POST_HOLD_S:.0f} s "
          f"plus {len(legs) - 1} Umkehrpausen")

    if args.plan:
        return

    if controller_factory is None:
        from test_controller import TestController
        controller_factory = TestController
    from measurement_logger import MeasurementLogger

    controller = controller_factory(vehicle_id=args.fahrzeug)
    stop_event = threading.Event()
    stop_request = threading.Event()
    measurement_thread = None
    logger = None
    run_directory = None
    leg_records = []
    status, reason, error_text = "finished", "pendel_completed", None

    try:
        controller.connect()
        test_run = controller.start_test_run()
        run_directory = test_run["directory"]
        controller.skip_precheck()
        print(f"\nTestRun: {test_run['run_id']}")

        print("RCS-Grenzen pruefen...")
        check_all_legs(controller, legs, settings)

        input("\nEnter startet den Pendeltest, Ctrl+C bricht ab: ")

        # Ziel vor dem Start an die Startdistanz stellen und erste Strecke
        # vorbereiten. Waehrend des Vorhaltens steht das Ziel dort.
        first_limits, first_setting = configure_leg(
            controller, legs[0][0], legs[0][1], settings
        )
        controller.radest.target_set_distance(legs[0][0])
        settings["rcs_limits"] = first_limits
        controller._read_radest_temperature()

        logger = MeasurementLogger(
            vehicle_id=args.fahrzeug,
            run_id=test_run["run_id"],
            log_directory=run_directory,
        )
        logger.start()
        test_id = controller.test_run.start_dynamic_test(
            parameters={
                "test_kind": "pendel",
                "start_distance_m": legs[0][0],
                "end_distance_m": legs[-1][1],
                "upper_distance_m": args.oben,
                "lower_distance_m": args.unten,
                "cycles": args.zyklen,
                "velocity_kmh": args.v,
                "rcs_dbsm": args.rcs,
                "rcs_constant_state": args.modus,
                "rcs_limits": first_limits,
                "rcs_radest_setting": first_setting,
                "pre_hold_s": PRE_HOLD_S,
                "post_hold_s": POST_HOLD_S,
                "planned_legs": [list(leg) for leg in legs],
            },
            log_file=logger.get_file_path(),
        )
        logger.set_test_id(test_id)
        controller.test_run.update_active_test({
            "radest_temperature_start_c": controller.radest_temperature_c,
        })

        state = PendelState(legs[0][0], args.v)
        start_ns = time.perf_counter_ns()
        measurement_thread = threading.Thread(
            target=measurement_loop,
            args=(controller.vehicle, logger, state, settings,
                  stop_event, start_ns),
            name="PendelMessung",
            daemon=True,
        )
        measurement_thread.start()

        print(f"\nVorhalten {PRE_HOLD_S:g} s bei {legs[0][0]:g} m")
        try:
            stop_request.wait(PRE_HOLD_S)
        except KeyboardInterrupt:
            stop_request.set()

        for index, (start_m, end_m) in enumerate(legs):
            if stop_request.is_set():
                status, reason = "aborted", "stopped_by_user"
                break

            configure_ns = time.perf_counter_ns()
            if index == 0:
                setting, limits = first_setting, first_limits
            else:
                limits, setting = configure_leg(
                    controller, start_m, end_m, settings
                )

            trigger_ns = time.perf_counter_ns()
            state.start_leg(index, start_m, end_m, trigger_ns)
            thread, result = run_trigger_in_thread(controller.radest)
            wait_for_thread(thread, stop_request)
            returned_ns = time.perf_counter_ns()
            state.finish_leg()

            if "error" in result:
                raise RuntimeError(
                    f"RadEsT-Fehler in Strecke {index}: {result['error']}"
                ) from result["error"]

            record = {
                "leg": index,
                "start_m": start_m,
                "end_m": end_m,
                "configure_ns": configure_ns,
                "trigger_call_ns": trigger_ns,
                "trigger_returned_ns": returned_ns,
                "configure_duration_s": round((trigger_ns - configure_ns) / 1e9, 3),
                "scenario_duration_s": round((returned_ns - trigger_ns) / 1e9, 3),
                "rcs_limits": limits,
                "rcs_radest_setting": setting,
            }
            leg_records.append(record)
            att = (setting or {}).get("values", {}).get("attSet")
            print(
                f"\n  Strecke {index}: {start_m:g} -> {end_m:g} m fertig "
                f"({record['scenario_duration_s']:.1f} s, "
                f"Umkehr-Vorbereitung {record['configure_duration_s']:.2f} s, "
                f"attSet {att})"
            )

        state.finish_leg(phase="post_hold")
        print(f"\nNachhalten {POST_HOLD_S:g} s")
        try:
            stop_request.wait(POST_HOLD_S)
        except KeyboardInterrupt:
            pass

        print("\nPendeltest abgeschlossen.")

    except KeyboardInterrupt:
        status, reason = "aborted", "stopped_by_user"
        print("\nPendeltest mit Ctrl+C abgebrochen.")

    except Exception as error:
        status, reason, error_text = "failed", "error", str(error)
        print(f"\nFEHLER: {error}")

    finally:
        stop_event.set()
        if measurement_thread is not None:
            measurement_thread.join(timeout=2.0)
        if logger is not None:
            logger.stop()

        if controller.test_run is not None and logger is not None:
            controller.test_run.update_active_test({"legs": leg_records})
            controller.test_run.finish_active_test(
                status=status, reason=reason, error=error_text
            )

        print("Verbindungen werden getrennt...")
        try:
            controller.disconnect()
        except Exception as error:
            print(f"Fehler beim Trennen: {error}")

        if run_directory is not None:
            run_path = Path(run_directory)
            archive = shutil.make_archive(
                str(run_path), "zip",
                root_dir=run_path.parent, base_dir=run_path.name,
            )
            print(f"ZIP zum Verschicken: {archive}")


if __name__ == "__main__":
    main()
