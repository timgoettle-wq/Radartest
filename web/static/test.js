"use strict";

let measurementSocket = null;
let socketClosingIntentionally = false;

const uiState = {
    connected: false,
    vehicleId: null,
    vehicleName: "",
    runId: null,
    signals: [],
    quickCheckComplete: false,
    quickCheckResult: null,
    precheckComplete: false,
    precheckSkipped: false,
    currentStep: 1,
    measurementComplete: false,
    currentMeasurement: null,
    lastMeasurement: null,
    samples: [],
    logFile: null,
    measurementStartedAt: null,
    lastConfiguration: null,
    vehicleOverview: null
};

const $ = id => document.getElementById(id);
const screens = {
    1: "screenVehicle",
    2: "screenQuickCheck",
    3: "screenPrecheck",
    4: "screenTests",
    5: "screenResult"
};

async function apiRequest(url, options = {}) {
    const response = await fetch(url, options);
    const text = await response.text();
    let data;
    try {
        data = JSON.parse(text);
    } catch {
        throw new Error(text || "Ungültige Serverantwort");
    }
    if (!response.ok) {
        throw new Error(data.detail || "Unbekannter Fehler");
    }
    return data;
}

function showError(message) {
    $("error").textContent = "Fehler: " + message;
}

function clearError() {
    $("error").textContent = "";
}

function showMessage(message) {
    $("appMessage").textContent = message || "";
}

function setBusy(button, busy, busyText, normalText) {
    button.disabled = busy;
    button.textContent = busy ? busyText : normalText;
}

function setIndicator(id, state) {
    const element = $(id);
    element.classList.remove("ok", "warning", "error");
    if (state) element.classList.add(state);
}

function updateHeader() {
    $("headerVehicle").textContent = uiState.vehicleName || "Kein Fahrzeug";
    $("headerTestRun").textContent = uiState.runId ? "TestRun " + uiState.runId : "Kein TestRun";
    $("headerConnection").classList.toggle("connected", uiState.connected);
    $("headerConnection").lastChild.textContent = uiState.connected ? "Verbunden" : "Nicht verbunden";
    $("disconnectButton").disabled = !uiState.connected;
    const status = uiState.connected ? "ok" : null;
    setIndicator("radestIndicator", status);
    setIndicator("vehicleIndicator", status);
    setIndicator("diagnosisIndicator", status);
}

function maxAvailableStep() {
    if (uiState.measurementComplete) return 5;
    if (uiState.precheckComplete) return 4;
    if (uiState.quickCheckComplete) return 3;
    if (uiState.connected) return 2;
    return 1;
}

function updateStepper() {
    const completed = {
        1: uiState.connected,
        2: uiState.quickCheckComplete,
        3: uiState.precheckComplete,
        4: uiState.measurementComplete,
        5: false
    };
    const available = maxAvailableStep();
    document.querySelectorAll(".stepper li").forEach(item => {
        const step = Number(item.dataset.step);
        const button = item.querySelector("button");
        item.classList.toggle("active", step === uiState.currentStep);
        item.classList.toggle("complete", Boolean(completed[step]));
        item.classList.toggle("locked", step > available);
        button.disabled = step > available || Boolean(uiState.currentMeasurement);
        item.querySelector("span").textContent = completed[step] && step !== uiState.currentStep ? "✓" : step;
    });
}

function showStep(step) {
    if (step > maxAvailableStep() || uiState.currentMeasurement) return;
    uiState.currentStep = step;
    document.querySelectorAll(".workflow-screen").forEach(screen => screen.hidden = true);
    $(screens[step]).hidden = false;
    updateStepper();
    clearError();
}

function showMeasurementScreen() {
    uiState.currentStep = 4;
    document.querySelectorAll(".workflow-screen").forEach(screen => screen.hidden = true);
    $("screenMeasurement").hidden = false;
    updateStepper();
}

function selectedVehicleName() {
    const option = $("vehicle").selectedOptions[0];
    return option ? option.textContent.trim() : "";
}

async function connectSystem() {
    clearError();
    showMessage("");
    const vehicleId = $("vehicle").value;
    if (!vehicleId) {
        showError("Bitte zuerst ein Fahrzeug auswählen.");
        return;
    }
    setBusy($("connectButton"), true, "Verbindung wird hergestellt …", "Prüfung starten");
    try {
        const data = await apiRequest("/api/connect/" + vehicleId, {method: "POST"});
        uiState.connected = true;
        uiState.vehicleId = Number(vehicleId);
        uiState.vehicleName = selectedVehicleName();
        uiState.runId = data.test_run?.run_id || null;
        uiState.signals = data.signals || [];
        $("vehicle").disabled = true;
        $("connectionResult").hidden = false;
        $("checkRadest").className = "check-row ok";
        $("checkDiagnosis").className = "check-row ok";
        const distanceAvailable = uiState.signals.includes("distance");
        $("checkSignals").className = "check-row " + (distanceAvailable ? "ok" : "warning");
        $("signals").textContent = distanceAvailable
            ? "Messsignale verfügbar: " + uiState.signals.join(", ")
            : "Kein standardisiertes distance-Signal verfügbar";
        $("toQuickCheckButton").disabled = false;
        updateHeader();
        updateStepper();
    } catch (error) {
        setBusy($("connectButton"), false, "", "Prüfung starten");
        showError(error.message);
    }
}

function hexId(value) {
    const number = Number(value);
    return value === null || value === undefined || value === "" || !Number.isFinite(number)
        ? "–"
        : "0x" + number.toString(16).toUpperCase();
}

function formatDateTime(value) {
    const date = value ? new Date(value) : null;
    return date && !Number.isNaN(date.getTime())
        ? date.toLocaleString("de-DE", {dateStyle: "medium", timeStyle: "short"})
        : "–";
}

