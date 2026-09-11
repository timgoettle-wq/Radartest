"use strict";

const resultState = {
    results: [],
    currentRun: null,
    currentMeasurement: null
};

const $ = id => document.getElementById(id);

const statusLabels = {
    finished: "Abgeschlossen",
    completed_with_errors: "Mit Fehlern",
    aborted: "Abgebrochen",
    running: "Laufend",
    failed: "Fehler",
    success: "Erfolgreich",
    warning: "Auffällig",
    pending: "Nicht vorhanden",
    completed: "Durchgeführt",
    skipped: "Übersprungen"
};

function statusClass(status) {
    if (["finished", "success", "completed"].includes(status)) return "success";
    if (["aborted", "warning", "skipped", "running"].includes(status)) return "warning";
    if (["failed", "completed_with_errors"].includes(status)) return "error";
    return "neutral";
}

async function apiRequest(url) {
    const response = await fetch(url);
    const text = await response.text();
    let data;

    try {
        data = JSON.parse(text);
    } catch {
        throw new Error(text || "Ungültige Serverantwort");
    }

    if (!response.ok) throw new Error(data.detail || "Unbekannter Fehler");
    return data;
}

function showMessage(message, error = false) {
    $("resultsMessage").textContent = message || "";
    $("resultsMessage").className = "status-message" + (error ? " error" : "");
}

function textElement(tag, text, className = "") {
    const element = document.createElement(tag);
    element.textContent = text;
    if (className) element.className = className;
    return element;
}

function badge(status) {
    return textElement("span", statusLabels[status] || status || "Unbekannt", "status-pill " + statusClass(status));
}

function formatDate(value) {
    if (!value) return "–";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString("de-DE");
}

function formatNumber(value, digits = 2, unit = "") {
    if (value === null || value === undefined || value === "") return "–";
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(digits).replace(".", ",") + unit : "–";
}

function formatPrecheckValue(value, unit) {
    if (value === null || value === undefined || value === "") return "–";
    const formatted = Array.isArray(value) ? value.join(" – ") : String(value);
    return formatted.toLocaleLowerCase().includes(unit.toLocaleLowerCase())
        ? formatted
        : formatted + " " + unit;
}

function testTypeLabel(type) {
    return type === "dynamic" ? "Dynamische Messung" : type === "static" ? "Statische Messung" : type || "Unbekannte Messung";
}

function parameterText(test) {
    if (test.type === "dynamic") {
        const parameters = test.parameters || {};
        return formatNumber(parameters.start_distance_m, 1, " m") + " → "
            + formatNumber(parameters.end_distance_m, 1, " m") + " · "
            + formatNumber(parameters.velocity_kmh, 1, " km/h");
    }
    return formatNumber(test.requested_distance, 1, " m");
}

function showView(id) {
    document.querySelectorAll(".results-view").forEach(view => view.hidden = true);
    $(id).hidden = false;
    $("resultsOverviewHeader").hidden = id !== "resultsOverview";
    showMessage("");
}

function setLocation(runId = null, testId = null, replace = false) {
    const url = new URL(location.href);
    url.search = "";
    if (runId) url.searchParams.set("run", runId);
    if (testId) url.searchParams.set("test", testId);
    history[replace ? "replaceState" : "pushState"]({}, "", url);
}

async function loadResults() {
    showMessage("Ergebnisse werden geladen …");
    try {
        const data = await apiRequest("/api/results");
        resultState.results = data.results || [];
        renderResults();
        showMessage("");
    } catch (error) {
        showMessage("Ergebnisse konnten nicht geladen werden: " + error.message, true);
    }
}

function renderResults() {
    const query = $("resultSearch").value.trim().toLocaleLowerCase("de");
    const status = $("resultStatusFilter").value;
    const type = $("resultTypeFilter").value;
    const visible = resultState.results.filter(run => {
        const searchText = (run.vehicle_name + " " + run.run_id).toLocaleLowerCase("de");
        return (!query || searchText.includes(query))
            && (!status || run.status === status)
            && (!type || (run.test_types || []).includes(type));
    });
    const body = $("resultsTableBody");
    body.replaceChildren();
    $("resultsCount").textContent = resultState.results.length === 1
        ? "1 TestRun im Ergebnisarchiv"
        : resultState.results.length + " TestRuns im Ergebnisarchiv";

    for (const run of visible) {
        const row = body.insertRow();
        row.className = "clickable-table-row";
        row.tabIndex = 0;
        row.setAttribute("role", "button");
        row.insertCell().textContent = formatDate(run.start_time);
        const vehicleCell = row.insertCell();
        vehicleCell.append(textElement("strong", run.vehicle_name));
        vehicleCell.append(textElement("small", run.run_id));
        row.insertCell().append(badge(run.status));
        row.insertCell().textContent = String(run.test_count);
        row.insertCell().append(badge(run.quick_check_status));
        row.insertCell().append(badge(run.precheck_status));
        row.addEventListener("click", () => openRun(run.run_id));
        row.addEventListener("keydown", event => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                openRun(run.run_id);
            }
        });
    }

    $("emptyResults").hidden = visible.length > 0;
}

