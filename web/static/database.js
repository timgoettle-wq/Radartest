"use strict";

let state = null;
let selectedVehicleId = Number(new URLSearchParams(location.search).get("vehicle")) || null;
let selectedSensorId = null;
let editorState = null;

const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[char]);
const rows = table => state.tables[table].rows;
const find = (table, id) => rows(table).find(row => row.id === Number(id));
const related = (table, key, id) => rows(table).filter(row => row[key] === Number(id));
const textCollator = new Intl.Collator("de", {sensitivity:"base", numeric:true});

function textGroup(value) {
  const firstCharacter = String(value ?? "").trim().charAt(0);
  if (!firstCharacter) return 3;
  if (/^\p{L}$/u.test(firstCharacter)) return 0;
  if (/^\p{N}$/u.test(firstCharacter)) return 1;
  return 2;
}

function compareText(left, right) {
  return textGroup(left) - textGroup(right)
    || textCollator.compare(String(left ?? ""), String(right ?? ""));
}

const FIELD_INFO = {
  manufacturer:{label:"Hersteller"}, model:{label:"Modell"}, variant:{label:"Variante"}, generation:{label:"Baureihe"},
  hsn:{label:"HSN (Feld 2.1, 4 Ziffern)"}, tsn:{label:"TSN (Feld 2.2, erste 3 Zeichen)"},
  year_from:{label:"Baujahr von"}, year_to:{label:"Baujahr bis"}, description:{label:"Beschreibung", textarea:true},
  name:{label:"Bezeichnung"}, interface:{label:"Schnittstelle", choices:[["can","CAN"]]},
  channel:{label:"CAN-Kanal"}, bitrate:{label:"Bitrate [bit/s]", choices:[[125000,"125.000"],[250000,"250.000"],[500000,"500.000"],[1000000,"1.000.000"]]}, request_id:{label:"CAN Request-ID"},
  response_id:{label:"CAN Response-ID"}, transport:{label:"Transport", choices:[["isotp","ISO-TP"]]},
  tx_padding:{label:"TX-Padding"}, identifier_key:{label:"Interner Schlüssel"}, label:{label:"Bezeichnung"},
  ecu_id:{label:"Radarsensor"}, vehicle_id:{label:"Fahrzeug"}, parameter_id:{label:"Diagnoseparameter"},
  identification_parameter_id:{label:"Identifikationsmerkmal"},
  service:{label:"SID / Service"}, did:{label:"DID / PID"}, byte_offset:{label:"Byte-Offset"},
  byte_length:{label:"Byte-Länge"}, data_type:{label:"Datentyp"}, required:{label:"Pflichtwert", boolean:true},
  enabled:{label:"Aktiv", boolean:true}, value:{label:"Zulässiger Referenzwert"}, note:{label:"Notiz / Quelle", textarea:true},
  subfunction:{label:"Subfunktion"}, status_mask:{label:"Statusmaske"}, factor:{label:"Skalierung / Faktor"},
  value_offset:{label:"Wert-Offset"}, unit:{label:"Einheit"}
};

// Reihenfolge der Eingabefelder, unabhängig von der Spaltenreihenfolge in der DB.
const COLUMN_ORDER = {
  vehicles:["manufacturer", "model", "variant", "generation", "year_from", "year_to", "description"],
  vehicle_key_numbers:["hsn", "tsn"]
};

function orderedColumns(tableName, columns) {
  const order = COLUMN_ORDER[tableName];
  if (!order) return columns;
  const rank = name => { const index = order.indexOf(name); return index < 0 ? order.length : index; };
  return [...columns].sort((left, right) => rank(left.name) - rank(right.name));
}

// HSN/TSN-Paare als normale Kacheln; bearbeitet werden sie im Fahrzeugdialog.
function renderKeyNumbers(vehicle) {
  const keys = related("vehicle_key_numbers", "vehicle_id", vehicle.id);
  if (!keys.length) return fact("HSN / TSN", null);
  return keys.map(key => fact("HSN / TSN", `${key.hsn} / ${key.tsn}`)).join("");
}

function keyNumberRow(hsn="", tsn="") {
  const row = document.createElement("div");
  row.className = "key-number-row";
  row.innerHTML = `<input class="key-hsn" type="text" inputmode="numeric" maxlength="4" placeholder="HSN" aria-label="HSN" value="${esc(hsn)}">
    <span aria-hidden="true">/</span>
    <input class="key-tsn" type="text" maxlength="3" placeholder="TSN" aria-label="TSN" value="${esc(tsn)}">
    <button type="button" class="link-button danger-text" title="Entfernen" aria-label="HSN/TSN entfernen">Entfernen</button>`;
  row.querySelector("button").onclick = () => row.remove();
  return row;
}