function profileFact(label, value) {
    const element = document.createElement("div");
    element.append(createTextElement("span", label), createTextElement("strong", String(value)));
    return element;
}

function renderVehicleProfile(data) {
    const vehicle = data.vehicle || {};
    $("profileName").textContent = [vehicle.manufacturer, vehicle.model, vehicle.generation]
        .filter(Boolean).join(" ") || selectedVehicleName();
    const years = vehicle.year_from
        ? "Baujahr " + vehicle.year_from + (vehicle.year_to ? "–" + vehicle.year_to : " bis heute")
        : "";
    $("profileMeta").textContent = [years, vehicle.description].filter(Boolean).join(" · ") || "Keine weiteren Angaben";

    const ecus = $("profileEcus");
    ecus.replaceChildren();
    if (!data.ecus?.length) {
        ecus.append(createTextElement("p", "Kein Steuergerät in der Datenpflege hinterlegt.", "profile-empty"));
    }
    for (const ecu of data.ecus || []) {
        const card = document.createElement("div");
        card.className = "profile-ecu";
        card.append(
            createTextElement("strong", ecu.name || "Steuergerät"),
            createTextElement("span", [ecu.interface, ecu.channel].filter(Boolean).join(" · ")
                + " · " + hexId(ecu.request_id) + " → " + hexId(ecu.response_id)),
            createTextElement("span", ecu.identification_count + " Identifikationsmerkmale · "
                + ecu.parameter_count + " Messparameter")
        );
        ecus.append(card);
    }

    const history = $("profileHistory");
    history.replaceChildren();
    const lastRun = data.last_run;
    if (!lastRun) {
        history.append(createTextElement("p", "Mit diesem Fahrzeug wurde noch kein TestRun durchgeführt.", "profile-empty"));
        return;
    }
    history.append(
        profileFact("TestRuns gesamt", data.run_count),
        profileFact("Letzter TestRun", formatDateTime(lastRun.start_time)),
        profileFact("Messungen darin", lastRun.test_count)
    );
    const link = document.createElement("a");
    link.href = "/results?run=" + encodeURIComponent(lastRun.run_id);
    link.textContent = "Letzten TestRun im Archiv öffnen";
    history.append(link);
}

function renderPrecheckHistory(lastPrecheck) {
    const formatters = {polarization: formatPolarization, frequency_range: formatFrequency, power: formatPower};
    document.querySelectorAll("[data-last-value]").forEach(element => {
        const key = element.dataset.lastValue;
        element.textContent = lastPrecheck ? "Zuletzt: " + formatters[key](lastPrecheck[key]) : "";
    });
    $("precheckLastInfo").textContent = lastPrecheck
        ? "Vergleichswerte aus dem letzten Precheck dieses Fahrzeugs vom " + formatDateTime(lastPrecheck.start_time) + "."
        : "Für dieses Fahrzeug gibt es noch keinen gespeicherten Precheck zum Vergleich.";
}

async function loadVehicleProfile() {
    const vehicleId = $("vehicle").value;
    if (!vehicleId) return;
    try {
        const data = await apiRequest("/api/vehicles/" + encodeURIComponent(vehicleId) + "/overview");
        if ($("vehicle").value !== vehicleId) return;
        uiState.vehicleOverview = data;
        renderVehicleProfile(data);
        renderPrecheckHistory(data.last_precheck);
    } catch (error) {
        $("profileHistory").replaceChildren(
            createTextElement("p", "Fahrzeugdaten konnten nicht geladen werden: " + error.message, "profile-empty")
        );
    }
}

function createTextElement(tag, text, className = "") {
    const element = document.createElement(tag);
    element.textContent = text;
    if (className) element.className = className;
    return element;
}

function displayDtcs(ecuResults, errorMessage) {
    const list = $("dtcList");
    list.replaceChildren();
    if (errorMessage) {
        $("dtcStatus").textContent = "Lesefehler";
        $("dtcStatus").className = "status-pill error";
        list.append(createTextElement("p", errorMessage, "inline-warning"));
        return {warning: true, count: 0};
    }
    if (!ecuResults?.length) {
        $("dtcStatus").textContent = "Nicht konfiguriert";
        $("dtcStatus").className = "status-pill neutral";
        list.append(createTextElement("p", "Keine DTC-Konfiguration vorhanden.", "empty-inline"));
        return {warning: false, count: 0};
    }
    let total = 0;
    for (const ecu of ecuResults) {
        const group = document.createElement("div");
        group.className = "diagnostic-group";
        group.append(createTextElement("strong", ecu.ecu_name));
        group.append(createTextElement("span", "Statusmaske: " + ecu.status_availability_mask));
        if (!ecu.dtcs.length) {
            group.append(createTextElement("p", "Keine DTCs vorhanden."));
        } else {
            for (const dtc of ecu.dtcs) {
                group.append(createTextElement("p", dtc.code + " · Status " + dtc.status, "dtc-entry"));
            }
        }
        total += ecu.dtcs.length;
        list.append(group);
    }
    $("dtcStatus").textContent = total ? total + " DTC(s)" : "Keine Fehler";
    $("dtcStatus").className = "status-pill " + (total ? "warning" : "success");
    return {warning: total > 0, count: total};
}