function fact(label, value) {
    const element = document.createElement("div");
    element.append(textElement("span", label));
    element.append(textElement("strong", value || "–"));
    return element;
}

async function openRun(runId, push = true) {
    showMessage("TestRun wird geladen …");
    try {
        const data = await apiRequest("/api/results/" + encodeURIComponent(runId));
        resultState.currentRun = data;
        renderRun(data);
        showView("runDetail");
        if (push) setLocation(runId);
    } catch (error) {
        showMessage("TestRun konnte nicht geladen werden: " + error.message, true);
    }
}

function renderRun(data) {
    const summary = data.summary;
    const run = data.run;
    $("runDetailTitle").textContent = summary.vehicle_name;
    $("runBreadcrumb").textContent = summary.vehicle_name;
    $("runDetailSubtitle").textContent = summary.run_id;
    $("downloadRun").href = "/api/results/" + encodeURIComponent(summary.run_id) + "/download";
    const facts = $("runFacts");
    facts.replaceChildren(
        fact("Start", formatDate(run.start_time)),
        fact("Ende", formatDate(run.end_time)),
        fact("Status", statusLabels[run.status] || run.status),
        fact("Git-Commit", run.software?.git_commit || "Nicht erfasst")
    );
    renderQuickCheck(run.quick_check, summary.quick_check_status);
    renderPrecheck(run.precheck, summary.precheck_status);
    renderMeasurements(summary.run_id, run.tests || []);
}

function renderQuickCheck(quickCheck, status) {
    $("archiveQuickStatus").replaceWith(Object.assign(badge(status), {id: "archiveQuickStatus"}));
    const content = $("archiveQuickContent");
    content.replaceChildren();

    if (!quickCheck) {
        content.append(textElement("p", "Für diesen TestRun ist kein Quick Check gespeichert.", "muted"));
        return;
    }
    const summary = quickCheck.identification_summary || {};
    const dtcs = (quickCheck.dtcs_before || []).flatMap(ecu =>
        (ecu.dtcs || []).map(dtc => ({...dtc, ecuName: ecu.ecu_name || "Steuergerät"}))
    );
    const values = document.createElement("div");
    values.className = "compact-facts";
    values.append(
        compactFact("Identifiziert", summary.match || 0),
        compactFact("Abweichend", summary.mismatch || 0),
        compactFact("Lesefehler", summary.read_error || 0),
        compactFact("DTCs", dtcs.length)
    );
    content.append(values);

    if (quickCheck.identification?.length) {
        const details = document.createElement("details");
        details.append(textElement("summary", "Identifikationswerte anzeigen"));
        const table = document.createElement("table");
        table.className = "results-table compact-table";
        const header = table.createTHead().insertRow();
        ["Merkmal", "Wert", "Bewertung"].forEach(label => header.append(textElement("th", label)));
        const body = table.createTBody();
        for (const item of quickCheck.identification) {
            const row = body.insertRow();
            row.insertCell().textContent = item.label || item.identifier_key || "–";
            row.insertCell().textContent = item.value ?? item.error_message ?? "–";
            row.insertCell().textContent = statusLabels[item.status] || item.status || "–";
        }
        details.append(table);
        content.append(details);
    }
    if (dtcs.length) {
        const details = document.createElement("details");
        details.append(textElement("summary", "Fehlerspeicher anzeigen"));
        const list = document.createElement("div");
        list.className = "archive-dtc-list";
        for (const dtc of dtcs) {
            list.append(textElement("p", dtc.ecuName + " · " + dtc.code + " · Status " + dtc.status));
        }
        details.append(list);
        content.append(details);
    }
}

function compactFact(label, value) {
    const element = document.createElement("div");
    element.className = "fact";
    element.append(textElement("span", label), textElement("strong", String(value)));
    return element;
}

