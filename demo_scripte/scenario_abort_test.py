"""Testet, ob sich ein laufendes RadEsT-Szenario vorzeitig abbrechen laesst.

Laut Bedienungsanleitung gibt es keinen Befehl zum Stoppen eines Szenarios.
Dieses Skript probiert deshalb verschiedene Wege aus und protokolliert mit
Zeitstempel, was das Geraet jeweils antwortet:

    warten              Referenzlauf ohne Abbruch. Zeigt, wann die Antwort
                        auf SCEN:TRIG kommt (sofort oder erst am Ende).
    trennen             TCP-Verbindung waehrend des Szenarios schliessen
                        und danach neu verbinden.
    zweite_verbindung   Waehrend des Szenarios eine zweite TCP-Verbindung
                        oeffnen und dort BEFEHL senden.
    gleiche_verbindung  Waehrend des Szenarios BEFEHL auf derselben
                        Verbindung senden, auf der SCEN:TRIG noch wartet.

Beispiele fuer BEFEHL (--befehl): "*IDN?" (harmlos, Standard),
"TARGET:SET:DISTANCE 10", "SYST:SLE 1", "*RST", "SYST:PRES".
*RST und SYST:PRES setzen Polarisation, Antennen, Luftspalt usw. auf
Werkseinstellungen zurueck. Danach muss der Precheck wiederholt werden.

Nachweis ohne Fahrzeug: Direkt nach dem Abbruchversuch startet das Skript
auf der noch offenen Verbindung ein neues Szenario (abschaltbar mit
--kein-neustart) und misst, wann dessen Antwort kommt:

    Antwort ca. Szenariodauer nach dem Neustart
        -> das Geraet hat sofort neu begonnen, der Abbruch hat funktioniert.
    Antwort ca. Szenariodauer nach dem Ende des ersten Szenarios
        -> das neue Szenario musste warten, der Abbruch hat nicht gewirkt.

Beim Referenzlauf "warten" wird kein neues Szenario gestartet.

Zusaetzlich kann das Fahrzeugradar mitgelesen werden. Dazu VEHICLE_ID setzen
(oder --fahrzeug angeben). Dann wird parallel das Signal "distance" ueber
CAN protokolliert.

Voraussetzung: Polarisation und Antennen sind am RadEsT bereits passend
eingestellt (z. B. durch einen vorherigen Precheck in der Weboberflaeche).
Die Weboberflaeche darf waehrend des Tests nicht verbunden sein.

Die Datei device.py wird nicht verwendet, damit jede Rohantwort des Geraets
mit Zeitstempel sichtbar ist. Alle Ereignisse landen zusaetzlich als CSV
unter test_runs/scenario_abort_<Zeitstempel>/.

Start aus dem Projektordner:
    python demo_scripte/scenario_abort_test.py --methode warten
    python demo_scripte/scenario_abort_test.py --methode trennen
    python demo_scripte/scenario_abort_test.py --methode zweite_verbindung --befehl "*IDN?"
"""

import argparse
import csv
import queue
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ======================================================
# KONFIGURATION
# ======================================================

RADEST_IP = "192.168.0.10"
RADEST_PORT = 2101

# Bewusst langes Szenario: 5 m -> 40 m bei 5 km/h dauert ca. 25 s.
START_DISTANCE_M = 5.0
END_DISTANCE_M = 40.0
VELOCITY_KMH = 5.0

# 0 = RCS konstant, 1 = RCS variabel (wie in der Weboberflaeche)
RCS_CONSTANT_STATE = 0

# None = Mitte des vom RadEsT gemeldeten RCS-Bereichs
RCS_DBSM = None

# Nach so vielen Sekunden wird der Abbruch versucht.
ABORT_AFTER_S = 5.0

# So lange wird nach dem erwarteten Szenarioende noch beobachtet.
OBSERVE_AFTER_END_S = 5.0

# Abweichung, bis zu der eine Antwortzeit noch einer Erwartung zugeordnet wird.
TIMING_TOLERANCE_S = 3.0

# None = kein Fahrzeug mitlesen, sonst ID aus der Datenbank
VEHICLE_ID = None
VEHICLE_INTERVAL_S = 0.2

METHODS = ("warten", "trennen", "zweite_verbindung", "gleiche_verbindung")

# Diese Befehle setzen die Geraeteeinstellungen zurueck.
RESETTING_COMMANDS = ("*RST", "SYST:PRES", "SYSTEM:PRESET")