function displayIdentification(results, summary = {}) {
    const container = $("identificationList");
    container.replaceChildren();
    if (!results?.length) {
        $("identificationStatus").textContent = "Nicht konfiguriert";
        $("identificationStatus").className = "status-pill neutral";
        container.append(createTextElement("p", "Keine Identifikationsparameter konfiguriert.", "empty-inline"));
        return {warning: false};
    }
    const statusLabels = {
        match: "Referenz erkannt",
        mismatch: "Nicht in Referenzliste",
        unknown: "Keine Referenz hinterlegt",
        read_error: "Lesefehler"
    };
    const table = document.createElement("table");
    table.className = "identification-table";
    const header = table.insertRow();
    ["Merkmal", "Steuergerät", "Istwert", "Referenz", "Bewertung"].forEach(title => {
        header.append(createTextElement("th", title));
    });
    for (const item of results) {
        const row = table.insertRow();
        const references = (item.accepted_values || []).map(entry => entry.value).join(", ");
        const values = [
            item.label + " (" + item.did + ")",
            item.ecu_name,
            item.read_status === "ok" ? String(item.value) : item.error_message,
            references || "–",
            statusLabels[item.status] || item.status
        ];
        values.forEach(value => row.insertCell().textContent = value || "–");
        row.className = item.status === "match" ? "row-success" : item.status === "unknown" ? "" : "row-warning";
    }
    container.append(table);
    const warnings = Number(summary.mismatch || 0) + Number(summary.read_error || 0);
    $("identificationStatus").textContent = warnings ? warnings + " Auffälligkeit(en)" : (summary.match || 0) + " erkannt";
    $("identificationStatus").className = "status-pill " + (warnings ? "warning" : "success");
    return {warning: warnings > 0};
}

function renderQuickCheck(data) {
    const dtc = displayDtcs(data.dtcs_before, data.dtc_error);
    const identification = displayIdentification(data.identification, data.identification_summary);
    const warning = dtc.warning || identification.warning;
    $("quickCheckSummary").className = "result-banner " + (warning ? "warning" : "success");
    $("quickCheckSummary").textContent = warning
        ? "Quick Check abgeschlossen – Auffälligkeiten prüfen, bewusstes Fortfahren ist möglich."
        : "Quick Check erfolgreich abgeschlossen.";
    $("quickCheckResult").hidden = false;
}

async function runQuickCheck() {
    clearError();
    setBusy($("quickCheckButton"), true, "Quick Check läuft …", "Quick Check starten");
    try {
        const data = await apiRequest("/api/quick-check", {method: "POST"});
        uiState.quickCheckResult = data;
        uiState.quickCheckComplete = true;
        renderQuickCheck(data);
        $("quickCheckButton").textContent = "Quick Check erneut starten";
        $("quickCheckButton").disabled = false;
        $("toPrecheckButton").disabled = false;
        updateStepper();
    } catch (error) {
        setBusy($("quickCheckButton"), false, "", "Quick Check starten");
        showError(error.message);
    }
}

function formatFrequency(value) {
    if (value === null || value === undefined || value === "") return "–";
    const formatted = Array.isArray(value) ? value.join(" – ") : String(value);
    return /\\bGHz\\b/i.test(formatted) ? formatted : formatted + " GHz";
}

function formatPower(value) {
    if (value === null || value === undefined || value === "") return "–";
    const formatted = String(value);
    return /\\bdBm\\b/i.test(formatted) ? formatted : formatted + " dBm";
}

function formatPolarization(value) {
    if (value === null || value === undefined || value === "") return "–";

    const raw = Array.isArray(value) ? value.join(", ") : String(value).trim();
    const code = (Array.isArray(value) ? String(value[0]) : raw.split(",")[0]).trim().toUpperCase();
    const labels = {
        "5": "Horizontal",
        "8": "Vertikal",
        "7": "+45°",
        "6": "−45°",
        "H": "Horizontal",
        "V": "Vertikal",
        "HORIZONTAL": "Horizontal",
        "VERTICAL": "Vertikal",
        "P45": "+45°",
        "M45": "−45°"
    };

    return labels[code] || raw;
}

function renderPrecheck(data) {
    const skipped = Boolean(data.skipped);
    $("precheckResult").hidden = false;
    $("precheckSummary").className = "result-banner " + (skipped ? "warning" : "success");
    $("precheckSummary").textContent = skipped
        ? "Precheck bewusst übersprungen und im TestRun dokumentiert."
        : "Precheck abgeschlossen – RadEsT-Werte wurden erfasst.";
    $("precheckConnection").textContent = skipped ? "Nicht geprüft" : "✓ Verbunden";
    $("frequency").textContent = skipped ? "Übersprungen" : formatFrequency(data.frequency_range);
    $("polarization").textContent = skipped ? "Übersprungen" : formatPolarization(data.polarization);
    $("power").textContent = skipped ? "Übersprungen" : formatPower(data.power);
}

function updatePrecheckProgress(activePhase = null, completedPhases = [], errorPhase = null) {
    const progress = $("precheckProgress");
    progress.hidden = false;
    progress.querySelectorAll("[data-precheck-phase]").forEach((item, index) => {
        const phase = item.dataset.precheckPhase;
        const completed = completedPhases.includes(phase);
        item.className = completed ? "complete" : phase === activePhase ? "active" : phase === errorPhase ? "error" : "";
        item.querySelector("span").textContent = completed ? "✓" : String(index + 1);
    });
}

