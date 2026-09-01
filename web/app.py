import asyncio

from fastapi import (
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse

from database.database import get_vehicles
from test_controller import TestController


app = FastAPI(
    title="Radar Testsystem"
)


# ==================================================
# AKTUELLER TESTCONTROLLER
# ==================================================

controller = None
selected_vehicle_id = None


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
            f"{name}"
            f"</option>"
        )


    html = """
    <!DOCTYPE html>

    <html lang="de">

    <head>

        <meta charset="UTF-8">

        <title>
            Radar Testsystem
        </title>

        <style>

            body {
                font-family: Arial, sans-serif;
                margin: 30px;
                max-width: 900px;
            }

            section {
                margin-top: 30px;
                padding-top: 10px;
                border-top: 1px solid #ccc;
            }

            button,
            select,
            input {
                font-size: 16px;
                padding: 6px;
                margin: 4px;
            }

            .value {
                font-weight: bold;
            }

            #status {
                margin-top: 15px;
                font-weight: bold;
            }

            #error {
                margin-top: 20px;
                font-weight: bold;
                color: red;
            }

        </style>

    </head>


    <body>

        <h1>
            Radar Testsystem
        </h1>


        <!-- =================================== -->
        <!-- 1. Fahrzeug -->
        <!-- =================================== -->

        <section>

            <h2>
                1. Fahrzeug auswählen
            </h2>


            <select id="vehicle">
                __VEHICLE_OPTIONS__
            </select>


            <button
                id="connectButton"
                onclick="connectSystem()"
            >
                Verbinden
            </button>


            <button
                id="disconnectButton"
                onclick="disconnectSystem()"
                disabled
            >
                Trennen
            </button>


            <p id="status">
                Nicht verbunden
            </p>


            <p id="signals"></p>


            <p>
                TestRun:
                <span
                    id="testRun"
                    class="value"
                >
                    -
                </span>
            </p>

        </section>


        <!-- =================================== -->
        <!-- 2. Precheck -->
        <!-- =================================== -->

        <section>

            <h2>
                2. RadEsT Precheck
            </h2>


            <button
                id="precheckButton"
                onclick="runPrecheck()"
                disabled
            >
                Precheck starten
            </button>


            <p>
                Polarisation:
                <span
                    id="polarization"
                    class="value"
                >
                    -
                </span>
            </p>


            <p>
                Frequenzbereich:
                <span
                    id="frequency"
                    class="value"
                >
                    -
                </span>
            </p>


            <p>
                Leistung:
                <span
                    id="power"
                    class="value"
                >
                    -
                </span>
            </p>

        </section>


        <!-- =================================== -->
        <!-- 3. Statische Messung -->
        <!-- =================================== -->

        <section>

            <h2>
                3. Statische Messung
            </h2>


            <label for="distanceInput">
                Distanz:
            </label>


            <input
                id="distanceInput"
                type="number"
                value="7.0"
                step="0.1"
                min="0"
                disabled
            >

            <span>m</span>


            <button
                id="staticButton"
                onclick="startStaticMeasurement()"
                disabled
            >
                Messung starten
            </button>


            <button
                id="stopButton"
                onclick="stopLiveMeasurement()"
                disabled
            >
                Live-Anzeige stoppen
            </button>


            <h3>
                Live-Werte
            </h3>


            <p>
                Angefordert:
                <span
                    id="requestedDistance"
                    class="value"
                >
                    -
                </span>
                m
            </p>


            <p>
                RadEsT:
                <span
                    id="radestDistance"
                    class="value"
                >
                    -
                </span>
                m
            </p>


            <p>
                Fahrzeug:
                <span
                    id="vehicleDistance"
                    class="value"
                >
                    -
                </span>
                m
            </p>


            <p>
                Differenz:
                <span
                    id="distanceError"
                    class="value"
                >
                    -
                </span>
                m
            </p>


            <p>
                Winkel:
                <span
                    id="angle"
                    class="value"
                >
                    -
                </span>
            </p>


            <p>
                Relativgeschwindigkeit:
                <span
                    id="relativeSpeed"
                    class="value"
                >
                    -
                </span>
            </p>


            <p>
                Relativbeschleunigung:
                <span
                    id="relativeAcceleration"
                    class="value"
                >
                    -
                </span>
            </p>


            <p>
                Logdatei:
                <span
                    id="logFile"
                    class="value"
                >
                    -
                </span>
            </p>

        </section>


        <p id="error"></p>


        <script>

            // ====================================
            // WEBSOCKET
            // ====================================

            let measurementSocket = null;


            // ====================================
            // API-HILFSFUNKTION
            // ====================================

            async function apiRequest(
                url,
                options = {}
            ) {

                const response = await fetch(
                    url,
                    options
                );


                const text =
                    await response.text();


                let data;


                try {

                    data = JSON.parse(
                        text
                    );

                }

                catch {

                    throw new Error(
                        text
                    );

                }


                if (!response.ok) {

                    throw new Error(
                        data.detail
                        || "Unbekannter Fehler"
                    );

                }


                return data;
            }


            // ====================================
            // VERBINDEN
            // ====================================

            async function connectSystem() {

                clearError();


                const vehicleId =
                    document.getElementById(
                        "vehicle"
                    ).value;


                const status =
                    document.getElementById(
                        "status"
                    );


                status.textContent =
                    "Verbindung wird hergestellt...";


                document.getElementById(
                    "connectButton"
                ).disabled = true;


                try {

                    const data =
                        await apiRequest(
                            `/api/connect/${vehicleId}`,
                            {
                                method: "POST"
                            }
                        );


                    status.textContent =
                        "Testsystem verbunden";


                    document.getElementById(
                        "signals"
                    ).textContent =
                        "Verfügbare Signale: "
                        + data.signals.join(", ");


                    if (
                        data.test_run
                        &&
                        data.test_run.run_id
                    ) {

                        document.getElementById(
                            "testRun"
                        ).textContent =
                            data.test_run.run_id;

                    }


                    document.getElementById(
                        "vehicle"
                    ).disabled = true;


                    document.getElementById(
                        "connectButton"
                    ).disabled = true;


                    document.getElementById(
                        "disconnectButton"
                    ).disabled = false;


                    document.getElementById(
                        "precheckButton"
                    ).disabled = false;

                }

                catch (error) {

                    status.textContent =
                        "Nicht verbunden";


                    document.getElementById(
                        "connectButton"
                    ).disabled = false;


                    showError(
                        error.message
                    );

                }
            }


            // ====================================
            // PRECHECK
            // ====================================

            async function runPrecheck() {

                clearError();


                const button =
                    document.getElementById(
                        "precheckButton"
                    );


                button.disabled = true;

                button.textContent =
                    "Precheck läuft...";


                try {

                    const data =
                        await apiRequest(
                            "/api/precheck",
                            {
                                method: "POST"
                            }
                        );


                    document.getElementById(
                        "polarization"
                    ).textContent =
                        data.polarization;


                    if (
                        Array.isArray(
                            data.frequency_range
                        )
                    ) {

                        document.getElementById(
                            "frequency"
                        ).textContent =
                            data.frequency_range.join(
                                " - "
                            )
                            + " GHz";

                    }

                    else {

                        document.getElementById(
                            "frequency"
                        ).textContent =
                            data.frequency_range;

                    }


                    document.getElementById(
                        "power"
                    ).textContent =
                        data.power;


                    document.getElementById(
                        "distanceInput"
                    ).disabled = false;


                    document.getElementById(
                        "staticButton"
                    ).disabled = false;


                    button.textContent =
                        "Precheck erneut starten";


                    button.disabled = false;

                }

                catch (error) {

                    button.textContent =
                        "Precheck starten";


                    button.disabled = false;


                    showError(
                        error.message
                    );

                }
            }


            // ====================================
            // STATISCHE MESSUNG STARTEN
            // ====================================

            async function startStaticMeasurement() {

                clearError();


                const distance =
                    document.getElementById(
                        "distanceInput"
                    ).value;


                try {

                    const data =
                        await apiRequest(
                            `/api/static/start?distance_m=${distance}`,
                            {
                                method: "POST"
                            }
                        );


                    document.getElementById(
                        "requestedDistance"
                    ).textContent =
                        Number(
                            data.requested_distance
                        ).toFixed(2);


                    document.getElementById(
                        "radestDistance"
                    ).textContent =
                        Number(
                            data.radest_distance
                        ).toFixed(2);


                    if (data.log_file) {

                        document.getElementById(
                            "logFile"
                        ).textContent =
                            data.log_file;

                    }


                    startLiveMeasurement();

                }

                catch (error) {

                    showError(
                        error.message
                    );

                }
            }


            // ====================================
            // WEBSOCKET STARTEN
            // ====================================

            function startLiveMeasurement() {

                stopLiveMeasurement();


                const protocol =
                    window.location.protocol === "https:"
                    ? "wss:"
                    : "ws:";


                const socketUrl =
                    `${protocol}//${window.location.host}/ws/static`;


                measurementSocket =
                    new WebSocket(
                        socketUrl
                    );


                measurementSocket.onopen =
                    function() {

                        console.log(
                            "WebSocket verbunden"
                        );


                        document.getElementById(
                            "stopButton"
                        ).disabled = false;

                    };


                measurementSocket.onmessage =
                    function(event) {

                        const message =
                            JSON.parse(
                                event.data
                            );


                        if (
                            message.type
                            === "measurement"
                        ) {

                            updateMeasurement(
                                message.data
                            );

                        }


                        if (
                            message.type
                            === "error"
                        ) {

                            showError(
                                message.message
                            );


                            stopLiveMeasurement();

                        }
                    };


                measurementSocket.onerror =
                    function() {

                        showError(
                            "WebSocket-Verbindung fehlgeschlagen"
                        );

                    };


                measurementSocket.onclose =
                    function() {

                        console.log(
                            "WebSocket getrennt"
                        );


                        measurementSocket = null;


                        document.getElementById(
                            "stopButton"
                        ).disabled = true;

                    };
            }


            // ====================================
            // LIVE-MESSWERT ANZEIGEN
            // ====================================

            function updateMeasurement(
                data
            ) {

                document.getElementById(
                    "requestedDistance"
                ).textContent =
                    Number(
                        data.requested_distance
                    ).toFixed(2);


                document.getElementById(
                    "radestDistance"
                ).textContent =
                    Number(
                        data.radest_distance
                    ).toFixed(2);


                const vehicle =
                    data.vehicle;


                // -------------------------------
                // Abstand
                // -------------------------------

                if (vehicle.distance) {

                    document.getElementById(
                        "vehicleDistance"
                    ).textContent =
                        Number(
                            vehicle.distance.value
                        ).toFixed(2);

                }

                else {

                    document.getElementById(
                        "vehicleDistance"
                    ).textContent = "-";

                }


                // -------------------------------
                // Differenz
                // -------------------------------

                if (
                    data.distance_error !== null
                    &&
                    data.distance_error !== undefined
                ) {

                    document.getElementById(
                        "distanceError"
                    ).textContent =
                        Number(
                            data.distance_error
                        ).toFixed(2);

                }

                else {

                    document.getElementById(
                        "distanceError"
                    ).textContent = "-";

                }


                // -------------------------------
                // Winkel
                // -------------------------------

                if (vehicle.angle) {

                    document.getElementById(
                        "angle"
                    ).textContent =
                        Number(
                            vehicle.angle.value
                        ).toFixed(2)
                        + " "
                        + vehicle.angle.unit;

                }

                else {

                    document.getElementById(
                        "angle"
                    ).textContent = "-";

                }


                // -------------------------------
                // Relativgeschwindigkeit
                // -------------------------------

                if (
                    vehicle.relative_speed
                ) {

                    document.getElementById(
                        "relativeSpeed"
                    ).textContent =
                        Number(
                            vehicle.relative_speed.value
                        ).toFixed(2)
                        + " "
                        + vehicle.relative_speed.unit;

                }

                else {

                    document.getElementById(
                        "relativeSpeed"
                    ).textContent = "-";

                }


                // -------------------------------
                // Relativbeschleunigung
                // -------------------------------

                if (
                    vehicle.relative_acceleration
                ) {

                    document.getElementById(
                        "relativeAcceleration"
                    ).textContent =
                        Number(
                            vehicle.relative_acceleration.value
                        ).toFixed(2)
                        + " "
                        + vehicle.relative_acceleration.unit;

                }

                else {

                    document.getElementById(
                        "relativeAcceleration"
                    ).textContent = "-";

                }
            }


            // ====================================
            // WEBSOCKET STOPPEN
            //
            // Wichtig:
            // Nur Live-Anzeige wird gestoppt.
            // Der Hintergrund-Messloop läuft weiter.
            // ====================================

            function stopLiveMeasurement() {

                if (
                    measurementSocket !== null
                ) {

                    measurementSocket.close();

                    measurementSocket = null;

                }


                document.getElementById(
                    "stopButton"
                ).disabled = true;
            }


            // ====================================
            // TESTSYSTEM TRENNEN
            // ====================================

            async function disconnectSystem() {

                clearError();


                stopLiveMeasurement();


                try {

                    await apiRequest(
                        "/api/disconnect",
                        {
                            method: "POST"
                        }
                    );


                    document.getElementById(
                        "status"
                    ).textContent =
                        "Nicht verbunden";


                    document.getElementById(
                        "signals"
                    ).textContent = "";


                    document.getElementById(
                        "vehicle"
                    ).disabled = false;


                    document.getElementById(
                        "connectButton"
                    ).disabled = false;


                    document.getElementById(
                        "disconnectButton"
                    ).disabled = true;


                    document.getElementById(
                        "precheckButton"
                    ).disabled = true;


                    document.getElementById(
                        "precheckButton"
                    ).textContent =
                        "Precheck starten";


                    document.getElementById(
                        "staticButton"
                    ).disabled = true;


                    document.getElementById(
                        "distanceInput"
                    ).disabled = true;


                    resetValues();

                }

                catch (error) {

                    showError(
                        error.message
                    );

                }
            }


            // ====================================
            // ANZEIGE ZURÜCKSETZEN
            // ====================================

            function resetValues() {

                document.getElementById(
                    "testRun"
                ).textContent = "-";


                document.getElementById(
                    "polarization"
                ).textContent = "-";


                document.getElementById(
                    "frequency"
                ).textContent = "-";


                document.getElementById(
                    "power"
                ).textContent = "-";


                document.getElementById(
                    "requestedDistance"
                ).textContent = "-";


                document.getElementById(
                    "radestDistance"
                ).textContent = "-";


                document.getElementById(
                    "vehicleDistance"
                ).textContent = "-";


                document.getElementById(
                    "distanceError"
                ).textContent = "-";


                document.getElementById(
                    "angle"
                ).textContent = "-";


                document.getElementById(
                    "relativeSpeed"
                ).textContent = "-";


                document.getElementById(
                    "relativeAcceleration"
                ).textContent = "-";


                document.getElementById(
                    "logFile"
                ).textContent = "-";
            }


            // ====================================
            // FEHLER
            // ====================================

            function showError(
                message
            ) {

                document.getElementById(
                    "error"
                ).textContent =
                    "Fehler: "
                    + message;
            }


            function clearError() {

                document.getElementById(
                    "error"
                ).textContent = "";
            }

        </script>

    </body>

    </html>
    """


    html = html.replace(
        "__VEHICLE_OPTIONS__",
        vehicle_options
    )


    return HTMLResponse(
        content=html
    )


