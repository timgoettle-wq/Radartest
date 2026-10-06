import asyncio
import threading
from pathlib import Path
from html import escape
from fastapi.staticfiles import StaticFiles
from web.database_api import make_database_router
from functools import wraps

from fastapi import (
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse

from database.database import get_vehicles
from test_controller import TestController
from web.results_api import router as results_router
from web.system_time import make_system_time_router


app = FastAPI(
    title="Radar Testsystem"
)


# ==================================================
# AKTUELLER TESTCONTROLLER
# ==================================================

controller = None
selected_vehicle_id = None
controller_lock = threading.RLock()
WEB_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
app.include_router(make_database_router(
    controller_lock, lambda: controller is not None
))
app.include_router(results_router)
app.include_router(make_system_time_router(
    controller_lock,
    lambda: controller is not None and controller.is_measurement_running()
))


@app.get("/database", response_class=HTMLResponse)
def database_page():
    return (WEB_DIR / "templates" / "database.html").read_text(encoding="utf-8")


@app.get("/results", response_class=HTMLResponse)
def results_page():
    return (WEB_DIR / "templates" / "results.html").read_text(encoding="utf-8")


def serialized_controller_access(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        with controller_lock:
            return function(*args, **kwargs)

    return wrapper


# ==================================================
# FAHRZEUGNAME FÜR DROPDOWN
# ==================================================

def get_vehicle_name(vehicle):

    if vehicle.get("name"):
        return vehicle["name"]

    parts = []

    for field in [
        "manufacturer",
        "brand",
        "make",
        "model",
        "variant",
    ]:

        value = vehicle.get(field)

        if value and value not in parts:
            parts.append(str(value))

    if parts:
        return " ".join(parts)

    return f"Fahrzeug {vehicle['id']}"


# ==================================================
# WEBSEITE
# ==================================================

@app.get(
    "/",
    response_class=HTMLResponse
)
def index():

    vehicles = get_vehicles()

    vehicle_options = ""

    for vehicle in vehicles:

        name = get_vehicle_name(
            vehicle
        )

        vehicle_options += (
            f'<option value="{vehicle["id"]}">'
            f"{escape(name)}"
            f"</option>"
        )


    html = (WEB_DIR / "templates" / "index.html").read_text(encoding="utf-8")


    html = html.replace(
        "__VEHICLE_OPTIONS__",
        vehicle_options
    )


    return HTMLResponse(
        content=html
    )


# ==================================================
# API: AKTUELLER WORKFLOW-STATUS
# ==================================================

@app.get("/api/status")
@serialized_controller_access
def get_system_status():

    if controller is None:
        return {
            "connected": False
        }

    latest_measurement = None

    try:
        latest_measurement = (
            controller.get_latest_measurement()
        )
    except RuntimeError:
        # Ein Messfehler wird weiterhin über den vorhandenen
        # WebSocket gemeldet. Der Status-Endpunkt selbst soll
        # für die Wiederherstellung der Oberfläche erreichbar
        # bleiben.
        pass

    test_run_data = (
        controller.test_run.data
        if controller.test_run is not None
        else {}
    )

    log_file = None

    if controller.measurement_logger is not None:
        log_file = (
            controller.measurement_logger
            .get_file_path()
        )

    return {
        "connected": controller.connected,
        "vehicle_id": controller.vehicle_id,
        "signals": controller.get_available_signals(),
        "test_run": controller.get_test_run_info(),
        "quick_check": test_run_data.get("quick_check"),
        "precheck": controller.get_precheck_result(),
        "measurement_running": (
            controller.is_measurement_running()
        ),
        "latest_measurement": latest_measurement,
        "log_file": log_file,
        # Arbeitspunkt des RadEsT (u. a. attSet) für die Anzeige nach
        # einem Neuladen der Seite
        "static_rcs_setting": controller.static_rcs_setting,
        "dynamic_rcs_setting": controller.dynamic_rcs_setting
    }


# ==================================================
# API: VERBINDEN
# ==================================================

@app.post("/api/connect/{vehicle_id}")
@serialized_controller_access
def connect_vehicle(
    vehicle_id: int
):

    global controller
    global selected_vehicle_id


    new_controller = None


    try:

        if controller is not None:

            controller.disconnect()

            controller = None

            selected_vehicle_id = None


        new_controller = TestController(
            vehicle_id=vehicle_id
        )


        new_controller.connect()


        test_run = (
            new_controller.start_test_run()
        )


        controller = new_controller

        selected_vehicle_id = vehicle_id


        return {

            "connected":
                True,

            "vehicle_id":
                vehicle_id,

            "signals":
                controller.get_available_signals(),

            "test_run":
                test_run
        }


    except Exception as error:

        if new_controller is not None:

            try:

                new_controller.disconnect()

            except Exception:

                pass


        controller = None

        selected_vehicle_id = None


        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


# ==================================================
# API: QUICK CHECK
# ==================================================

@app.post("/api/quick-check")
@serialized_controller_access
def run_quick_check():

    if controller is None:

        raise HTTPException(
            status_code=400,
            detail="Testsystem ist nicht verbunden"
        )


    try:

        return (
            controller.run_quick_check()
        )


    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


# ==================================================
# API: RADEST PRECHECK
# ==================================================

@app.post("/api/precheck")
@serialized_controller_access
def run_precheck():

    if controller is None:

        raise HTTPException(
            status_code=400,
            detail="Testsystem ist nicht verbunden"
        )


    try:

        return (
            controller.run_precheck()
        )


    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


def _run_precheck_phase(method_name):

    if controller is None:
        raise HTTPException(
            status_code=400,
            detail="Testsystem ist nicht verbunden"
        )

    try:
        return getattr(controller, method_name)()
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


@app.post("/api/precheck/start")
@serialized_controller_access
def start_precheck():
    return _run_precheck_phase("start_precheck")


@app.post("/api/precheck/polarization")
@serialized_controller_access
def measure_precheck_polarization():
    return _run_precheck_phase("measure_precheck_polarization")


@app.post("/api/precheck/frequency")
@serialized_controller_access
def measure_precheck_frequency():
    return _run_precheck_phase("measure_precheck_frequency")


@app.post("/api/precheck/power")
@serialized_controller_access
def measure_precheck_power():
    return _run_precheck_phase("measure_precheck_power")


@app.post("/api/precheck/skip")
@serialized_controller_access
def skip_precheck():

    if controller is None:

        raise HTTPException(
            status_code=400,
            detail="Testsystem ist nicht verbunden"
        )

    try:
        return controller.skip_precheck()
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


# ==================================================
# API: STATISCHE RCS-GRENZEN ERMITTELN
# ==================================================

@app.post("/api/static/rcs-limits")
@serialized_controller_access
def prepare_static_measurement(
    distance_m: float
):

    if controller is None:
        raise HTTPException(
            status_code=400,
            detail="Testsystem ist nicht verbunden"
        )

    try:
        return controller.prepare_static_measurement(
            distance_m
        )
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


# ==================================================
# API: STATISCHE MESSUNG STARTEN
# ==================================================

@app.post("/api/static/start")
@serialized_controller_access
def start_static_measurement(
    distance_m: float,
    rcs_dbsm: float
):

    if controller is None:

        raise HTTPException(
            status_code=400,
            detail="Testsystem ist nicht verbunden"
        )


    try:

        result = (
            controller.start_static_measurement(
                distance_m,
                rcs_dbsm
            )
        )


        log_file = (
            controller.start_logging()
        )


        controller.start_measurement_loop(
            interval_s=0.2
        )


        result[
            "log_file"
        ] = log_file


        return result


    except Exception as error:

        controller.stop_measurement_loop()

        controller.stop_logging(
            status="failed",
            reason="start_failed",
            error=str(error)
        )

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


# ==================================================
# API: DYNAMISCHE RCS-GRENZEN ERMITTELN
# ==================================================

@app.post("/api/dynamic/rcs-limits")
@serialized_controller_access
def prepare_dynamic_measurement(
    start_distance_m: float,
    end_distance_m: float,
    velocity_kmh: float,
    rcs_constant_state: int
):

    if controller is None:
        raise HTTPException(
            status_code=400,
            detail="Testsystem ist nicht verbunden"
        )

    try:
        return controller.prepare_dynamic_measurement(
            start_distance_m=start_distance_m,
            end_distance_m=end_distance_m,
            velocity_kmh=velocity_kmh,
            rcs_constant_state=rcs_constant_state
        )
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


# ==================================================
# API: DYNAMISCHE MESSUNG STARTEN
# ==================================================

@app.post("/api/dynamic/start")
@serialized_controller_access
def start_dynamic_measurement(
    start_distance_m: float,
    end_distance_m: float,
    velocity_kmh: float,
    rcs_constant_state: int,
    rcs_dbsm: float
):

    if controller is None:

        raise HTTPException(
            status_code=400,
            detail="Testsystem ist nicht verbunden"
        )


    try:

        result = (
            controller.start_dynamic_measurement(
                start_distance_m=start_distance_m,
                end_distance_m=end_distance_m,
                velocity_kmh=velocity_kmh,
                rcs_constant_state=rcs_constant_state,
                rcs_dbsm=rcs_dbsm
            )
        )


        log_file = (
            controller.start_logging()
        )


        controller.start_measurement_loop(
            interval_s=0.2
        )


        controller.trigger_dynamic_scenario()


        result[
            "log_file"
        ] = log_file


        return result


    except Exception as error:

        controller.stop_measurement_loop()

        controller.stop_logging(
            status="failed",
            reason="start_failed",
            error=str(error)
        )


        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


# ==================================================
# WEBSOCKET: LIVE-MESSUNG
# ==================================================

@app.websocket("/ws/static")
async def static_measurement_websocket(
    websocket: WebSocket
):

    await websocket.accept()


    active_controller = controller


    if active_controller is None:

        await websocket.send_json({

            "type":
                "error",

            "message":
                "Testsystem ist nicht verbunden"
        })


        await websocket.close()

        return


    last_sequence = None


    try:

        while True:

            if controller is not active_controller:

                await websocket.send_json({

                    "type":
                        "error",

                    "message":
                        "Testsystem wurde getrennt "
                        "oder gewechselt"
                })

                break


            try:

                measurement = (
                    active_controller
                    .get_latest_measurement()
                )


                if measurement is not None:

                    sequence = (
                        measurement.get(
                            "sequence"
                        )
                    )


                    if sequence != last_sequence:

                        await websocket.send_json({

                            "type":
                                "measurement",

                            "data":
                                measurement
                        })


                        last_sequence = (
                            sequence
                        )


                    if (
                        measurement.get(
                            "scenario_done"
                        )
                        and
                        not active_controller
                        .is_measurement_running()
                    ):

                        await websocket.send_json({

                            "type":
                                "complete"
                        })

                        break


            except WebSocketDisconnect:

                # Browser ist weg (z. B. WLAN-Aussetzer). Nichts mehr
                # senden, die Messung selbst läuft im Controller weiter.
                raise

            except Exception as error:

                try:

                    await websocket.send_json({

                        "type":
                            "error",

                        "message":
                            str(error)
                    })

                except Exception:

                    pass

                break


            await asyncio.sleep(
                0.05
            )


    except WebSocketDisconnect:

        pass


    finally:

        try:

            await websocket.close()

        except Exception:

            pass


# ==================================================
# API: MESSUNG STOPPEN
# ==================================================

@app.post("/api/measurement/stop")
@serialized_controller_access
def stop_measurement():

    if controller is None:

        raise HTTPException(
            status_code=400,
            detail="Testsystem ist nicht verbunden"
        )

    try:
        return controller.stop_active_measurement()
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


# ==================================================
# API: TRENNEN
# ==================================================

@app.post("/api/disconnect")
@serialized_controller_access
def disconnect_vehicle():

    global controller
    global selected_vehicle_id


    if controller is not None:

        try:

            controller.disconnect()


        finally:

            controller = None

            selected_vehicle_id = None


    return {
        "connected": False
    }
