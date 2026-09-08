import asyncio
import threading
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


app = FastAPI(
    title="Radar Testsystem"
)


# ==================================================
# AKTUELLER TESTCONTROLLER
# ==================================================

controller = None
selected_vehicle_id = None
controller_lock = threading.RLock()


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

            .dtc {
                margin-left: 20px;
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
        <!-- 2. Quick Check -->
        <!-- =================================== -->

        <section>

            <h2>
                2. Fahrzeug Quick Check
            </h2>


            <button
                id="quickCheckButton"
                onclick="runQuickCheck()"
                disabled
            >
                Quick Check starten
            </button>


            <div id="quickCheckResult">

                <p>
                    Fehlerspeicher:
                    <span
                        id="dtcStatus"
                        class="value"
                    >
                        -
                    </span>
                </p>

                <div id="dtcList"></div>

            </div>

        </section>


        <!-- =================================== -->
        <!-- 3. Precheck -->
        <!-- =================================== -->

        <section>

            <h2>
                3. RadEsT Precheck
            </h2>


            <button
                id="precheckButton"
                onclick="runPrecheck()"
                disabled
            >
                Precheck starten
            </button>


            <button
                id="skipPrecheckButton"
                onclick="skipPrecheck()"
                disabled
            >
                Precheck überspringen
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
        <!-- 4. Statische Messung -->
        <!-- =================================== -->

        <section>

            <h2>
                4. Statische Messung
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

        </section>


        <!-- =================================== -->
        <!-- 5. Dynamische Messung -->
        <!-- =================================== -->

        <section>

            <h2>
                5. Dynamische Messung
            </h2>


            <label for="dynamicStartDistanceInput">
                Startdistanz:
            </label>

            <input
                id="dynamicStartDistanceInput"
                type="number"
                value="30.0"
                step="0.1"
                min="0.1"
                disabled
            >

            <span>m</span>


            <label for="dynamicEndDistanceInput">
                Enddistanz:
            </label>

            <input
                id="dynamicEndDistanceInput"
                type="number"
                value="5.0"
                step="0.1"
                min="0.1"
                disabled
            >

            <span>m</span>


            <label for="dynamicVelocityInput">
                Geschwindigkeit:
            </label>

            <input
                id="dynamicVelocityInput"
                type="number"
                value="20"
                step="1"
                min="1"
                disabled
            >

            <span>km/h</span>


            <button
                id="dynamicButton"
                onclick="startDynamicMeasurement()"
                disabled
            >
                Scenario starten
            </button>


            <p>
                Scenario-Status:
                <span
                    id="scenarioStatus"
                    class="value"
                >
                    -
                </span>
            </p>

            <p>
                Aktuelle Phase:
                <span
                    id="scenarioPhase"
                    class="value"
                >
                    -
                </span>
            </p>


            <p>
                Gesamtdauer:
                <span
                    id="scenarioDuration"
                    class="value"
                >
                    -
                </span>
                s
            </p>


            <p>
                Fortschritt:
                <span
                    id="scenarioProgress"
                    class="value"
                >
                    -
                </span>
            </p>

        </section>


        <!-- =================================== -->
        <!-- 6. Live-Werte -->
        <!-- =================================== -->

        <section>

            <h2>
                6. Live-Werte
            </h2>


            <button
                id="stopButton"
                onclick="stopMeasurement()"
                disabled
            >
                Messung stoppen
            </button>


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
                RadEsT / Scenario-Soll:
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
                        "quickCheckButton"
                    ).disabled = false;


                    // Precheck erst nach Quick Check
                    document.getElementById(
                        "precheckButton"
                    ).disabled = true;


                    document.getElementById(
                        "skipPrecheckButton"
                    ).disabled = true;

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
            // QUICK CHECK
            // ====================================

            async function runQuickCheck() {

                clearError();


                const button =
                    document.getElementById(
                        "quickCheckButton"
                    );


                button.disabled = true;

                button.textContent =
                    "Quick Check läuft...";


                document.getElementById(
                    "dtcStatus"
                ).textContent =
                    "wird gelesen...";


                document.getElementById(
                    "dtcList"
                ).innerHTML = "";


                try {

                    const data =
                        await apiRequest(
                            "/api/quick-check",
                            {
                                method: "POST"
                            }
                        );


                    displayDtcs(
                        data.dtcs_before
                    );


                    button.textContent =
                        "Quick Check erneut starten";


                    button.disabled = false;


                    // Nach erfolgreichem Quick Check
                    // darf der RadEsT Precheck gestartet werden
                    document.getElementById(
                        "precheckButton"
                    ).disabled = false;


                    document.getElementById(
                        "skipPrecheckButton"
                    ).disabled = false;

                }

                catch (error) {

                    button.textContent =
                        "Quick Check starten";


                    button.disabled = false;


                    document.getElementById(
                        "dtcStatus"
                    ).textContent =
                        "Fehler";


                    showError(
                        error.message
                    );

                }
            }


            // ====================================
            // DTC-ERGEBNIS ANZEIGEN
            // ====================================

            function displayDtcs(
                ecuResults
            ) {

                const list =
                    document.getElementById(
                        "dtcList"
                    );


                list.innerHTML = "";


                if (
                    !ecuResults
                    ||
                    ecuResults.length === 0
                ) {

                    document.getElementById(
                        "dtcStatus"
                    ).textContent =
                        "Keine DTC-Konfiguration vorhanden";

                    return;
                }


                let totalDtcs = 0;


                for (
                    const ecu of ecuResults
                ) {

                    totalDtcs +=
                        ecu.dtcs.length;


                    const ecuTitle =
                        document.createElement(
                            "p"
                        );


                    ecuTitle.innerHTML =
                        "<strong>ECU:</strong> "
                        + ecu.ecu_name;


                    list.appendChild(
                        ecuTitle
                    );


                    const mask =
                        document.createElement(
                            "p"
                        );


                    mask.className =
                        "dtc";


                    mask.textContent =
                        "Status Availability Mask: "
                        + ecu.status_availability_mask;


                    list.appendChild(
                        mask
                    );


                    if (
                        ecu.dtcs.length === 0
                    ) {

                        const empty =
                            document.createElement(
                                "p"
                            );


                        empty.className =
                            "dtc";


                        empty.textContent =
                            "Keine DTCs vorhanden";


                        list.appendChild(
                            empty
                        );


                        continue;
                    }


                    for (
                        const dtc of ecu.dtcs
                    ) {

                        const item =
                            document.createElement(
                                "p"
                            );


                        item.className =
                            "dtc";


                        item.textContent =
                            "DTC: "
                            + dtc.code
                            + " | Status: "
                            + dtc.status;


                        list.appendChild(
                            item
                        );

                    }

                }


                if (totalDtcs === 0) {

                    document.getElementById(
                        "dtcStatus"
                    ).textContent =
                        "Keine Fehler gespeichert";

                }

                else {

                    document.getElementById(
                        "dtcStatus"
                    ).textContent =
                        totalDtcs
                        + " DTC(s) gefunden";

                }
            }


            // ====================================
            // RADEST PRECHECK
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


                    enableMeasurementControls();


                    document.getElementById(
                        "skipPrecheckButton"
                    ).disabled = true;


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


            async function skipPrecheck() {

                clearError();

                const button =
                    document.getElementById(
                        "skipPrecheckButton"
                    );

                button.disabled = true;

                try {

                    await apiRequest(
                        "/api/precheck/skip",
                        {
                            method: "POST"
                        }
                    );

                    document.getElementById(
                        "polarization"
                    ).textContent = "Übersprungen";

                    document.getElementById(
                        "frequency"
                    ).textContent = "Übersprungen";

                    document.getElementById(
                        "power"
                    ).textContent = "Übersprungen";

                    button.textContent =
                        "Precheck übersprungen";

                    enableMeasurementControls();

                }

                catch (error) {

                    button.disabled = false;

                    showError(
                        error.message
                    );

                }
            }


            function enableMeasurementControls() {

                for (const id of [
                    "distanceInput",
                    "staticButton",
                    "dynamicStartDistanceInput",
                    "dynamicEndDistanceInput",
                    "dynamicVelocityInput",
                    "dynamicButton"
                ]) {
                    document.getElementById(
                        id
                    ).disabled = false;
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
            // DYNAMISCHE MESSUNG STARTEN
            // ====================================

            async function startDynamicMeasurement() {

                clearError();


                const startDistance =
                    document.getElementById(
                        "dynamicStartDistanceInput"
                    ).value;


                const endDistance =
                    document.getElementById(
                        "dynamicEndDistanceInput"
                    ).value;


                const velocity =
                    document.getElementById(
                        "dynamicVelocityInput"
                    ).value;


                const button =
                    document.getElementById(
                        "dynamicButton"
                    );


                button.disabled = true;

                button.textContent =
                    "Scenario läuft...";


                document.getElementById(
                    "scenarioStatus"
                ).textContent =
                    "Wird vorbereitet...";


                try {

                    const url =
                        "/api/dynamic/start"
                        + `?start_distance_m=${startDistance}`
                        + `&end_distance_m=${endDistance}`
                        + `&velocity_kmh=${velocity}`;


                    const data =
                        await apiRequest(
                            url,
                            {
                                method: "POST"
                            }
                        );


                    document.getElementById(
                        "requestedDistance"
                    ).textContent =
                        Number(
                            data.start_distance
                        ).toFixed(2);


                    document.getElementById(
                        "radestDistance"
                    ).textContent =
                        Number(
                            data.start_distance
                        ).toFixed(2);


                    document.getElementById(
                        "scenarioDuration"
                    ).textContent =
                        Number(
                            data.total_duration_s
                        ).toFixed(2);


                    document.getElementById(
                        "scenarioProgress"
                    ).textContent =
                        "0.0 %";


                    document.getElementById(
                        "scenarioStatus"
                    ).textContent =
                        "Läuft";


                    document.getElementById(
                        "scenarioPhase"
                    ).textContent =
                        "Startdistanz halten";


                    if (data.log_file) {

                        document.getElementById(
                            "logFile"
                        ).textContent =
                            data.log_file;

                    }


                    startLiveMeasurement();

                }

                catch (error) {

                    button.disabled = false;

                    button.textContent =
                        "Scenario starten";


                    document.getElementById(
                        "scenarioStatus"
                    ).textContent =
                        "Fehler";


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


                        if (
                            message.type
                            === "complete"
                        ) {

                            document.getElementById(
                                "scenarioStatus"
                            ).textContent =
                                "Beendet";


                            document.getElementById(
                                "scenarioPhase"
                            ).textContent =
                                "Enddistanz gehalten";


                            document.getElementById(
                                "scenarioProgress"
                            ).textContent =
                                "100.0 %";


                            const dynamicButton =
                                document.getElementById(
                                    "dynamicButton"
                                );


                            dynamicButton.disabled = false;

                            dynamicButton.textContent =
                                "Scenario erneut starten";


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

                if (
                    data.test_type
                    === "dynamic"
                ) {

                    const phaseLabels = {
                        pre_hold: "Startdistanz halten",
                        moving: "Bewegung",
                        post_hold: "Enddistanz halten"
                    };

                    document.getElementById(
                        "scenarioDuration"
                    ).textContent =
                        Number(
                            data.dynamic_total_duration_s
                        ).toFixed(2);


                    document.getElementById(
                        "scenarioProgress"
                    ).textContent =
                        (
                            Number(
                                data.scenario_progress
                            )
                            * 100
                        ).toFixed(1)
                        + " %";


                    document.getElementById(
                        "scenarioStatus"
                    ).textContent =
                        data.scenario_done
                        ? "Beendet"
                        : "Läuft";


                    document.getElementById(
                        "scenarioPhase"
                    ).textContent =
                        phaseLabels[data.phase]
                        || data.phase
                        || "-";

                }

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
            // MESSUNG STOPPEN
            // ====================================

            async function stopMeasurement() {

                clearError();

                try {

                    const data = await apiRequest(
                        "/api/measurement/stop",
                        {
                            method: "POST"
                        }
                    );

                    stopLiveMeasurement();

                    document.getElementById(
                        "scenarioStatus"
                    ).textContent =
                        data.status === "aborted"
                        ? "Abgebrochen"
                        : "Beendet";

                    document.getElementById(
                        "dynamicButton"
                    ).disabled = false;

                    document.getElementById(
                        "dynamicButton"
                    ).textContent =
                        "Scenario erneut starten";

                }

                catch (error) {

                    showError(
                        error.message
                    );

                }
            }


            // ====================================
            // WEBSOCKET STOPPEN
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
                        "quickCheckButton"
                    ).disabled = true;


                    document.getElementById(
                        "quickCheckButton"
                    ).textContent =
                        "Quick Check starten";


                    document.getElementById(
                        "precheckButton"
                    ).disabled = true;


                    document.getElementById(
                        "precheckButton"
                    ).textContent =
                        "Precheck starten";


                    document.getElementById(
                        "skipPrecheckButton"
                    ).disabled = true;


                    document.getElementById(
                        "skipPrecheckButton"
                    ).textContent =
                        "Precheck überspringen";


                    document.getElementById(
                        "staticButton"
                    ).disabled = true;


                    document.getElementById(
                        "distanceInput"
                    ).disabled = true;


                    document.getElementById(
                        "dynamicButton"
                    ).disabled = true;


                    document.getElementById(
                        "dynamicButton"
                    ).textContent =
                        "Scenario starten";


                    document.getElementById(
                        "dynamicStartDistanceInput"
                    ).disabled = true;


                    document.getElementById(
                        "dynamicEndDistanceInput"
                    ).disabled = true;


                    document.getElementById(
                        "dynamicVelocityInput"
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
                    "dtcStatus"
                ).textContent = "-";


                document.getElementById(
                    "dtcList"
                ).innerHTML = "";


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


                document.getElementById(
                    "scenarioStatus"
                ).textContent = "-";


                document.getElementById(
                    "scenarioPhase"
                ).textContent = "-";


                document.getElementById(
                    "scenarioDuration"
                ).textContent = "-";


                document.getElementById(
                    "scenarioProgress"
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
# API: STATISCHE MESSUNG STARTEN
# ==================================================

@app.post("/api/static/start")
@serialized_controller_access
def start_static_measurement(
    distance_m: float
):

    if controller is None:

        raise HTTPException(
            status_code=400,
            detail="Testsystem ist nicht verbunden"
        )


    try:

        result = (
            controller.start_static_measurement(
                distance_m
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
# API: DYNAMISCHE MESSUNG STARTEN
# ==================================================

@app.post("/api/dynamic/start")
@serialized_controller_access
def start_dynamic_measurement(
    start_distance_m: float,
    end_distance_m: float,
    velocity_kmh: float
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
                velocity_kmh=velocity_kmh
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


            except Exception as error:

                await websocket.send_json({

                    "type":
                        "error",

                    "message":
                        str(error)
                })

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