function renderPrecheck(precheck, status) {
    $("archivePrecheckStatus").replaceWith(Object.assign(badge(status), {id: "archivePrecheckStatus"}));
    const content = $("archivePrecheckContent");
    content.replaceChildren();

    if (!precheck) {
        content.append(textElement("p", "Für diesen TestRun ist kein Precheck gespeichert.", "muted"));
        return;
    }
    if (precheck.skipped) {
        content.append(textElement("p", "Der Precheck wurde bewusst übersprungen.", "archive-warning"));
        return;
    }
    const values = document.createElement("div");
    values.className = "compact-facts";
    values.append(
        compactFact("Polarisation", precheck.polarization ?? "–"),
        compactFact("Frequenzbereich", formatPrecheckValue(precheck.frequency_range, "GHz")),
        compactFact("Leistung", formatPrecheckValue(precheck.power, "dBm"))
    );
    content.append(values);
}

function renderMeasurements(runId, tests) {
    const body = $("measurementsTableBody");
    body.replaceChildren();
    $("measurementCount").textContent = tests.length + " Messung(en)";
    $("emptyMeasurements").hidden = tests.length > 0;

    for (const test of tests) {
        const row = body.insertRow();
        row.insertCell().textContent = testTypeLabel(test.type);
        row.insertCell().textContent = parameterText(test);
        row.insertCell().append(badge(test.status));
        row.insertCell().textContent = formatDate(test.start_time);
        row.insertCell().textContent = test.sample_count ?? "–";
        const actionCell = row.insertCell();
        const button = textElement("button", "Messung öffnen", "small-button");
        button.type = "button";
        button.disabled = !test.log_file;
        button.addEventListener("click", () => openMeasurement(runId, String(test.test_id)));
        actionCell.append(button);
    }
}

async function openMeasurement(runId, testId, push = true) {
    showMessage("Messdaten werden geladen …");
    try {
        const url = "/api/results/" + encodeURIComponent(runId) + "/measurements/" + encodeURIComponent(testId);
        const data = await apiRequest(url);
        resultState.currentMeasurement = data;
        renderMeasurement(data);
        showView("measurementDetail");
        if (push) setLocation(runId, testId);
        requestAnimationFrame(() => drawArchiveChart(data.points || []));
    } catch (error) {
        showMessage("Messdaten konnten nicht geladen werden: " + error.message, true);
    }
}

function renderMeasurement(data) {
    const measurement = data.measurement;
    const summary = data.summary;
    $("archiveMeasurementTitle").textContent = testTypeLabel(measurement.type);
    $("measurementBreadcrumb").textContent = testTypeLabel(measurement.type);
    $("backToRun").textContent = data.run.vehicle_name || "TestRun";
    $("archiveMeasurementSubtitle").textContent = data.run.vehicle_name + " · " + parameterText(measurement);
    $("archiveDuration").textContent = formatNumber(summary.duration_s, 2, " s");
    $("archiveSamples").textContent = String(summary.sample_count);
    $("archiveValidSamples").textContent = String(summary.valid_distance_points);
    $("archiveDropouts").textContent = String(summary.dropout_count);
    $("archiveMeanError").textContent = formatNumber(summary.mean_absolute_error_m, 3, " m");
    $("archiveMaxError").textContent = formatNumber(summary.max_absolute_error_m, 3, " m");
    $("downloadCsv").href = "/api/results/" + encodeURIComponent(data.run.run_id)
        + "/measurements/" + encodeURIComponent(measurement.test_id) + "/download";
    $("measurementMetadata").replaceChildren(
        fact("Test-ID", measurement.test_id),
        fact("Status", statusLabels[measurement.status] || measurement.status),
        fact("Start", formatDate(measurement.start_time)),
        fact("Ende", formatDate(measurement.end_time)),
        fact("Abschlussgrund", measurement.end_reason || "–"),
        fact("Fehlerhafte Messpunkte", String(summary.error_sample_count))
    );
}