async function runPrecheck() {
    clearError();
    setBusy($("precheckButton"), true, "Precheck läuft …", "Precheck starten");
    $("skipPrecheckButton").disabled = true;
    $("precheckResult").hidden = true;
    let activePhase = "polarization";
    const completedPhases = [];
    try {
        await apiRequest("/api/precheck/start", {method: "POST"});
        updatePrecheckProgress(activePhase, completedPhases);
        await apiRequest("/api/precheck/polarization", {method: "POST"});
        completedPhases.push("polarization");
        activePhase = "frequency";
        updatePrecheckProgress(activePhase, completedPhases);
        await apiRequest("/api/precheck/frequency", {method: "POST"});
        completedPhases.push("frequency");
        activePhase = "power";
        updatePrecheckProgress(activePhase, completedPhases);
        const data = await apiRequest("/api/precheck/power", {method: "POST"});
        completedPhases.push("power");
        activePhase = null;
        updatePrecheckProgress(activePhase, completedPhases);
        uiState.precheckComplete = true;
        uiState.precheckSkipped = false;
        renderPrecheck(data);
        $("precheckButton").textContent = "Precheck erneut starten";
        $("precheckButton").disabled = false;
        $("skipPrecheckButton").disabled = true;
        $("toTestsButton").disabled = false;
        updateStepper();
    } catch (error) {
        updatePrecheckProgress(null, completedPhases, activePhase);
        setBusy($("precheckButton"), false, "", "Precheck starten");
        $("skipPrecheckButton").disabled = false;
        showError(error.message);
    }
}

async function skipPrecheck() {
    clearError();
    setBusy($("skipPrecheckButton"), true, "Wird dokumentiert …", "Precheck überspringen");
    try {
        const data = await apiRequest("/api/precheck/skip", {method: "POST"});
        uiState.precheckComplete = true;
        uiState.precheckSkipped = true;
        renderPrecheck(data);
        $("precheckButton").disabled = false;
        $("skipPrecheckButton").textContent = "Precheck übersprungen";
        $("toTestsButton").disabled = false;
        updateStepper();
    } catch (error) {
        setBusy($("skipPrecheckButton"), false, "", "Precheck überspringen");
        showError(error.message);
    }
}

function setRcsLimitDisplay(prefix, data) {
    const limits = data.rcs_limits;
    const input = $(prefix + "RcsInput");
    const minimum = Number(limits.rcs_min_dbsm);
    const maximum = Number(limits.rcs_max_dbsm);
    $(prefix + "RcsPolarization").textContent = formatPolarization(limits.polarization);
    $(prefix + "RcsEirp").textContent = fixed(limits.eirp_dbm) + " dBm";
    $(prefix + "RcsRange").textContent = fixed(minimum) + " bis " + fixed(maximum) + " dBsm";
    input.min = String(minimum);
    input.max = String(maximum);
    input.value = String(minimum <= 0 && maximum >= 0 ? 0 : minimum);
    $(prefix + "RcsPanel").hidden = false;
}

function invalidateStaticRcs() {
    $("staticRcsPanel").hidden = true;
}

function invalidateDynamicRcs() {
    $("dynamicRcsPanel").hidden = true;
}

function staticBaseConfiguration() {
    const distance = Number($("distanceInput").value);
    if (!Number.isFinite(distance) || distance <= 0) throw new Error("Distanz muss größer als 0 m sein.");
    return {distance};
}

function dynamicBaseConfiguration() {
    const start = Number($("dynamicStartDistanceInput").value);
    const end = Number($("dynamicEndDistanceInput").value);
    const velocity = Number($("dynamicVelocityInput").value);
    const rcsConstantState = Number($("dynamicRcsModeInput").value);
    if (![start, end, velocity].every(Number.isFinite) || start <= 0 || end <= 0 || velocity <= 0) {
        throw new Error("Distanzen und Geschwindigkeit müssen größer als 0 sein.");
    }
    if (start === end) throw new Error("Start- und Enddistanz müssen unterschiedlich sein.");
    return {start, end, velocity, rcsConstantState};
}

async function prepareStaticRcs() {
    clearError();
    const {distance} = staticBaseConfiguration();
    setBusy($("staticRcsLimitsButton"), true, "RCS-Grenzen werden ermittelt …", "RCS-Grenzen ermitteln");
    invalidateStaticRcs();
    try {
        const data = await apiRequest(
            "/api/static/rcs-limits?distance_m=" + encodeURIComponent(distance),
            {method: "POST"}
        );
        setRcsLimitDisplay("static", data);
    } catch (error) {
        showError(error.message);
    } finally {
        setBusy($("staticRcsLimitsButton"), false, "", "RCS-Grenzen ermitteln");
    }
}

async function prepareDynamicRcs() {
    clearError();
    const configuration = dynamicBaseConfiguration();
    setBusy($("dynamicRcsLimitsButton"), true, "RCS-Grenzen werden ermittelt …", "RCS-Grenzen ermitteln");
    invalidateDynamicRcs();
    try {
        const data = await apiRequest(
            "/api/dynamic/rcs-limits?start_distance_m=" + encodeURIComponent(configuration.start)
                + "&end_distance_m=" + encodeURIComponent(configuration.end)
                + "&velocity_kmh=" + encodeURIComponent(configuration.velocity)
                + "&rcs_constant_state=" + encodeURIComponent(configuration.rcsConstantState),
            {method: "POST"}
        );
        setRcsLimitDisplay("dynamic", data);
    } catch (error) {
        showError(error.message);
    } finally {
        setBusy($("dynamicRcsLimitsButton"), false, "", "RCS-Grenzen ermitteln");
    }
}

function staticConfiguration() {
    const {distance} = staticBaseConfiguration();
    if ($("staticRcsPanel").hidden) throw new Error("Bitte zuerst die RCS-Grenzen ermitteln.");
    const rcs = Number($("staticRcsInput").value);
    if (!Number.isFinite(rcs)) throw new Error("Bitte eine gültige RCS eingeben.");
    return {
        type: "static",
        title: "Statische Messung",
        description: distance.toFixed(1) + " m konstante Zieldistanz | " + rcs.toFixed(1) + " dBsm",
        resultParameters: distance.toFixed(1) + " m · " + rcs.toFixed(1) + " dBsm",
        url: "/api/static/start?distance_m=" + encodeURIComponent(distance)
            + "&rcs_dbsm=" + encodeURIComponent(rcs)
    };
}