function keyNumberEditor(vehicle) {
  const wrapper = document.createElement("div");
  wrapper.className = "wide key-number-editor";
  wrapper.innerHTML = `<span>HSN / TSN</span><div class="key-number-rows"></div>`;
  const rows = wrapper.querySelector(".key-number-rows");
  const keys = vehicle ? related("vehicle_key_numbers", "vehicle_id", vehicle.id) : [];
  keys.forEach(key => rows.append(keyNumberRow(key.hsn, key.tsn)));
  if (!keys.length) rows.append(keyNumberRow());
  const add = document.createElement("button");
  add.type = "button";
  add.className = "small-button";
  add.textContent = "+ HSN/TSN";
  add.onclick = () => { const row = keyNumberRow(); rows.append(row); row.querySelector("input").focus(); };
  wrapper.append(add);
  return wrapper;
}

const DIALOG_DELETE_KINDS = ["identification", "reference", "parameter", "field", "dtc"];

const EDITORS = {
  vehicle:{table:"vehicles", title:"Fahrzeug", context:"Fahrzeugdaten"},
  sensor:{table:"ecus", title:"Radarsensor", context:"Sensor und Kommunikation"},
  identification:{table:"identification_parameters", title:"Hardware-/Softwarekennung", context:"Identifikation"},
  reference:{table:"accepted_identification_values", title:"Referenzwert", context:"Serienstand"},
  parameter:{table:"diagnostic_parameters", title:"Diagnoseparameter", context:"Diagnose"},
  field:{table:"signal_fields", title:"Signalfeld", context:"Signalauswertung"},
  dtc:{table:"dtc_config", title:"DTC-Abfrage", context:"Diagnose"}
};

const SIGNAL_LABELS = {
  status:"Status",
  distance:"Abstand",
  angle:"Winkel",
  relative_speed:"Relativgeschwindigkeit",
  relative_acceleration:"Relativbeschleunigung"
};

const SENSOR_NAMES = [
  "Frontradar Mitte",
  "Frontradar links",
  "Frontradar rechts",
  "Seitenradar links",
  "Seitenradar rechts",
  "Heckradar Mitte",
  "Heckradar links",
  "Heckradar rechts"
];

const IDENTIFICATION_TYPES = {
  hardware_number:"Hardwarenummer",
  software_number:"Softwarenummer",
  calibration_version:"Kalibrierungsstand",
  part_number:"Teilenummer",
  serial_number:"Seriennummer",
  ecu_version:"Steuergeräteversion"
};

async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
  return data;
}

function message(text, error=false) {
  $("message").textContent = text;
  $("message").classList.toggle("error", error);
}

function hex(value) {
  return value === null || value === undefined ? "—" : "0x" + Number(value).toString(16).toUpperCase();
}

function parseFormInteger(value) {
  const text = String(value).trim();
  return Number.parseInt(text, text.toLowerCase().startsWith("0x") ? 16 : 10);
}

function diagnosticParameterKey(service, did) {
  const serviceHex = parseFormInteger(service).toString(16).toUpperCase().padStart(2, "0");
  const didHex = parseFormInteger(did).toString(16).toUpperCase().padStart(4, "0");
  return `diagnostic_${serviceHex}_${didHex}`;
}

function years(vehicle) {
  if (!vehicle.year_from && !vehicle.year_to) return "Baujahr nicht angegeben";
  return [vehicle.year_from || "…", vehicle.year_to || "heute"].join(" – ");
}

function vehicleName(vehicle) {
  return [vehicle.manufacturer, vehicle.model, vehicle.variant, vehicle.generation].filter(Boolean).join(" ");
}

function action(label, name, id=null, style="secondary") {
  return `<button class="${style}" data-action="${name}"${id === null ? "" : ` data-id="${Number(id)}"`}>${esc(label)}</button>`;
}

async function load(successMessage="") {
  try {
    state = await request("/api/database");
    fillManufacturerFilter();
    if (selectedVehicleId && !find("vehicles", selectedVehicleId)) {
      selectedVehicleId = null;
      history.replaceState({}, "", "/database");
    }
    render();
    message(successMessage || (state.locked ? "Nur Ansicht: Zum Bearbeiten zuerst das Testsystem trennen." : ""));
  } catch (error) {
    message(error.message, true);
  }
}

function fillManufacturerFilter() {
  const select = $("manufacturerFilter");
  const current = select.value;
  const manufacturers = [...new Set(rows("vehicles").map(v => v.manufacturer).filter(Boolean))].sort(compareText);
  select.replaceChildren(new Option("Alle Hersteller", ""));
  manufacturers.forEach(value => select.add(new Option(value, value)));
  select.value = manufacturers.includes(current) ? current : "";
}

function render() {
  $("vehicleOverview").hidden = Boolean(selectedVehicleId);
  $("vehicleDetail").hidden = !selectedVehicleId;
  if (selectedVehicleId) renderDetail(); else renderOverview();
  document.querySelectorAll("button[data-action]").forEach(button => button.disabled = state.locked);
}

