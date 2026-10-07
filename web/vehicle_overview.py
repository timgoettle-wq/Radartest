"""Fahrzeugsteckbrief fuer Schritt 1 und Vergleichswerte fuer den Precheck.

Liest nur: Fahrzeugdaten aus der Datenbank und bisherige TestRuns aus
test_runs/*/run.json. Ohne Controller-Lock, damit die Anzeige auch waehrend
einer laufenden Messung nicht blockiert.
"""

import json
from contextlib import closing
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from database import database
from web import results_api


router = APIRouter(prefix="/api/vehicles", tags=["Fahrzeuge"])


def _ecus(connection, vehicle_id):
    rows = connection.execute(
        """
        SELECT e.*,
            (SELECT COUNT(*) FROM identification_parameters i
             WHERE i.ecu_id = e.id AND i.enabled) AS identification_count,
            (SELECT COUNT(*) FROM diagnostic_parameters d
             WHERE d.ecu_id = e.id) AS parameter_count
        FROM ecus e
        WHERE e.vehicle_id = ?
        ORDER BY e.id
        """,
        (vehicle_id,),
    )

    return [
        {
            "name": row["name"],
            "interface": row["interface"],
            "channel": row["channel"],
            "request_id": row["request_id"],
            "response_id": row["response_id"],
            "identification_count": row["identification_count"],
            "parameter_count": row["parameter_count"],
        }
        for row in rows
    ]


def _start_instant(run):
    # Zeitstempel mit unterschiedlichem UTC-Offset (Sommer-/Winterzeit)
    # nicht als Text, sondern als Zeitpunkt vergleichen.
    try:
        instant = datetime.fromisoformat(run.get("start_time") or "")
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)

    if instant.tzinfo is None:
        instant = instant.astimezone()

    return instant


def _runs_for_vehicle(vehicle_id):
    runs = []

    if not results_api.TEST_RUNS_DIR.is_dir():
        return runs

    for metadata_file in results_api.TEST_RUNS_DIR.glob("*/run.json"):
        try:
            data = json.loads(metadata_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        if str(data.get("vehicle_id")) == str(vehicle_id):
            runs.append(data)

    runs.sort(key=_start_instant, reverse=True)
    return runs


def _last_precheck(runs):
    for run in runs:
        precheck = run.get("precheck") or {}

        if precheck.get("skipped"):
            continue

        values = {
            key: precheck.get(key)
            for key in ("polarization", "frequency_range", "power")
        }

        if any(value not in (None, "") for value in values.values()):
            return {
                "run_id": run.get("run_id"),
                "start_time": run.get("start_time"),
                **values,
            }

    return None


@router.get("/{vehicle_id}/overview")
def vehicle_overview(vehicle_id: int):
    with closing(database.get_connection()) as connection:
        vehicle = connection.execute(
            "SELECT * FROM vehicles WHERE id = ?",
            (vehicle_id,),
        ).fetchone()

        if vehicle is None:
            raise HTTPException(status_code=404, detail="Fahrzeug nicht gefunden")

        ecus = _ecus(connection, vehicle_id)

    runs = _runs_for_vehicle(vehicle_id)

    return {
        "vehicle": dict(vehicle),
        "ecus": ecus,
        "run_count": len(runs),
        "last_run": results_api._run_summary(runs[0]) if runs else None,
        "last_precheck": _last_precheck(runs),
    }