function dynamicConfiguration() {
    const {start, end, velocity, rcsConstantState} = dynamicBaseConfiguration();
    if ($("dynamicRcsPanel").hidden) throw new Error("Bitte zuerst die RCS-Grenzen ermitteln.");
    const rcs = Number($("dynamicRcsInput").value);
    if (!Number.isFinite(rcs)) throw new Error("Bitte eine gültige RCS eingeben.");
    const rcsMode = rcsConstantState === 0 ? "konstante RCS" : "variable RCS";
    return {
        type: "dynamic",
        title: "Dynamische Messung",
        description: start.toFixed(1) + " m → " + end.toFixed(1) + " m | " + velocity.toFixed(1) + " km/h | " + rcs.toFixed(1) + " dBsm, " + rcsMode,
        resultParameters: start.toFixed(1) + " m → " + end.toFixed(1) + " m · " + velocity.toFixed(1) + " km/h · " + rcs.toFixed(1) + " dBsm · " + rcsMode,
        url: "/api/dynamic/start?start_distance_m=" + encodeURIComponent(start)
            + "&end_distance_m=" + encodeURIComponent(end)
            + "&velocity_kmh=" + encodeURIComponent(velocity)
            + "&rcs_constant_state=" + encodeURIComponent(rcsConstantState)
            + "&rcs_dbsm=" + encodeURIComponent(rcs)
    };
}

// Vom RadEsT beim Setzen des RCS gemeldete Daempfungsstufe (ca. 4 dB je Schritt).
function attSetValue(setting) {
    const value = setting?.values?.attSet;
    return value === null || value === undefined ? null : Number(value);
}

function showAttSet(configuration, setting) {
    const attSet = attSetValue(setting);
    $("radestAttSet").textContent = attSet === null ? "–" : fixed(attSet);
    if (attSet !== null && configuration && !configuration.attSetShown) {
        configuration.resultParameters += " · attSet " + fixed(attSet);
        configuration.attSetShown = true;
    }
}

function resetMeasurementDisplay(configuration) {
    uiState.samples = [];
    uiState.lastMeasurement = null;
    uiState.logFile = null;
    uiState.measurementStartedAt = performance.now();
    $("measurementTitle").textContent = configuration.title;
    $("measurementDescription").textContent = configuration.description;
    $("measurementState").className = "live-badge";
    $("measurementState").lastChild.textContent = "Live";
    ["requestedDistance", "radestDistance", "vehicleDistance", "distanceError", "angle",
        "relativeSpeed", "relativeAcceleration", "scenarioPhase", "scenarioProgress",
        "scenarioDuration", "measurementElapsed", "radestAttSet"].forEach(id => $(id).textContent = "–");
    $("scenarioStatus").textContent = "Läuft";
    $("stopButton").disabled = true;
    drawChart();
}

async function startConfiguredMeasurement(configuration) {
    clearError();
    uiState.lastConfiguration = configuration;
    uiState.measurementComplete = false;
    uiState.currentMeasurement = configuration;
    resetMeasurementDisplay(configuration);
    showMeasurementScreen();
    try {
        const data = await apiRequest(configuration.url, {method: "POST"});
        uiState.logFile = data.log_file || null;
        showAttSet(configuration, data.rcs_radest_setting);
        if (configuration.type === "static") {
            $("requestedDistance").textContent = fixed(data.requested_distance);
            $("radestDistance").textContent = fixed(data.radest_distance);
            $("scenarioPhase").textContent = "Konstante Distanz";
            $("scenarioProgress").textContent = "laufend";
        } else {
            $("requestedDistance").textContent = fixed(data.start_distance);
            $("radestDistance").textContent = fixed(data.start_distance);
            $("scenarioDuration").textContent = fixed(data.total_duration_s);
            $("scenarioPhase").textContent = "Startdistanz halten";
            $("scenarioProgress").textContent = "0,0 %";
        }
        startLiveMeasurement();
    } catch (error) {
        uiState.currentMeasurement = null;
        showStep(4);
        showError(error.message);
    }
}

async function startStaticMeasurement() {
    try {
        await startConfiguredMeasurement(staticConfiguration());
    } catch (error) {
        showError(error.message);
    }
}

async function startDynamicMeasurement() {
    try {
        await startConfiguredMeasurement(dynamicConfiguration());
    } catch (error) {
        showError(error.message);
    }
}

function startLiveMeasurement() {
    stopLiveMeasurement(true);
    socketClosingIntentionally = false;
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    measurementSocket = new WebSocket(protocol + "//" + location.host + "/ws/static");
    measurementSocket.onopen = () => {
        $("stopButton").disabled = false;
    };
    measurementSocket.onmessage = event => {
        const message = JSON.parse(event.data);
        if (message.type === "measurement") updateMeasurement(message.data);
        if (message.type === "complete") {
            stopLiveMeasurement(true);
            finishMeasurement("finished");
        }
        if (message.type === "error") {
            stopLiveMeasurement(true);
            setIndicator("diagnosisIndicator", "error");
            finishMeasurement("failed", message.message);
        }
    };
    measurementSocket.onerror = () => {
        if (!socketClosingIntentionally) showError("WebSocket-Verbindung fehlgeschlagen.");
    };
    measurementSocket.onclose = () => {
        measurementSocket = null;
        $("stopButton").disabled = true;
    };
}

function fixed(value, digits = 2) {
    const number = numeric(value);
    return Number.isFinite(number) ? number.toFixed(digits) : "–";
}