# Zustand, der vor und nach dem Test abgefragt und verglichen wird.
STATE_QUERIES = [
    "SYSTEM:GET:POLARIZATION:77GHZ:SETTING?",
    "SYSTEM:GET:TX?",
    "SYSTEM:GET:RX?",
    "SYSTEM:GET:AIRGAP?",
    "SYSTEM:GET:CENTERFREQ?",
    "SYSTEM:GET:BANDWIDTH?",
    "SYSTEM:GET:ATTENUATION?",
    "TARGET:GET:DISTANCE?",
]


# ======================================================
# EREIGNISPROTOKOLL
# ======================================================

class EventLog:
    """Schreibt Ereignisse mit Zeit seit Skriptstart auf Konsole und CSV."""

    def __init__(self, directory):
        self._start = time.perf_counter()
        self._lock = threading.Lock()
        self.file_path = directory / "events.csv"
        self._file = open(self.file_path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file, delimiter=";")
        self._writer.writerow(["t_s", "quelle", "ereignis", "daten"])
        self.events = []

    def now(self):
        return time.perf_counter() - self._start

    def write(self, source, event, data=""):
        t_s = self.now()

        with self._lock:
            print(f"{t_s:8.3f} s  {source:<10} {event:<18} {data}")
            self._writer.writerow([f"{t_s:.3f}", source, event, data])
            self._file.flush()
            self.events.append((t_s, source, event, data))

        return t_s

    def close(self):
        with self._lock:
            self._file.close()


# ======================================================
# MINIMALE SCPI-VERBINDUNG
# ======================================================

class RawScpiConnection:
    """TCP-Verbindung, die jede empfangene Antwort sofort protokolliert.

    Ein eigener Lesethread nimmt alle Daten entgegen. Dadurch bleibt
    sichtbar, wann das Geraet antwortet, auch wenn gerade niemand auf
    eine Antwort wartet.
    """

    def __init__(self, name, log):
        self.name = name
        self.log = log
        self.socket = None
        self.closed = threading.Event()
        self.first_rx_after = {}
        self._answers = queue.Queue()
        self._reader = None

    def connect(self, timeout_s=3.0):
        self.socket = socket.create_connection(
            (RADEST_IP, RADEST_PORT),
            timeout=timeout_s
        )
        self.socket.settimeout(0.2)
        self.closed.clear()
        self._reader = threading.Thread(
            target=self._read_loop,
            name=f"Reader-{self.name}",
            daemon=True
        )
        self._reader.start()
        self.log.write(self.name, "verbunden")

    def _read_loop(self):
        while not self.closed.is_set():
            try:
                data = self.socket.recv(4096)
            except socket.timeout:
                continue
            except OSError as error:
                if not self.closed.is_set():
                    self.log.write(self.name, "lesefehler", repr(error))
                break

            if not data:
                self.log.write(self.name, "vom_geraet_getrennt")
                break

            text = data.decode("utf-8", errors="replace")
            self.log.write(self.name, "RX", repr(text))
            self._answers.put(text)

        self.closed.set()

    def send(self, command):
        self.socket.sendall(f"{command}\0".encode("utf-8"))
        return self.log.write(self.name, "TX", command)

    def query(self, command, timeout_s=3.0, quiet_s=0.3):
        """Sendet einen Befehl und sammelt die Antwort.

        Die Antwort gilt als vollstaendig, wenn nach dem ersten Teil
        quiet_s lang nichts mehr kommt.
        """

        while not self._answers.empty():
            self._answers.get_nowait()

        self.send(command)

        parts = []
        deadline = time.perf_counter() + timeout_s

        while True:
            remaining = deadline - time.perf_counter()

            if remaining <= 0:
                break

            wait_s = quiet_s if parts else remaining

            try:
                parts.append(self._answers.get(timeout=min(wait_s, remaining)))
            except queue.Empty:
                break

        return "".join(parts).strip().strip("\0").strip()

    def close(self):
        self.closed.set()

        if self.socket is None:
            return

        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

        self.socket.close()
        self.log.write(self.name, "geschlossen")


# ======================================================
# FAHRZEUG MITLESEN (OPTIONAL)
# ======================================================