function renderOverview() {
  $("breadcrumbs").textContent = "";
  $("pageTitle").textContent = "Fahrzeuge";
  $("pageSubtitle").textContent = `${rows("vehicles").length} Fahrzeuge in der Datenbank`;
  $("primaryAction").textContent = "+ Fahrzeug anlegen";
  $("primaryAction").disabled = state.locked;
  $("primaryAction").dataset.action = "newVehicle";
  renderVehicleList();
}

function renderVehicleList() {
  const query = $("search").value.trim().toLowerCase();
  const manufacturer = $("manufacturerFilter").value;
  const year = Number($("yearFilter").value) || null;
  const vehicles = rows("vehicles").filter(vehicle => {
    const text = [vehicle.manufacturer, vehicle.model, vehicle.variant, vehicle.generation, vehicle.description,
      ...related("vehicle_key_numbers", "vehicle_id", vehicle.id).flatMap(key => [key.hsn, key.tsn])].join(" ").toLowerCase();
    const yearMatches = !year || ((!vehicle.year_from || vehicle.year_from <= year) && (!vehicle.year_to || vehicle.year_to >= year));
    return (!query || text.includes(query)) && (!manufacturer || vehicle.manufacturer === manufacturer) && yearMatches;
  }).sort((left, right) =>
    compareText(left.manufacturer, right.manufacturer)
    || compareText(left.model, right.model)
    || compareText(left.variant, right.variant)
    || compareText(left.generation, right.generation)
    || Number(left.id) - Number(right.id)
  );
  $("emptyVehicles").hidden = vehicles.length > 0;
  $("vehicleList").innerHTML = vehicles.map(vehicle => {
    return `<tr class="vehicle-table-row clickable-table-row" data-open-vehicle="${vehicle.id}" tabindex="0" role="button">
      <td><strong>${esc(vehicle.manufacturer || "—")}</strong></td>
      <td>${esc(vehicle.model || "—")}</td>
      <td>${esc(vehicle.variant || "—")}</td>
      <td>${esc(vehicle.generation || "—")}</td>
      <td>${esc(years(vehicle))}</td>
    </tr>`;
  }).join("");
}

function renderDetail() {
  const vehicle = find("vehicles", selectedVehicleId);
  const sensors = related("ecus", "vehicle_id", vehicle.id);
  if (!sensors.some(sensor => sensor.id === selectedSensorId)) {
    selectedSensorId = sensors[0]?.id || null;
  }
  $("breadcrumbs").innerHTML = `<button class="breadcrumb-link" data-action="back">Datenpflege</button><span>›</span><strong>${esc(vehicleName(vehicle))}</strong>`;
  $("pageTitle").textContent = vehicleName(vehicle);
  $("pageSubtitle").textContent = `${sensors.length} zugeordnete Radarsensoren · interne Vehicle-ID ${vehicle.id}`;
  $("primaryAction").textContent = "Fahrzeug bearbeiten";
  $("primaryAction").dataset.action = "editVehicle";
  $("primaryAction").disabled = state.locked;
  renderVehicleWorkspace(vehicle, sensors);
}

function fact(label, value) {
  return `<div class="fact"><span>${esc(label)}</span><strong>${esc(value ?? "—")}</strong></div>`;
}

function renderVehicleWorkspace(vehicle, sensors) {
  const sensor = sensors.find(item => item.id === selectedSensorId) || null;
  const sensorOptions = sensors.map(item =>
    `<option value="${item.id}"${item.id === selectedSensorId ? " selected" : ""}>${esc(item.name)}</option>`
  ).join("");

  $("detailContent").innerHTML = `
    <section class="vehicle-data-section">
      <div class="section-heading"><div><h2>Fahrzeugdaten</h2><p>Allgemeine Daten des ausgewählten Fahrzeugs.</p></div></div>
      <div class="facts-grid">
        ${fact("Hersteller", vehicle.manufacturer)}
        ${fact("Modell", vehicle.model)}
        ${fact("Variante", vehicle.variant)}
        ${fact("Baureihe", vehicle.generation)}
        ${fact("Baujahr", years(vehicle))}
        ${renderKeyNumbers(vehicle)}
      </div>
      <div class="description-box"><span>Beschreibung</span><p>${esc(vehicle.description || "Keine Beschreibung hinterlegt.")}</p></div>
    </section>

    <section class="sensor-management-section">
      <div class="sensor-selector-row">
        <label class="sensor-selector"><span>Radarsensor auswählen</span>
          <select id="sensorSelector" ${sensors.length ? "" : "disabled"}>
            ${sensors.length ? sensorOptions : '<option value="">Kein Radarsensor vorhanden</option>'}
          </select>
        </label>
        ${action("+ Radarsensor hinzufügen", "newSensor", null, "primary")}
      </div>
      ${sensor ? renderSensorWorkspace(sensor) : '<p class="empty-state">Lege einen Radarsensor an, um Hardware- und Softwarestände, DTC-Abfrage und Diagnosedaten zu konfigurieren.</p>'}
    </section>

    <div class="danger-zone"><div><strong>Fahrzeug löschen</strong><p>Nur möglich, wenn keine Sensoren mehr zugeordnet sind.</p></div>${action("Fahrzeug löschen", "deleteVehicle", vehicle.id, "danger")}</div>`;
}