function updateMeasurement(data) {
    uiState.lastMeasurement = data;
    uiState.samples.push({
        time: numeric(data.elapsed_s),
        radest: numeric(data.radest_distance),
        vehicle: numeric(data.vehicle?.distance?.value),
        error: numeric(data.distance_error),
        phase: data.phase || null
    });
    $("requestedDistance").textContent = fixed(data.requested_distance);
    $("radestDistance").textContent = fixed(data.radest_distance);
    $("vehicleDistance").textContent = fixed(data.vehicle?.distance?.value);
    $("distanceError").textContent = fixed(data.distance_error);
    $("measurementElapsed").textContent = fixed(data.elapsed_s);
    $("angle").textContent = signalText(data.vehicle?.angle);
    $("relativeSpeed").textContent = signalText(data.vehicle?.relative_speed);
    $("relativeAcceleration").textContent = signalText(data.vehicle?.relative_acceleration);
    if (data.test_type === "dynamic") {
        const phaseLabels = {pre_hold: "Startdistanz halten", moving: "Bewegung", post_hold: "Enddistanz halten"};
        $("scenarioPhase").textContent = phaseLabels[data.phase] || data.phase || "–";
        const progress = numeric(data.scenario_progress);
        $("scenarioProgress").textContent = Number.isFinite(progress) ? fixed(progress * 100, 1) + " %" : "–";
        $("scenarioDuration").textContent = fixed(data.dynamic_total_duration_s);
    }
    drawChart();
}

function signalText(signal) {
    return signal && Number.isFinite(numeric(signal.value))
        ? fixed(signal.value) + (signal.unit ? " " + signal.unit : "")
        : "–";
}

function numeric(value) {
    if (value === null || value === undefined || value === "") return Number.NaN;
    const number = Number(value);
    return Number.isFinite(number) ? number : Number.NaN;
}

function drawChart(canvasId = "liveChart") {
    const canvas = $(canvasId);
    if (!canvas) return;
    const width = Math.max(320, canvas.clientWidth || 900);
    const height = canvasId === "resultChart" ? 360 : 320;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    const context = canvas.getContext("2d");
    context.scale(ratio, ratio);
    context.clearRect(0, 0, width, height);
    const pad = {left: 48, right: 18, top: 28, bottom: 34};
    const points = uiState.samples.filter(point => Number.isFinite(point.time) && Number.isFinite(point.radest));
    context.font = "12px Arial";
    context.fillStyle = "#63756d";
    if (points.length < 2) {
        window.DistanceChartTooltip?.clear(canvas);
        context.textAlign = "center";
        context.fillText("Der Live-Verlauf erscheint mit den ersten Messpunkten.", width / 2, height / 2);
        return;
    }
    const values = points.flatMap(point => [point.radest, point.vehicle]).filter(Number.isFinite);
    let minY = Math.min(...values);
    let maxY = Math.max(...values);
    const margin = Math.max(0.5, (maxY - minY) * 0.12);
    minY -= margin;
    maxY += margin;
    const minX = points[0].time;
    const maxX = Math.max(points.at(-1).time, minX + 0.1);
    const x = value => pad.left + (value - minX) / (maxX - minX) * (width - pad.left - pad.right);
    const y = value => pad.top + (maxY - value) / (maxY - minY) * (height - pad.top - pad.bottom);
    context.strokeStyle = "#d5e5dc";
    context.lineWidth = 1;
    for (let index = 0; index <= 4; index++) {
        const py = pad.top + index / 4 * (height - pad.top - pad.bottom);
        context.beginPath(); context.moveTo(pad.left, py); context.lineTo(width - pad.right, py); context.stroke();
        context.fillStyle = "#63756d"; context.textAlign = "right";
        context.fillText((maxY - index / 4 * (maxY - minY)).toFixed(1), pad.left - 7, py + 4);
    }
    drawPhaseMarkers(context, points, x, pad, height);
    drawSeries(context, points, "radest", x, y, "#008143");
    drawSeries(context, points, "vehicle", x, y, "#d58a00");
    context.textAlign = "left"; context.fillStyle = "#008143"; context.fillText("— RadEsT", pad.left, 15);
    context.fillStyle = "#d58a00"; context.fillText("— Fahrzeug", pad.left + 85, 15);
    context.fillStyle = "#63756d";
    context.textAlign = "left"; context.fillText("0 s", pad.left, height - 10);
    context.textAlign = "right"; context.fillText((maxX - minX).toFixed(1) + " s", width - pad.right, height - 10);
    context.save();
    context.translate(13, height / 2);
    context.rotate(-Math.PI / 2);
    context.textAlign = "center";
    context.fillText("Distanz [m]", 0, 0);
    context.restore();
    window.DistanceChartTooltip?.update(canvas, {
        points,
        timeKey: "time",
        radestKey: "radest",
        vehicleKey: "vehicle",
        x,
        y,
        pad,
        width,
        height
    });
}

function drawPhaseMarkers(context, points, x, pad, height) {
    const labels = {pre_hold: "Halten Start", moving: "Bewegung", post_hold: "Halten Ende"};
    let previous = null;
    for (const point of points) {
        if (!point.phase || point.phase === previous) continue;
        const px = x(point.time);
        if (previous !== null) {
            context.save();
            context.setLineDash([4, 4]);
            context.strokeStyle = "#9cb3a8";
            context.beginPath();
            context.moveTo(px, pad.top);
            context.lineTo(px, height - pad.bottom);
            context.stroke();
            context.restore();
        }
        context.fillStyle = "#63756d";
        context.font = "11px Arial";
        context.textAlign = "left";
        context.fillText(labels[point.phase] || point.phase, Math.min(px + 4, context.canvas.clientWidth - 85), pad.top + 12);
        previous = point.phase;
    }
}