# ==================================================
# API: VERBINDEN
# ==================================================

@app.post("/api/connect/{vehicle_id}")
def connect_vehicle(
    vehicle_id: int
):

    global controller
    global selected_vehicle_id


    new_controller = None


    try:

        # --------------------------------------------------
        # Falls bereits ein Controller vorhanden ist:
        # sauber trennen.
        # --------------------------------------------------

        if controller is not None:

            controller.disconnect()

            controller = None

            selected_vehicle_id = None


        # --------------------------------------------------
        # Controller für ausgewähltes Fahrzeug
        # --------------------------------------------------

        new_controller = TestController(
            vehicle_id=vehicle_id
        )


        # --------------------------------------------------
        # Fahrzeug + RadEsT verbinden
        # --------------------------------------------------

        new_controller.connect()


        # --------------------------------------------------
        # Neuen TestRun starten
        # --------------------------------------------------

        test_run = (
            new_controller.start_test_run()
        )


        # --------------------------------------------------
        # Erst nach erfolgreichem Connect global setzen
        # --------------------------------------------------

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

        # --------------------------------------------------
        # Teilweise aufgebaute Verbindung aufräumen
        # --------------------------------------------------

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
# API: PRECHECK
# ==================================================

@app.post("/api/precheck")
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


# ==================================================
# API: STATISCHE MESSUNG STARTEN
# ==================================================