function renderSensorWorkspace(sensor) {
  const identifications = related("identification_parameters", "ecu_id", sensor.id);
  const dtcs = related("dtc_config", "ecu_id", sensor.id);
  const parameters = related("diagnostic_parameters", "ecu_id", sensor.id);

  return `<article class="entity-card sensor-workspace">
    <div class="entity-header">
      <div><p class="eyebrow">Ausgewählter Radarsensor</p><h2>${esc(sensor.name)}</h2><p>${esc(sensor.channel)} · ${esc(sensor.interface.toUpperCase())} / ${esc(sensor.transport.toUpperCase())}</p></div>
      <div class="button-row">${action("Sensor bearbeiten", "editSensor", sensor.id)}${action("Sensor löschen", "deleteSensor", sensor.id, "danger ghost")}</div>
    </div>
    <div class="compact-facts">
      ${fact("Request", hex(sensor.request_id))}
      ${fact("Response", hex(sensor.response_id))}
      ${fact("Bitrate", `${Number(sensor.bitrate).toLocaleString("de-DE")} bit/s`)}
      ${fact("TX-Padding", sensor.tx_padding === null ? "—" : hex(sensor.tx_padding))}
    </div>

    <div class="subsection">
      <div class="section-heading"><div><h3>Hardware- und Softwarestände</h3><p>Auslesbare Identifikationsmerkmale und bekannte Serienwerte.</p></div>${action("+ Kennung", "newIdentification", sensor.id)}</div>
      ${renderIdentificationSection(identifications)}
    </div>

    <div class="subsection">
      <div class="section-heading"><div><h3>DTC-Abfrage</h3><p>Fehlerspeicherabfrage dieses Radarsensors.</p></div>${action("+ DTC-Abfrage", "newDtc", sensor.id)}</div>
      ${renderDtcSection(dtcs)}
    </div>

    <div class="subsection diagnosis-subsection">
      <div class="section-heading"><div><h3>Diagnosedaten</h3><p>Diagnoseabfragen und zugehörige Signalfelder.</p></div>${action("+ Diagnoseabfrage", "newParameter", sensor.id)}</div>
      ${renderParameterSection(parameters)}
    </div>
  </article>`;
}


// Variantenauswahl (nur für den Vergleich, wird nach Tims Wahl entfernt).
const LAYOUT_VARIANT = new URLSearchParams(location.search).get("layout") || "cards";

function renderIdentificationSection(identifications) {
  if (!identifications.length) return '<p class="empty-inline">Noch keine Identifikationsmerkmale hinterlegt.</p>';
  if (LAYOUT_VARIANT === "table") {
    return `<div class="config-table-wrap"><table class="config-table">
      <thead><tr><th>Kennung</th><th>DID</th><th>Datentyp</th><th>Referenzwerte</th><th><span class="visually-hidden">Aktionen</span></th></tr></thead>
      <tbody>${identifications.map(item => {
        const references = related("accepted_identification_values", "identification_parameter_id", item.id);
        return `<tr>
          <td><strong>${esc(item.label)}</strong></td>
          <td class="mono">${hex(item.did)}</td>
          <td>${esc(item.data_type)}</td>
          <td><div class="reference-values">${references.map(ref => `<button class="reference-value" data-action="editReference" data-id="${Number(ref.id)}" title="Referenzwert bearbeiten"><code>${esc(ref.value)}</code>${ref.note ? `<span>${esc(ref.note)}</span>` : ""}</button>`).join("") || '<span class="muted">Kein Referenzwert</span>'}${action("+ Referenzwert", "newReference", item.id, "link-button add-link")}</div></td>
          <td class="row-action">${action("Bearbeiten", "editIdentification", item.id, "link-button")}</td>
        </tr>`;
      }).join("")}</tbody></table></div>`;
  }
  if (LAYOUT_VARIANT === "values") {
    return `<div class="value-rows">${identifications.map(item => {
      const references = related("accepted_identification_values", "identification_parameter_id", item.id);
      return `<div class="value-row">
        <div class="value-row-values">${references.map(ref => `<button class="reference-value lead" data-action="editReference" data-id="${Number(ref.id)}" title="${esc(ref.note || "Referenzwert bearbeiten")}"><code>${esc(ref.value)}</code></button>`).join("") || '<span class="muted">Kein Referenzwert</span>'}</div>
        <div class="value-row-meta"><strong>${esc(item.label)}</strong><span>DID ${hex(item.did)} · ${esc(item.data_type)}</span></div>
        <div class="value-row-actions">${action("+ Wert", "newReference", item.id, "link-button add-link")}${action("Bearbeiten", "editIdentification", item.id, "link-button")}</div>
      </div>`;
    }).join("")}</div>`;
  }
  if (LAYOUT_VARIANT === "collapsed") {
    return `<div class="disclosure-list">${identifications.map(item => {
      const references = related("accepted_identification_values", "identification_parameter_id", item.id);
      const first = references[0]?.value;
      return `<details class="disclosure-row">
        <summary><strong>${esc(item.label)}</strong><span class="mono">DID ${hex(item.did)}</span><code>${esc(first ?? "–")}</code><span class="muted">${references.length === 1 ? "1 Referenzwert" : `${references.length} Referenzwerte`}</span></summary>
        <div class="disclosure-body">
          <p class="muted">Datentyp ${esc(item.data_type)}</p>
          ${references.map(ref => `<div class="reference-row"><div><code>${esc(ref.value)}</code>${ref.note ? `<span>${esc(ref.note)}</span>` : ""}</div><div class="button-row">${action("Bearbeiten", "editReference", ref.id, "link-button")}</div></div>`).join("")}
          <div class="disclosure-actions">${action("+ Referenzwert", "newReference", item.id, "small-button")}${action("Kennung bearbeiten", "editIdentification", item.id, "link-button")}</div>
        </div>
      </details>`;
    }).join("")}</div>`;
  }
  return identifications.map(renderIdentification).join("");
}