function drawSeries(context, points, key, x, y, color) {
    context.strokeStyle = color;
    context.lineWidth = 2.5;
    context.beginPath();
    let started = false;
    for (const point of points) {
        if (!Number.isFinite(point[key])) {
            started = false;
            continue;
        }
        if (!started) context.moveTo(x(point.time), y(point[key]));
        else context.lineTo(x(point.time), y(point[key]));
        started = true;
    }
    context.stroke();
}

function stopLiveMeasurement(intentional = false) {
    socketClosingIntentionally = intentional;
    if (measurementSocket) {
        measurementSocket.close();
        measurementSocket = null;
    }
    $("stopButton").disabled = true;
}

async function stopMeasurement() {
    clearError();
    $("stopButton").disabled = true;
    try {
        const data = await apiRequest("/api/measurement/stop", {method: "POST"});
        stopLiveMeasurement(true);
        finishMeasurement(data.status === "aborted" ? "aborted" : "finished");
    } catch (error) {
        $("stopButton").disabled = false;
        showError(error.message);
    }
}

function finishMeasurement(status, errorMessage = "") {
    const configuration = uiState.currentMeasurement;
    if (!configuration) return;
    uiState.currentMeasurement = null;
    uiState.measurementComplete = true;
    const validErrors = uiState.samples.map(sample => sample.error).filter(Number.isFinite).map(Math.abs);
    const duration = uiState.lastMeasurement?.elapsed_s
        ?? ((performance.now() - uiState.measurementStartedAt) / 1000);
    $("resultVehicle").textContent = uiState.vehicleName;
    $("resultRun").textContent = uiState.runId || "–";
    $("resultType").textContent = configuration.title;
    $("resultParameters").textContent = configuration.resultParameters;
    $("resultDuration").textContent = fixed(duration) + " s";
    $("resultSamples").textContent = String(uiState.samples.length);
    $("resultMeanError").textContent = validErrors.length
        ? fixed(validErrors.reduce((sum, value) => sum + value, 0) / validErrors.length) + " m"
        : "Nicht verfügbar";
    $("resultMaxError").textContent = validErrors.length
        ? fixed(Math.max(...validErrors)) + " m"
        : "Nicht verfügbar";
    $("logFile").textContent = uiState.logFile || "–";
    $("resultStatus").className = "status-pill " + (status === "finished" ? "success" : status === "aborted" ? "warning" : "error");
    $("resultStatus").textContent = status === "finished" ? "Abgeschlossen" : status === "aborted" ? "Abgebrochen" : "Fehler";
    $("resultHeadline").textContent = errorMessage || (status === "aborted" ? "Die Messung wurde durch den Benutzer beendet." : "Die Messung wurde abgeschlossen.");
    uiState.currentStep = 5;
    document.querySelectorAll(".workflow-screen").forEach(screen => screen.hidden = true);
    $("screenResult").hidden = false;
    updateStepper();
    requestAnimationFrame(() => drawChart("resultChart"));
}

async function disconnectSystem(finishedByUser = false) {
    clearError();
    if (uiState.currentMeasurement && !confirm("Die laufende Messung und den TestRun wirklich beenden?")) return;
    stopLiveMeasurement(true);
    try {
        const oldRun = uiState.runId;
        await apiRequest("/api/disconnect", {method: "POST"});
        resetWorkflow();
        showMessage(finishedByUser && oldRun ? "TestRun " + oldRun + " wurde abgeschlossen." : "Testsystem wurde getrennt.");
    } catch (error) {
        showError(error.message);
    }
}

function resetWorkflow() {
    Object.assign(uiState, {
        connected: false, vehicleId: null, vehicleName: "", runId: null, signals: [],
        quickCheckComplete: false, quickCheckResult: null, precheckComplete: false,
        precheckSkipped: false, currentStep: 1, measurementComplete: false,
        currentMeasurement: null, lastMeasurement: null, samples: [], logFile: null,
        lastConfiguration: null
    });
    $("vehicle").disabled = false;
    $("connectionResult").hidden = true;
    $("quickCheckResult").hidden = true;
    $("precheckResult").hidden = true;
    updatePrecheckProgress();
    invalidateStaticRcs();
    invalidateDynamicRcs();
    $("toQuickCheckButton").disabled = true;
    $("toPrecheckButton").disabled = true;
    $("toTestsButton").disabled = true;
    setBusy($("connectButton"), false, "", "Prüfung starten");
    updateHeader();
    showStep(1);
}