function drawArchiveChart(points) {
    const canvas = $("archiveChart");
    const width = Math.max(480, canvas.clientWidth || 1000);
    const height = 420;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    const context = canvas.getContext("2d");
    context.scale(ratio, ratio);
    context.clearRect(0, 0, width, height);
    const valid = points.filter(point => Number.isFinite(point.elapsed_s) && Number.isFinite(point.radest_distance_m));
    const pad = {left: 58, right: 22, top: 38, bottom: 42};
    context.font = "12px Arial";

    if (valid.length < 2) {
        context.fillStyle = "#63756d";
        context.textAlign = "center";
        context.fillText("Für diesen Graphen sind nicht genügend Messpunkte vorhanden.", width / 2, height / 2);
        return;
    }

    const values = valid.flatMap(point => [point.radest_distance_m, point.vehicle_distance_m]).filter(Number.isFinite);
    let minY = Math.min(...values);
    let maxY = Math.max(...values);
    const margin = Math.max(0.5, (maxY - minY) * 0.12);
    minY -= margin;
    maxY += margin;
    const minX = valid[0].elapsed_s;
    const maxX = Math.max(valid.at(-1).elapsed_s, minX + 0.1);
    const x = value => pad.left + (value - minX) / (maxX - minX) * (width - pad.left - pad.right);
    const y = value => pad.top + (maxY - value) / (maxY - minY) * (height - pad.top - pad.bottom);

    context.strokeStyle = "#d5e5dc";
    context.lineWidth = 1;
    for (let index = 0; index <= 5; index++) {
        const py = pad.top + index / 5 * (height - pad.top - pad.bottom);
        context.beginPath(); context.moveTo(pad.left, py); context.lineTo(width - pad.right, py); context.stroke();
        context.fillStyle = "#63756d"; context.textAlign = "right";
        context.fillText((maxY - index / 5 * (maxY - minY)).toFixed(1), pad.left - 8, py + 4);
    }
    drawPhases(context, valid, x, pad, height);
    drawSeries(context, valid, "radest_distance_m", x, y, "#008143");
    drawSeries(context, valid, "vehicle_distance_m", x, y, "#d58a00");
    context.textAlign = "left"; context.fillStyle = "#008143"; context.fillText("— RadEsT", pad.left, 18);
    context.fillStyle = "#d58a00"; context.fillText("— Fahrzeug", pad.left + 90, 18);
    context.fillStyle = "#63756d"; context.fillText(minX.toFixed(1) + " s", pad.left, height - 12);
    context.textAlign = "right"; context.fillText(maxX.toFixed(1) + " s", width - pad.right, height - 12);
    context.save(); context.translate(14, height / 2); context.rotate(-Math.PI / 2);
    context.textAlign = "center"; context.fillText("Distanz [m]", 0, 0); context.restore();
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
        if (started) context.lineTo(x(point.elapsed_s), y(point[key]));
        else context.moveTo(x(point.elapsed_s), y(point[key]));
        started = true;
    }
    context.stroke();
}

function drawPhases(context, points, x, pad, height) {
    const labels = {pre_hold: "Halten Start", moving: "Bewegung", post_hold: "Halten Ende"};
    let previous = null;
    for (const point of points) {
        if (!point.phase || point.phase === previous) continue;
        const px = x(point.elapsed_s);
        if (previous !== null) {
            context.save(); context.setLineDash([4, 4]); context.strokeStyle = "#9cb3a8";
            context.beginPath(); context.moveTo(px, pad.top); context.lineTo(px, height - pad.bottom); context.stroke(); context.restore();
        }
        context.fillStyle = "#63756d"; context.font = "11px Arial"; context.textAlign = "left";
        context.fillText(labels[point.phase] || point.phase, Math.min(px + 4, context.canvas.clientWidth - 90), pad.top + 13);
        previous = point.phase;
    }
}

async function restoreFromLocation() {
    const parameters = new URLSearchParams(location.search);
    const runId = parameters.get("run");
    const testId = parameters.get("test");
    if (!runId) {
        showView("resultsOverview");
        return;
    }
    await openRun(runId, false);
    if (testId) await openMeasurement(runId, testId, false);
}

$("reloadResults").addEventListener("click", loadResults);
$("resultSearch").addEventListener("input", renderResults);
$("resultStatusFilter").addEventListener("change", renderResults);
$("resultTypeFilter").addEventListener("change", renderResults);
$("backToResults").addEventListener("click", () => { showView("resultsOverview"); setLocation(); });
$("backToResultsFromMeasurement").addEventListener("click", () => { showView("resultsOverview"); setLocation(); });
$("backToRun").addEventListener("click", () => { showView("runDetail"); setLocation(resultState.currentRun.summary.run_id); });
window.addEventListener("popstate", restoreFromLocation);
window.addEventListener("resize", () => {
    if (!$("measurementDetail").hidden && resultState.currentMeasurement) {
        drawArchiveChart(resultState.currentMeasurement.points || []);
    }
});

loadResults().then(restoreFromLocation);