class VehicleMonitor:
    """Liest zyklisch die Objektdistanz des Fahrzeugradars."""

    def __init__(self, vehicle_id, log):
        from diagnostics.vehicle import VehicleDiagnostic

        self.log = log
        self.vehicle = VehicleDiagnostic(vehicle_id=vehicle_id)
        self.stop_event = threading.Event()
        self.thread = None
        self.signals = [
            signal
            for signal in ("distance", "status")
            if signal in self.vehicle.get_available_signals()
        ]

        if "distance" not in self.signals:
            raise RuntimeError(
                f"Fahrzeug {vehicle_id} hat kein Signal 'distance'"
            )

    def start(self):
        self.vehicle.connect()
        self.thread = threading.Thread(
            target=self._loop,
            name="VehicleMonitor",
            daemon=True
        )
        self.thread.start()

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                values = self.vehicle.read_signals(self.signals)
                text = "  ".join(
                    f"{name}={values[name]['value']}"
                    for name in self.signals
                )
                self.log.write("fahrzeug", "messwert", text)
            except Exception as error:
                self.log.write("fahrzeug", "lesefehler", repr(error))

            self.stop_event.wait(VEHICLE_INTERVAL_S)

    def stop(self):
        self.stop_event.set()

        if self.thread is not None:
            self.thread.join(timeout=2.0)

        self.vehicle.disconnect()


# ======================================================
# ABLAUF
# ======================================================

def read_state(connection):
    return {
        command: connection.query(command)
        for command in STATE_QUERIES
    }


def configure_scenario(connection, log):
    """Konfiguriert das Szenario wie TestController.prepare_dynamic_measurement."""

    connection.query(f"SCENARIO:DISTANCE:START {START_DISTANCE_M}")
    connection.query(f"SCENARIO:DISTANCE:END {END_DISTANCE_M}")
    connection.query(f"SCENARIO:VELOCITY {VELOCITY_KMH}")
    connection.query(f"SCENARIO:RCS:CONST {RCS_CONSTANT_STATE}")
    connection.query(f"TARGET:SET:DISTANCE {START_DISTANCE_M}")

    limits = connection.query("SCENARIO:RCS:LIMITS?", timeout_s=10.0)
    values = [value.strip().strip('"') for value in limits.split(",")]

    if len(values) != 4:
        raise RuntimeError(f"Unerwartete RCS-Grenzen: {limits!r}")

    rcs_min = float(values[2])
    rcs_max = float(values[3])
    rcs = RCS_DBSM if RCS_DBSM is not None else (rcs_min + rcs_max) / 2

    if not rcs_min <= rcs <= rcs_max:
        raise RuntimeError(
            f"RCS {rcs} dBsm liegt nicht in {rcs_min} ... {rcs_max} dBsm"
        )

    connection.query(f"SCENARIO:RCS {rcs:.2f}", timeout_s=10.0)
    log.write("skript", "rcs_gesetzt", f"{rcs:.2f} dBsm")


def reconnect(log, name, max_wait_s=30.0):
    """Versucht wiederholt, eine neue Verbindung aufzubauen."""

    deadline = time.perf_counter() + max_wait_s
    attempt = 0

    while time.perf_counter() < deadline:
        attempt += 1
        connection = RawScpiConnection(name, log)

        try:
            connection.connect(timeout_s=2.0)
            return connection
        except OSError as error:
            log.write(name, "verbinden_fehler", f"Versuch {attempt}: {error!r}")
            time.sleep(1.0)

    return None