async function restoreStatus() {
    try {
        const status = await apiRequest("/api/status");
        if (!status.connected) {
            resetWorkflow();
            return;
        }
        uiState.connected = true;
        uiState.vehicleId = Number(status.vehicle_id);
        $("vehicle").value = String(status.vehicle_id);
        $("vehicle").disabled = true;
        uiState.vehicleName = selectedVehicleName();
        uiState.runId = status.test_run?.run_id || null;
        uiState.signals = status.signals || [];
        uiState.quickCheckComplete = Boolean(status.quick_check);
        uiState.quickCheckResult = status.quick_check || null;
        uiState.precheckComplete = Boolean(status.precheck?.done);
        uiState.precheckSkipped = Boolean(status.precheck?.skipped);
        if (uiState.quickCheckResult) {
            renderQuickCheck(uiState.quickCheckResult);
            $("quickCheckButton").textContent = "Quick Check erneut starten";
        }
        if (uiState.precheckComplete) {
            renderPrecheck({
                ...status.precheck,
                status: status.precheck.skipped ? "skipped" : "completed"
            });
            $("precheckButton").textContent = status.precheck.skipped
                ? "Precheck nachholen"
                : "Precheck erneut starten";
            if (!status.precheck.skipped) {
                updatePrecheckProgress(null, ["polarization", "frequency", "power"]);
            }
            $("skipPrecheckButton").disabled = true;
            $("toTestsButton").disabled = false;
        }
        $("connectionResult").hidden = false;
        $("checkRadest").className = "check-row ok";
        $("checkDiagnosis").className = "check-row ok";
        $("checkSignals").className = "check-row " + (uiState.signals.includes("distance") ? "ok" : "warning");
        $("signals").textContent = "Messsignale: " + (uiState.signals.join(", ") || "keine");
        $("toQuickCheckButton").disabled = false;
        $("toPrecheckButton").disabled = !uiState.quickCheckComplete;
        updateHeader();
        if (status.measurement_running && status.latest_measurement) {
            const latest = status.latest_measurement;
            uiState.currentMeasurement = restoredConfiguration(latest);
            uiState.lastConfiguration = uiState.currentMeasurement;
            resetMeasurementDisplay(uiState.currentMeasurement);
            uiState.logFile = status.log_file || null;
            showAttSet(
                uiState.currentMeasurement,
                latest.test_type === "dynamic"
                    ? status.dynamic_rcs_setting
                    : status.static_rcs_setting
            );
            showMeasurementScreen();
            updateMeasurement(latest);
            startLiveMeasurement();
        } else {
            showStep(uiState.precheckComplete ? 4 : uiState.quickCheckComplete ? 3 : 2);
        }
    } catch (error) {
        showError("Systemstatus konnte nicht geladen werden: " + error.message);
    }
}

function restoredConfiguration(data) {
    if (data.test_type === "dynamic") {
        const start = Number(data.scenario_start_distance);
        const end = Number(data.scenario_end_distance);
        const velocity = Number(data.scenario_velocity_kmh);
        const rcs = Number(data.rcs_dbsm);
        const rcsConstantState = Number(data.rcs_constant_state);
        const rcsMode = rcsConstantState === 0 ? "konstante RCS" : "variable RCS";
        return {
            type: "dynamic", title: "Dynamische Messung",
            description: fixed(start, 1) + " m → " + fixed(end, 1) + " m | " + fixed(velocity, 1) + " km/h | " + fixed(rcs, 1) + " dBsm, " + rcsMode,
            resultParameters: fixed(start, 1) + " m → " + fixed(end, 1) + " m · " + fixed(velocity, 1) + " km/h · " + fixed(rcs, 1) + " dBsm · " + rcsMode,
            url: "/api/dynamic/start?start_distance_m=" + encodeURIComponent(start)
                + "&end_distance_m=" + encodeURIComponent(end)
                + "&velocity_kmh=" + encodeURIComponent(velocity)
                + "&rcs_constant_state=" + encodeURIComponent(rcsConstantState)
                + "&rcs_dbsm=" + encodeURIComponent(rcs)
        };
    }
    const distance = Number(data.requested_distance);
    const rcs = Number(data.rcs_dbsm);
    return {
        type: "static", title: "Statische Messung",
        description: fixed(distance, 1) + " m konstante Zieldistanz | " + fixed(rcs, 1) + " dBsm",
        resultParameters: fixed(distance, 1) + " m · " + fixed(rcs, 1) + " dBsm",
        url: "/api/static/start?distance_m=" + encodeURIComponent(distance)
            + "&rcs_dbsm=" + encodeURIComponent(rcs)
    };
}

$("connectButton").addEventListener("click", connectSystem);
$("toQuickCheckButton").addEventListener("click", () => showStep(2));
$("quickCheckButton").addEventListener("click", runQuickCheck);
$("toPrecheckButton").addEventListener("click", () => showStep(3));
$("precheckButton").addEventListener("click", runPrecheck);
$("skipPrecheckButton").addEventListener("click", skipPrecheck);
$("toTestsButton").addEventListener("click", () => showStep(4));
$("staticRcsLimitsButton").addEventListener("click", prepareStaticRcs);
$("dynamicRcsLimitsButton").addEventListener("click", prepareDynamicRcs);
$("staticButton").addEventListener("click", startStaticMeasurement);
$("dynamicButton").addEventListener("click", startDynamicMeasurement);
$("distanceInput").addEventListener("input", invalidateStaticRcs);
["dynamicStartDistanceInput", "dynamicEndDistanceInput", "dynamicVelocityInput", "dynamicRcsModeInput"].forEach(id => {
    $(id).addEventListener("input", invalidateDynamicRcs);
    $(id).addEventListener("change", invalidateDynamicRcs);
});
$("stopButton").addEventListener("click", stopMeasurement);
$("disconnectButton").addEventListener("click", () => disconnectSystem(false));
$("repeatButton").addEventListener("click", () => {
    uiState.measurementComplete = false;
    invalidateStaticRcs();
    invalidateDynamicRcs();
    showStep(4);
    showMessage("Vor der Wiederholung bitte die RCS-Grenzen erneut ermitteln.");
});
$("moreMeasurementButton").addEventListener("click", () => {
    uiState.measurementComplete = false;
    invalidateStaticRcs();
    invalidateDynamicRcs();
    showStep(4);
});
$("finishRunButton").addEventListener("click", () => disconnectSystem(true));
document.querySelectorAll("[data-go-step]").forEach(button => {
    button.addEventListener("click", () => showStep(Number(button.dataset.goStep)));
});
document.querySelectorAll(".stepper li").forEach(item => {
    item.querySelector("button").addEventListener("click", () => showStep(Number(item.dataset.step)));
});
window.addEventListener("resize", () => {
    if (!$("screenMeasurement").hidden) drawChart();
    if (!$("screenResult").hidden) drawChart("resultChart");
});

$("vehicle").addEventListener("change", loadVehicleProfile);

updateHeader();
restoreStatus().then(loadVehicleProfile);