function renderDtcSection(dtcs) {
  if (!dtcs.length) return '<p class="empty-inline">Keine DTC-Abfrage konfiguriert.</p>';
  if (LAYOUT_VARIANT === "table") {
    return `<div class="config-table-wrap"><table class="config-table">
      <thead><tr><th>Service</th><th>Subfunktion</th><th>Statusmaske</th><th>Status</th><th><span class="visually-hidden">Aktionen</span></th></tr></thead>
      <tbody>${dtcs.map(dtc => `<tr><td class="mono"><strong>${hex(dtc.service)}</strong></td><td class="mono">${hex(dtc.subfunction)}</td><td class="mono">${hex(dtc.status_mask)}</td><td>${dtc.enabled ? "aktiv" : "inaktiv"}</td><td class="row-action">${action("Bearbeiten", "editDtc", dtc.id, "link-button")}</td></tr>`).join("")}</tbody></table></div>`;
  }
  if (LAYOUT_VARIANT === "values" || LAYOUT_VARIANT === "collapsed") {
    return `<div class="value-rows">${dtcs.map(dtc => `<div class="value-row">
      <div class="value-row-values"><code class="lead-code">Service ${hex(dtc.service)}</code></div>
      <div class="value-row-meta"><strong>Subfunktion ${hex(dtc.subfunction)}</strong><span>Statusmaske ${hex(dtc.status_mask)} · ${dtc.enabled ? "aktiv" : "inaktiv"}</span></div>
      <div class="value-row-actions">${action("Bearbeiten", "editDtc", dtc.id, "link-button")}</div>
    </div>`).join("")}</div>`;
  }
  return dtcs.map(dtc => `<div class="list-row nested-card dtc-config-card"><div><strong>Service ${hex(dtc.service)}</strong><span>Subfunktion ${hex(dtc.subfunction)} · Statusmaske ${hex(dtc.status_mask)} · ${dtc.enabled ? "aktiv" : "inaktiv"}</span></div><div class="button-row">${action("Bearbeiten", "editDtc", dtc.id, "link-button")}</div></div>`).join("");
}