def run(method, command, vehicle_id, restart=True):
    run_directory = (
        PROJECT_ROOT
        / "test_runs"
        / f"scenario_abort_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    run_directory.mkdir(parents=True, exist_ok=True)

    log = EventLog(run_directory)
    main = RawScpiConnection("haupt", log)
    connections = [main]
    monitor = None

    duration_s = abs(END_DISTANCE_M - START_DISTANCE_M) / (VELOCITY_KMH / 3.6)
    trigger_t_s = None
    abort_t_s = None
    restart_t_s = None
    restart_connection = None

    try:
        log.write("skript", "methode", f"{method}  befehl={command!r}")
        main.connect()
        log.write("skript", "idn", main.query("*IDN?"))

        state_before = read_state(main)
        configure_scenario(main, log)

        if vehicle_id is not None:
            monitor = VehicleMonitor(vehicle_id, log)
            monitor.start()

        print(
            f"\nSzenario {START_DISTANCE_M} m -> {END_DISTANCE_M} m "
            f"bei {VELOCITY_KMH} km/h, erwartete Dauer {duration_s:.1f} s."
        )

        if method != "warten":
            print(f"Abbruchversuch nach {ABORT_AFTER_S:.1f} s.")

        input("Enter druecken, um das Szenario zu starten ...")

        trigger_t_s = main.send("SCENARIO:TRIGGER")
        end_t_s = trigger_t_s + duration_s

        if method != "warten":
            time.sleep(max(0.0, trigger_t_s + ABORT_AFTER_S - log.now()))
            abort_t_s = log.write("skript", "abbruch_start", method)

            if method == "trennen":
                main.close()
                new_connection = reconnect(log, "neu")
                connections.append(new_connection)

                # Antwortet das Geraet schon waehrend des Szenarios?
                if new_connection is not None:
                    new_connection.query("*IDN?", timeout_s=5.0)
                    restart_connection = new_connection

            elif method == "zweite_verbindung":
                second = RawScpiConnection("zweite", log)

                try:
                    second.connect()
                    connections.append(second)
                    second.query(command, timeout_s=5.0)
                    restart_connection = second
                except OSError as error:
                    log.write("zweite", "verbinden_fehler", repr(error))

            elif method == "gleiche_verbindung":
                main.send(command)
                restart_connection = main

            log.write("skript", "abbruch_ende", method)

            # Laesst sich direkt ein neues Szenario starten?
            if restart and restart_connection is not None:
                restart_t_s = restart_connection.send("SCENARIO:TRIGGER")

        # Bis nach dem erwarteten Szenarioende beobachten. Mit Neustart so
        # lange, dass auch ein wartendes zweites Szenario fertig werden kann.
        observe_until = end_t_s + OBSERVE_AFTER_END_S

        if restart_t_s is not None:
            observe_until = (
                max(end_t_s, restart_t_s) + duration_s + OBSERVE_AFTER_END_S
            )

        print(
            f"Beobachtung laeuft bis {observe_until - trigger_t_s:.0f} s "
            "nach dem Start ..."
        )

        while log.now() < observe_until:
            time.sleep(0.2)

        observe_end_t_s = log.now()

        # Zustand am Ende ueber eine noch funktionierende Verbindung lesen.
        probe = next(
            (
                connection
                for connection in connections
                if connection is not None and not connection.closed.is_set()
            ),
            None
        )

        if probe is None:
            probe = reconnect(log, "abschluss")
            connections.append(probe)

        if probe is not None:
            if "SLE" in command.upper() and method in (
                "zweite_verbindung", "gleiche_verbindung"
            ):
                probe.query("SYSTEM:SLEEP 0", timeout_s=10.0)

            log.write("skript", "fehlerspeicher", probe.query("SYSTEM:ERROR?"))
            state_after = read_state(probe)
        else:
            state_after = {}

        rx_after_trigger = [
            (t_s, data)
            for t_s, source, event, data in log.events
            if trigger_t_s <= t_s <= observe_end_t_s
            and source == "haupt" and event == "RX"
        ]

        rx_other = [
            (t_s, source, data)
            for t_s, source, event, data in log.events
            if abort_t_s is not None
            and abort_t_s <= t_s <= observe_end_t_s
            and source in ("neu", "zweite") and event == "RX"
        ]

        restart_rx = []

        if restart_t_s is not None:
            restart_rx = [
                t_s
                for t_s, source, event, data in log.events
                if restart_t_s < t_s <= observe_end_t_s
                and source == restart_connection.name and event == "RX"
            ]

        print_summary(
            method, duration_s, trigger_t_s, abort_t_s,
            rx_after_trigger, rx_other, state_before, state_after
        )

        if restart_t_s is not None:
            print_restart_verdict(
                duration_s, trigger_t_s, restart_t_s, restart_rx
            )
        elif method != "warten":
            print("\nKein neues Szenario gestartet.")

        print(f"\nProtokoll: {log.file_path}")

    finally:
        if monitor is not None:
            monitor.stop()

        for connection in connections:
            if connection is not None and not connection.closed.is_set():
                connection.close()

        log.close()


def print_summary(method, duration_s, trigger_t_s, abort_t_s,
                  rx_after_trigger, rx_other, state_before, state_after):
    print("\n" + "=" * 60)
    print("ZUSAMMENFASSUNG")
    print("=" * 60)
    print(f"Methode:                 {method}")
    print(f"Erwartete Szenariodauer: {duration_s:.1f} s")

    if abort_t_s is not None:
        print(f"Abbruchversuch bei:      {abort_t_s - trigger_t_s:.1f} s nach Trigger")

    if rx_after_trigger:
        print("Antworten der Hauptverbindung nach SCEN:TRIG:")

        for t_s, data in rx_after_trigger:
            print(f"  nach {t_s - trigger_t_s:6.2f} s: {data}")
    else:
        print("Keine Antwort der Hauptverbindung nach SCEN:TRIG.")

    if method in ("trennen", "zweite_verbindung"):
        if rx_other:
            print("Antworten der neuen/zweiten Verbindung:")

            for t_s, source, data in rx_other:
                print(f"  {source} nach {t_s - trigger_t_s:6.2f} s: {data}")
        else:
            print("Keine Antwort der neuen/zweiten Verbindung.")

    changed = [
        command
        for command in STATE_QUERIES
        if command in state_after
        and state_before.get(command) != state_after.get(command)
    ]

    print("Geaenderte Geraeteeinstellungen:")

    if not state_after:
        print("  (Zustand nach dem Test nicht lesbar)")
    elif not changed:
        print("  keine")

    for command in changed:
        print(
            f"  {command}: {state_before.get(command)!r} -> "
            f"{state_after.get(command)!r}"
        )

    print(
        "\nHinweis: Ob der Abbruch gewirkt hat, zeigt die Bewertung des "
        "neuen Szenarios\nunten. Mit --fahrzeug zusaetzlich die "
        "Fahrzeugwerte (distance) im Protokoll."
    )


def print_restart_verdict(duration_s, trigger_t_s, restart_t_s, restart_rx):
    """Bewertet anhand der Antwortzeit, ob das neue Szenario sofort lief."""

    end_t_s = trigger_t_s + duration_s
    expected_if_aborted = restart_t_s + duration_s
    expected_if_queued = end_t_s + duration_s

    def relative(t_s):
        return f"{t_s - trigger_t_s:6.1f} s"

    print("\nNEUES SZENARIO DIREKT NACH DEM ABBRUCH (Zeiten ab erstem Start)")
    print(f"  gestartet bei:                          {relative(restart_t_s)}")
    print(f"  Antwort erwartet, falls abgebrochen:    {relative(expected_if_aborted)}")
    print(f"  Antwort erwartet, falls es warten muss: {relative(expected_if_queued)}")

    if not restart_rx:
        print(
            "  Keine Antwort auf das neue SCEN:TRIG erhalten.\n"
            "  -> Ergebnis unklar. Protokoll (events.csv) pruefen."
        )
        return

    # Die letzte Antwort gehoert zum neuen Szenario. Davor koennen z. B.
    # die Antwort auf BEFEHL oder das Ende des ersten Szenarios liegen.
    answer_t_s = restart_rx[-1]
    print(f"  Antwort erhalten bei:                   {relative(answer_t_s)}")

    if answer_t_s - restart_t_s < 1.0:
        print(
            "  -> Antwort kam sofort. Entweder wurde SCEN:TRIG abgelehnt oder\n"
            "     das Geraet antwortet nicht erst am Szenarioende. Referenzlauf\n"
            "     mit --methode warten und die Rohantwort im Protokoll pruefen."
        )
        return

    distance_aborted = abs(answer_t_s - expected_if_aborted)
    distance_queued = abs(answer_t_s - expected_if_queued)

    if min(distance_aborted, distance_queued) > TIMING_TOLERANCE_S:
        print("  -> Passt zu keiner Erwartung. Protokoll (events.csv) pruefen.")
    elif distance_aborted < distance_queued:
        print(
            "  -> Das neue Szenario lief sofort.\n"
            "     Der Abbruch hat funktioniert."
        )
    else:
        print(
            "  -> Das neue Szenario musste warten, bis das erste fertig war.\n"
            "     Der Abbruch hat NICHT funktioniert."
        )


def main():
    global RADEST_IP, RADEST_PORT

    parser = argparse.ArgumentParser(
        description="Abbruch eines laufenden RadEsT-Szenarios testen"
    )
    parser.add_argument("--methode", choices=METHODS, default="warten")
    parser.add_argument("--befehl", default="*IDN?")
    parser.add_argument("--fahrzeug", type=int, default=VEHICLE_ID)
    parser.add_argument("--ip", default=RADEST_IP)
    parser.add_argument("--port", type=int, default=RADEST_PORT)
    parser.add_argument(
        "--kein-neustart",
        action="store_true",
        help="nach dem Abbruchversuch kein neues Szenario starten"
    )
    args = parser.parse_args()

    RADEST_IP = args.ip
    RADEST_PORT = args.port

    if args.befehl.upper().replace(" ", "") in RESETTING_COMMANDS:
        print(
            f"ACHTUNG: {args.befehl} setzt die Geraeteeinstellungen zurueck.\n"
            "Danach muss der Precheck in der Weboberflaeche wiederholt werden."
        )

    run(
        args.methode,
        args.befehl,
        args.fahrzeug,
        restart=not args.kein_neustart
    )


if __name__ == "__main__":
    main()
