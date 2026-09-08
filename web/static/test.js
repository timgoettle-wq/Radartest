

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


                document.getElementById(
                    "identificationStatus"
                ).textContent =
                    "wird gelesen...";


                document.getElementById(
                    "identificationList"
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
                        data.dtcs_before,
                        data.dtc_error
                    );


                    displayIdentification(
                        data.identification,
                        data.identification_summary
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


                    document.getElementById(
                        "identificationStatus"
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
                ecuResults,
                errorMessage
            ) {

                const list =
                    document.getElementById(
                        "dtcList"
                    );


                list.innerHTML = "";


                if (errorMessage) {

                    document.getElementById(
                        "dtcStatus"
                    ).textContent =
                        "Lesefehler: "
                        + errorMessage;

                    return;
                }


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
            // STEUERGERÄTE-IDENTIFIKATION ANZEIGEN
            // ====================================

            function displayIdentification(
                results,
                summary
            ) {

                const container =
                    document.getElementById(
                        "identificationList"
                    );


                container.innerHTML = "";


                if (!results || results.length === 0) {

                    document.getElementById(
                        "identificationStatus"
                    ).textContent =
                        "Keine Parameter konfiguriert";

                    return;
                }


                const statusLabels = {
                    match: "Referenz erkannt",
                    mismatch: "Nicht in Referenzliste",
                    unknown: "Keine Referenz hinterlegt",
                    read_error: "Lesefehler"
                };


                const table = document.createElement(
                    "table"
                );

                table.className =
                    "identification-table";


                const header = table.insertRow();

                for (const title of [
                    "Merkmal",
                    "Steuergerät",
                    "Istwert",
                    "Rohantwort",
                    "Referenz",
                    "Bewertung"
                ]) {

                    const cell = document.createElement(
                        "th"
                    );

                    cell.textContent = title;
                    header.appendChild(cell);
                }


                for (const item of results) {

                    const row = table.insertRow();

                    const references = (
                        item.accepted_values || []
                    ).map(
                        entry => entry.value
                    ).join(", ");

                    const values = [
                        item.label
                            + " (" + item.did + ")",
                        item.ecu_name,
                        item.read_status === "ok"
                            ? String(item.value)
                            : item.error_message,
                        item.raw_response || "-",
                        references || "-",
                        statusLabels[item.status]
                            || item.status
                    ];

                    for (const value of values) {

                        const cell = row.insertCell();
                        cell.textContent = value || "-";
                    }
                }


                container.appendChild(table);


                document.getElementById(
                    "identificationStatus"
                ).textContent =
                    summary.match + " erkannt, "
                    + summary.mismatch + " unbekannt, "
                    + summary.unknown + " ohne Referenz, "
                    + summary.read_error + " Lesefehler";
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
                    "identificationStatus"
                ).textContent = "-";


                document.getElementById(
                    "identificationList"
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

        