function renderParameterSection(parameters) {
  if (!parameters.length) return '<p class="empty-inline">Noch keine Diagnoseabfragen hinterlegt.</p>';
  if (LAYOUT_VARIANT === "table") {
    return parameters.map(parameter => {
      const fields = related("signal_fields", "parameter_id", parameter.id);
      return `<div class="parameter-block">
        <div class="parameter-block-head"><strong>Diagnoseabfrage</strong><span class="mono">SID ${hex(parameter.service)} · DID/PID ${hex(parameter.did)}</span>${action("Bearbeiten", "editParameter", parameter.id, "link-button")}</div>
        <div class="config-table-wrap"><table class="config-table">
          <thead><tr><th>Signal</th><th>Byte</th><th>Länge</th><th>Datentyp</th><th>Faktor</th><th>Einheit</th><th><span class="visually-hidden">Aktionen</span></th></tr></thead>
          <tbody>${fields.map(field => `<tr><td class="mono"><strong>${esc(field.name)}</strong></td><td class="mono num">${field.byte_offset}</td><td class="mono num">${field.byte_length}</td><td>${esc(field.data_type)}</td><td class="mono num">${field.factor}</td><td>${esc(field.unit || "–")}</td><td class="row-action">${action("Bearbeiten", "editField", field.id, "link-button")}</td></tr>`).join("") || '<tr><td colspan="7" class="muted">Noch kein Signalfeld definiert.</td></tr>'}</tbody>
        </table></div>
        ${action("+ Signalfeld", "newField", parameter.id, "link-button add-link")}
      </div>`;
    }).join("");
  }
  if (LAYOUT_VARIANT === "values") {
    return parameters.map(parameter => {
      const fields = related("signal_fields", "parameter_id", parameter.id);
      return `<div class="parameter-block">
        <div class="parameter-block-head"><strong>Diagnoseabfrage</strong><span class="mono">SID ${hex(parameter.service)} · DID/PID ${hex(parameter.did)}</span>${action("Bearbeiten", "editParameter", parameter.id, "link-button")}</div>
        <div class="signal-grid">${fields.map(field => `<button class="signal-tile" data-action="editField" data-id="${Number(field.id)}" title="Signalfeld bearbeiten"><code>${esc(field.name)}</code><span>Byte ${field.byte_length > 1 ? `${field.byte_offset}–${field.byte_offset + field.byte_length - 1}` : field.byte_offset} · ${esc(field.data_type)} · ×${field.factor}${field.unit ? ` ${esc(field.unit)}` : ""}</span></button>`).join("")}</div>
        ${action("+ Signalfeld", "newField", parameter.id, "link-button add-link")}
      </div>`;
    }).join("");
  }
  if (LAYOUT_VARIANT === "collapsed") {
    return `<div class="disclosure-list">${parameters.map(parameter => {
      const fields = related("signal_fields", "parameter_id", parameter.id);
      return `<details class="disclosure-row">
        <summary><strong>Diagnoseabfrage</strong><span class="mono">SID ${hex(parameter.service)} · DID/PID ${hex(parameter.did)}</span><code>${fields.map(field => esc(field.name)).slice(0, 3).join(", ")}${fields.length > 3 ? " …" : ""}</code><span class="muted">${fields.length === 1 ? "1 Signalfeld" : `${fields.length} Signalfelder`}</span></summary>
        <div class="disclosure-body">
          ${fields.map(field => `<div class="list-row"><div><strong>${esc(field.name)}</strong><span>Byte ${field.byte_offset}, ${field.byte_length} Byte · ${esc(field.data_type)} · Faktor ${field.factor}${field.unit ? ` · ${esc(field.unit)}` : ""}</span></div><div class="button-row">${action("Bearbeiten", "editField", field.id, "link-button")}</div></div>`).join("")}
          <div class="disclosure-actions">${action("+ Signalfeld", "newField", parameter.id, "small-button")}${action("Abfrage bearbeiten", "editParameter", parameter.id, "link-button")}</div>
        </div>
      </details>`;
    }).join("")}</div>`;
  }
  return parameters.map(renderParameter).join("");
}

function renderIdentification(item) {
  const references = related("accepted_identification_values", "identification_parameter_id", item.id);
  return `<div class="nested-card">
    <div class="nested-main"><div><strong>${esc(item.label)}</strong><span>DID ${hex(item.did)} · ${esc(item.data_type)}</span></div><div class="button-row">${action("Bearbeiten", "editIdentification", item.id, "link-button")}</div></div>
    <div class="reference-list">${references.map(ref => `<div class="reference-row"><div><code>${esc(ref.value)}</code>${ref.note ? `<span>${esc(ref.note)}</span>` : ""}</div><div class="button-row">${action("Bearbeiten", "editReference", ref.id, "link-button")}</div></div>`).join("") || `<span class="muted">Noch kein zulässiger Referenzwert</span>`}</div>
    ${action("+ Referenzwert", "newReference", item.id, "small-button")}
  </div>`;
}

function renderParameter(parameter) {
  const fields = related("signal_fields", "parameter_id", parameter.id);
  return `<div class="nested-card">
    <div class="nested-main"><div><strong>Diagnoseabfrage</strong><span>SID ${hex(parameter.service)} · DID/PID ${hex(parameter.did)}</span></div><div class="button-row">${action("Bearbeiten", "editParameter", parameter.id, "link-button")}</div></div>
    <div class="signal-list">${fields.map(field => `<div class="list-row"><div><strong>${esc(field.name)}</strong><span>Byte ${field.byte_offset}, ${field.byte_length} Byte · ${esc(field.data_type)} · Faktor ${field.factor}${field.unit ? ` · ${esc(field.unit)}` : ""}</span></div><div class="button-row">${action("Bearbeiten", "editField", field.id, "link-button")}</div></div>`).join("") || `<span class="muted">Noch kein Signalfeld definiert.</span>`}</div>
    ${action("+ Signalfeld", "newField", parameter.id, "small-button")}
  </div>`;
}