@app.post("/api/static/start")
def start_static_measurement(
    distance_m: float
):

    if controller is None:

        raise HTTPException(
            status_code=400,
            detail="Testsystem ist nicht verbunden"
        )


    try:

        # --------------------------------------------------
        # RadEsT-Distanz einstellen
        # --------------------------------------------------

        result = (
            controller.start_static_measurement(
                distance_m
            )
        )


        # --------------------------------------------------
        # CSV-Logging starten
        #
        # Der Logger registriert gleichzeitig den
        # statischen Test im aktuellen TestRun.
        # --------------------------------------------------

        log_file = (
            controller.start_logging()
        )


        # --------------------------------------------------
        # Hintergrund-Messloop starten
        # --------------------------------------------------

        controller.start_measurement_loop(
            interval_s=0.2
        )


        # --------------------------------------------------
        # Logdatei zusätzlich an Browser zurückgeben
        # --------------------------------------------------

        result[
            "log_file"
        ] = log_file


        return result


    except Exception as error:

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


    # --------------------------------------------------
    # Controller merken, zu dem dieser WebSocket gehört
    # --------------------------------------------------

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

            # ----------------------------------------------
            # Wurde Controller inzwischen getrennt
            # oder durch einen anderen ersetzt?
            # ----------------------------------------------

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

                # ------------------------------------------
                # KEINE CAN-/UDS-Abfrage hier.
                #
                # Der TestController erzeugt die Messwerte
                # unabhängig im Hintergrundthread.
                # ------------------------------------------

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


                    # --------------------------------------
                    # Nur neue Messpunkte übertragen
                    # --------------------------------------

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


            except Exception as error:

                await websocket.send_json({

                    "type":
                        "error",

                    "message":
                        str(error)
                })

                break


            # ----------------------------------------------
            # Nur prüfen, ob ein neuer Messpunkt vorliegt.
            #
            # Messloop läuft separat mit ca. 200 ms.
            # ----------------------------------------------

            await asyncio.sleep(
                0.05
            )


    except WebSocketDisconnect:

        # --------------------------------------------------
        # Browser/WebSocket weg:
        #
        # Hintergrundmessung läuft bewusst weiter.
        # --------------------------------------------------

        pass


    finally:

        try:

            await websocket.close()

        except Exception:

            pass


# ==================================================
# API: TRENNEN
# ==================================================

@app.post("/api/disconnect")
def disconnect_vehicle():

    global controller
    global selected_vehicle_id


    if controller is not None:

        try:

            # TestController erledigt intern:
            #
            # - Measurement Thread stoppen
            # - CSV schließen
            # - aktiven statischen Test abschließen
            # - TestRun abschließen
            # - Fahrzeug trennen
            # - RadEsT trennen

            controller.disconnect()


        finally:

            controller = None

            selected_vehicle_id = None


    return {
        "connected": False
    }