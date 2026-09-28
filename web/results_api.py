import csv
import json
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse


TEST_RUNS_DIR = Path(__file__).resolve().parents[1] / "test_runs"

router = APIRouter(prefix="/api/results", tags=["results"])


def _vehicle_name(data):
    vehicle = data.get("vehicle") or {}
    parts = []

    for field in (
        "manufacturer",
        "brand",
        "make",
        "model",
        "generation",
        "variant",
    ):
        value = vehicle.get(field)
        if value and str(value) not in parts:
            parts.append(str(value))

    return " ".join(parts) or f"Fahrzeug {data.get('vehicle_id', '–')}"


def _run_directory(run_id):
    base = TEST_RUNS_DIR.resolve()
    directory = (base / run_id).resolve()

    if directory.parent != base or not directory.is_dir():
        raise HTTPException(status_code=404, detail="TestRun nicht gefunden")

    return directory


def _read_run(run_id):
    metadata_file = _run_directory(run_id) / "run.json"

    if not metadata_file.is_file():
        raise HTTPException(status_code=404, detail="run.json nicht gefunden")

    try:
        return json.loads(metadata_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=500,
            detail=f"TestRun-Metadaten können nicht gelesen werden: {error}",
        ) from error


def _find_test(data, test_id):
    for test in data.get("tests") or []:
        if str(test.get("test_id")) == test_id:
            return test

    raise HTTPException(status_code=404, detail="Messung nicht gefunden")


def _measurement_file(run_id, test):
    file_name = test.get("log_file")

    if not file_name or Path(file_name).name != file_name:
        raise HTTPException(status_code=404, detail="Messdatei nicht hinterlegt")

    run_directory = _run_directory(run_id)
    file_path = (run_directory / file_name).resolve()

    if file_path.parent != run_directory.resolve() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Messdatei nicht gefunden")

    return file_path


def _number(value):
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def _quick_check_status(quick_check):
    if not quick_check:
        return "pending"

    summary = quick_check.get("identification_summary") or {}
    mismatches = int(summary.get("mismatch") or 0)
    read_errors = int(summary.get("read_error") or 0)
    dtc_count = sum(
        len(ecu.get("dtcs") or [])
        for ecu in quick_check.get("dtcs_before") or []
    )

    return "warning" if mismatches or read_errors or dtc_count or quick_check.get("dtc_error") else "success"


def _run_summary(data):
    tests = data.get("tests") or []
    types = sorted({test.get("type") for test in tests if test.get("type")})
    precheck = data.get("precheck") or {}

    return {
        "run_id": data.get("run_id"),
        "vehicle_id": data.get("vehicle_id"),
        "vehicle_name": _vehicle_name(data),
        "start_time": data.get("start_time"),
        "end_time": data.get("end_time"),
        "status": data.get("status", "unknown"),
        "test_count": len(tests),
        "test_types": types,
        "quick_check_status": _quick_check_status(data.get("quick_check")),
        "precheck_status": (
            "skipped"
            if precheck.get("skipped")
            else "completed" if precheck else "pending"
        ),
        "git_commit": (data.get("software") or {}).get("git_commit"),
    }


def _read_measurement(file_path):
    points = []
    error_values = []
    dropout_count = 0
    error_sample_count = 0

    try:
        with file_path.open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file, delimiter=";"):
                elapsed = _number(row.get("elapsed_s"))
                radest = _number(row.get("radest_distance_m"))
                vehicle = _number(row.get("vehicle_distance"))
                distance_error = _number(row.get("distance_error_m"))

                if vehicle is None:
                    dropout_count += 1

                if row.get("sample_status") not in (None, "", "ok"):
                    error_sample_count += 1

                if distance_error is None and radest is not None and vehicle is not None:
                    distance_error = vehicle - radest

                if distance_error is not None:
                    error_values.append(abs(distance_error))

                points.append({
                    "elapsed_s": elapsed,
                    "radest_distance_m": radest,
                    "vehicle_distance_m": vehicle,
                    "distance_error_m": distance_error,
                    "phase": row.get("phase") or None,
                    "sample_status": row.get("sample_status") or "ok",
                })
    except (OSError, csv.Error) as error:
        raise HTTPException(
            status_code=500,
            detail=f"Messdatei kann nicht gelesen werden: {error}",
        ) from error

    elapsed_values = [
        point["elapsed_s"]
        for point in points
        if point["elapsed_s"] is not None
    ]

    return points, {
        "sample_count": len(points),
        "valid_distance_points": sum(
            point["radest_distance_m"] is not None
            and point["vehicle_distance_m"] is not None
            for point in points
        ),
        "dropout_count": dropout_count,
        "error_sample_count": error_sample_count,
        "duration_s": max(elapsed_values) if elapsed_values else None,
        "mean_absolute_error_m": (
            sum(error_values) / len(error_values)
            if error_values else None
        ),
        "max_absolute_error_m": max(error_values) if error_values else None,
    }


@router.get("")
def list_results():
    results = []

    if TEST_RUNS_DIR.is_dir():
        for metadata_file in TEST_RUNS_DIR.glob("*/run.json"):
            try:
                data = json.loads(metadata_file.read_text(encoding="utf-8"))
                results.append(_run_summary(data))
            except (OSError, json.JSONDecodeError):
                continue

    results.sort(key=lambda item: item.get("start_time") or "", reverse=True)
    return {"results": results}


@router.get("/{run_id}/measurements/{test_id}")
def get_measurement(run_id: str, test_id: str):
    data = _read_run(run_id)
    test = _find_test(data, test_id)
    points, summary = _read_measurement(_measurement_file(run_id, test))

    return {
        "run": _run_summary(data),
        "measurement": test,
        "summary": summary,
        "points": points,
    }


@router.get("/{run_id}/measurements/{test_id}/download")
def download_measurement(run_id: str, test_id: str):
    data = _read_run(run_id)
    test = _find_test(data, test_id)
    file_path = _measurement_file(run_id, test)

    return FileResponse(
        file_path,
        media_type="text/csv",
        filename=file_path.name,
    )


@router.get("/{run_id}/download")
def download_run(run_id: str):
    file_path = _run_directory(run_id) / "run.json"

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="run.json nicht gefunden")

    return FileResponse(
        file_path,
        media_type="application/json",
        filename=f"{run_id}_run.json",
    )


@router.delete("/{run_id}")
def delete_result(run_id: str):
    directory = _run_directory(run_id)

    try:
        shutil.rmtree(directory)
    except OSError as error:
        raise HTTPException(
            status_code=500,
            detail=f"TestRun kann nicht gelöscht werden: {error}",
        ) from error

    return {
        "deleted": True,
        "run_id": run_id,
    }


@router.get("/{run_id}")
def get_result(run_id: str):
    data = _read_run(run_id)
    return {
        "summary": _run_summary(data),
        "run": data,
    }