function openEditor(kind, row=null, fixed={}) {
  const config = EDITORS[kind];
  editorState = {kind, table:config.table, row, fixed};
  $("dialogContext").textContent = config.context;
  $("dialogTitle").textContent = `${row ? "Bearbeiten" : "Anlegen"}: ${config.title}`;
  $("editor").replaceChildren();
  const table = state.tables[config.table];
  orderedColumns(config.table, table.columns).filter(column => column.name !== "id" && !(column.name in fixed) && !(kind === "identification" && column.name === "identifier_key") && !(kind === "parameter" && column.name === "name")).forEach(column => {
    const info = FIELD_INFO[column.name] || {label:column.name};
    const wrapper = document.createElement("label");
    wrapper.className = info.textarea ? "wide" : "";
    const caption = document.createElement("span");
    caption.textContent = info.label + (column.notnull ? " *" : "");
    let input;
    const relationChoices = column.name === "ecu_id"
      ? related("ecus", "vehicle_id", selectedVehicleId).map(sensor => [sensor.id, sensor.name])
      : null;
    const signalChoices = kind === "field" && column.name === "name"
      ? state.signal_names.map(value => [value, `${SIGNAL_LABELS[value]} (${value})`])
      : null;
    const sensorChoices = kind === "sensor" && column.name === "name"
      ? SENSOR_NAMES.map(value => [value, value])
      : null;
    let identificationChoices = kind === "identification" && column.name === "label"
      ? Object.entries(IDENTIFICATION_TYPES)
      : null;
    if (identificationChoices && row && !IDENTIFICATION_TYPES[row.identifier_key]) {
      identificationChoices = [...identificationChoices, [row.identifier_key, row.label]];
    }
    if (sensorChoices && row && !SENSOR_NAMES.includes(row.name)) {
      sensorChoices.push([row.name, row.name]);
    }
    const choices = info.boolean ? [[1,"Ja"],[0,"Nein"]] : identificationChoices || sensorChoices || info.choices || relationChoices || signalChoices || (column.name === "data_type" ? state.data_types.map(value => [value,value]) : null);
    if (choices) {
      input = document.createElement("select");
      input.add(new Option(column.notnull ? "Bitte auswählen" : "Nicht angegeben", ""));
      if (column.notnull) input.options[0].disabled = true;
      choices.forEach(([value,label]) => input.add(new Option(label,value)));
    } else if (info.textarea) {
      input = document.createElement("textarea"); input.rows = 3;
    } else {
      input = document.createElement("input");
      input.type = column.type.toUpperCase() === "INTEGER" && !state.hex_fields.includes(column.name) ? "number" : column.type.toUpperCase() === "REAL" ? "number" : "text";
      if (column.type.toUpperCase() === "REAL") input.step = "any";
    }
    input.name = column.name;
    input.required = Boolean(column.notnull);
    const fallback = column.dflt_value === null ? "" : String(column.dflt_value).replace(/^'|'$/g, "");
    let value = row?.[column.name] ?? fallback;
    if (!row && kind === "sensor" && column.name === "name") value = SENSOR_NAMES[0];
    if (!row && kind === "sensor" && column.name === "bitrate") value = 500000;
    if (kind === "identification" && column.name === "label" && row) value = row.identifier_key;
    if (state.hex_fields.includes(column.name) && value !== "") value = hex(value);
    input.value = value;
    wrapper.append(caption, input);
    $("editor").append(wrapper);
  });
  if (kind === "vehicle") {
    // HSN/TSN direkt nach Baujahr, vor der Beschreibung.
    const description = $("editor").querySelector('[name="description"]')?.closest("label");
    $("editor").insertBefore(keyNumberEditor(row), description || null);
  }
  // Löschen von Kennungen, Referenzwerten, DTC-Abfragen, Diagnoseabfragen
  // und Signalfeldern liegt im Bearbeiten-Dialog statt neben jeder Zeile.
  $("deleteInDialog").hidden = !(row && DIALOG_DELETE_KINDS.includes(kind));
  $("editorForm").querySelector(":scope > .form-hint").hidden =
    !table.columns.some(column => state.hex_fields.includes(column.name));
  $("editorDialog").showModal();
}

async function saveEditor(event) {
  event.preventDefault();
  const {table, row, fixed, kind} = editorState;
  const payload = {...fixed, ...Object.fromEntries(new FormData($("editorForm")))};
  if (kind === "identification") {
    const identifierKey = payload.label;
    payload.identifier_key = identifierKey;
    payload.label = IDENTIFICATION_TYPES[identifierKey] || row?.label || identifierKey;
  }
  if (kind === "parameter") {
    payload.name = diagnosticParameterKey(payload.service, payload.did);
  }
  if (kind === "vehicle") {
    payload.key_numbers = [...$("editor").querySelectorAll(".key-number-row")].map(item => ({
      hsn:item.querySelector(".key-hsn").value.trim(),
      tsn:item.querySelector(".key-tsn").value.trim()
    })).filter(pair => pair.hsn || pair.tsn);
  }
  try {
    const result = await request(`/api/database/${table}${row ? "/" + row.id : ""}`, {
      method:row ? "PUT" : "POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)
    });
    if (kind === "vehicle" && !row) {
      selectedVehicleId = Number(result.id);
      selectedSensorId = null;
      history.pushState({}, "", `/database?vehicle=${selectedVehicleId}`);
    }
    if (kind === "sensor" && !row) {
      selectedSensorId = Number(result.id);
    }
    $("editorDialog").close();
    await load("Gespeichert. Die Konfiguration wird bei der nächsten Verbindung neu geladen.");
  } catch (error) { message(error.message, true); }
}

async function remove(table, id, label, afterConfirm=null) {
  if (!confirm(`${label} wirklich löschen? Vorher wird eine Datenbanksicherung erstellt.`)) return;
  afterConfirm?.();
  try {
    await request(`/api/database/${table}/${id}`, {method:"DELETE"});
    if (table === "vehicles") {
      selectedVehicleId = null;
      selectedSensorId = null;
      history.pushState({}, "", "/database");
    }
    if (table === "ecus" && selectedSensorId === Number(id)) {
      selectedSensorId = null;
    }
    await load("Eintrag gelöscht. Eine Sicherung wurde erstellt.");
  } catch (error) { message(error.message, true); }
}

function handleAction(actionName, id) {
  const vehicle = selectedVehicleId ? find("vehicles", selectedVehicleId) : null;
  const actions = {
    back:() => { selectedVehicleId=null; selectedSensorId=null; history.pushState({},"","/database"); render(); },
    newVehicle:() => openEditor("vehicle"), editVehicle:() => openEditor("vehicle", vehicle),
    deleteVehicle:() => remove("vehicles", id, "Fahrzeug"),
    newSensor:() => openEditor("sensor", null, {vehicle_id:selectedVehicleId}),
    editSensor:() => openEditor("sensor", find("ecus", id), {vehicle_id:selectedVehicleId}),
    deleteSensor:() => remove("ecus", id, "Radarsensor"),
    newIdentification:() => openEditor("identification", null, {ecu_id:id}),
    editIdentification:() => { const row=find("identification_parameters",id); openEditor("identification",row,{ecu_id:row.ecu_id}); },
    newReference:() => openEditor("reference",null,{identification_parameter_id:id}),
    editReference:() => { const row=find("accepted_identification_values",id); openEditor("reference",row,{identification_parameter_id:row.identification_parameter_id}); },
    newParameter:() => id ? openEditor("parameter",null,{ecu_id:id}) : openEditor("parameter"),
    editParameter:() => { const row=find("diagnostic_parameters",id); openEditor("parameter",row,{ecu_id:row.ecu_id}); },
    newField:() => openEditor("field",null,{parameter_id:id}),
    editField:() => { const row=find("signal_fields",id); openEditor("field",row,{parameter_id:row.parameter_id}); },
    newDtc:() => openEditor("dtc",null,{ecu_id:id}),
    editDtc:() => { const row=find("dtc_config",id); openEditor("dtc",row,{ecu_id:row.ecu_id}); }
  };
  actions[actionName]?.();
}

document.addEventListener("click", event => {
  const actionButton = event.target.closest("[data-action]");
  if (actionButton && !actionButton.disabled) handleAction(actionButton.dataset.action, Number(actionButton.dataset.id) || null);
  const card = event.target.closest("[data-open-vehicle]");
  if (card && !actionButton) {
    selectedVehicleId = Number(card.dataset.openVehicle);
    history.pushState({}, "", `/database?vehicle=${selectedVehicleId}`);
    render();
  }
});
document.addEventListener("change", event => {
  if (event.target.id !== "sensorSelector") return;
  selectedSensorId = Number(event.target.value) || null;
  renderDetail();
  document.querySelectorAll("button[data-action]").forEach(button => button.disabled = state.locked);
});
document.addEventListener("keydown", event => {
  const card = event.target.closest("[data-open-vehicle]");
  if (card && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); card.click(); }
});
[$("search"), $("yearFilter")].forEach(input => input.addEventListener("input", renderVehicleList));
$("manufacturerFilter").onchange = renderVehicleList;
$("reload").onclick = () => load();
$("editorForm").onsubmit = saveEditor;
$("deleteInDialog").onclick = async () => {
  const {table, row, kind} = editorState;
  if (!row || !DIALOG_DELETE_KINDS.includes(kind)) return;
  await remove(table, row.id, EDITORS[kind].title, () => $("editorDialog").close());
};
$("cancelDialog").onclick = $("closeDialog").onclick = () => $("editorDialog").close();
window.onpopstate = () => { selectedVehicleId=Number(new URLSearchParams(location.search).get("vehicle")) || null; selectedSensorId=null; render(); };

load();
