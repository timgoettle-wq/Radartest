"use strict";

let state = null;
let selectedVehicleId = Number(new URLSearchParams(location.search).get("vehicle")) || null;
let activeTab = "vehicle";
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
  manufacturer:{label:"Hersteller"}, model:{label:"Modell"}, generation:{label:"Baureihe"},
  year_from:{label:"Baujahr von"}, year_to:{label:"Baujahr bis"}, description:{label:"Beschreibung", textarea:true},
  name:{label:"Bezeichnung"}, interface:{label:"Schnittstelle", choices:[["can","CAN"]]},
  channel:{label:"CAN-Kanal"}, bitrate:{label:"Bitrate [bit/s]"}, request_id:{label:"CAN Request-ID"},
  response_id:{label:"CAN Response-ID"}, transport:{label:"Transport", choices:[["isotp","ISO-TP"]]},
  tx_padding:{label:"TX-Padding"}, identifier_key:{label:"Interner Schlüssel"}, label:{label:"Anzeigename"},
  ecu_id:{label:"Radarsensor"}, vehicle_id:{label:"Fahrzeug"}, parameter_id:{label:"Diagnoseparameter"},
  identification_parameter_id:{label:"Identifikationsmerkmal"},
  service:{label:"SID / Service"}, did:{label:"DID / PID"}, byte_offset:{label:"Byte-Offset"},
  byte_length:{label:"Byte-Länge"}, data_type:{label:"Datentyp"}, required:{label:"Pflichtwert", boolean:true},
  enabled:{label:"Aktiv", boolean:true}, value:{label:"Zulässiger Referenzwert"}, note:{label:"Notiz / Quelle", textarea:true},
  subfunction:{label:"Subfunktion"}, status_mask:{label:"Statusmaske"}, factor:{label:"Skalierung / Faktor"},
  value_offset:{label:"Wert-Offset"}, unit:{label:"Einheit"}
};

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

function years(vehicle) {
  if (!vehicle.year_from && !vehicle.year_to) return "Baujahr nicht angegeben";
  return [vehicle.year_from || "…", vehicle.year_to || "heute"].join(" – ");
}

function vehicleName(vehicle) {
  return [vehicle.manufacturer, vehicle.model, vehicle.generation].filter(Boolean).join(" ");
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
    const text = [vehicle.manufacturer, vehicle.model, vehicle.generation, vehicle.description].join(" ").toLowerCase();
    const yearMatches = !year || ((!vehicle.year_from || vehicle.year_from <= year) && (!vehicle.year_to || vehicle.year_to >= year));
    return (!query || text.includes(query)) && (!manufacturer || vehicle.manufacturer === manufacturer) && yearMatches;
  }).sort((left, right) =>
    compareText(left.manufacturer, right.manufacturer)
    || compareText(left.model, right.model)
    || compareText(left.generation, right.generation)
    || Number(left.id) - Number(right.id)
  );
  $("emptyVehicles").hidden = vehicles.length > 0;
  $("vehicleList").innerHTML = vehicles.map(vehicle => {
    return `<tr class="vehicle-table-row clickable-table-row" data-open-vehicle="${vehicle.id}" tabindex="0" role="button">
      <td><strong>${esc(vehicle.manufacturer || "—")}</strong></td>
      <td>${esc(vehicle.model || "—")}</td>
      <td>${esc(vehicle.generation || "—")}</td>
      <td>${esc(years(vehicle))}</td>
    </tr>`;
  }).join("");
}

function renderDetail() {
  const vehicle = find("vehicles", selectedVehicleId);
  $("breadcrumbs").innerHTML = `<button class="breadcrumb-link" data-action="back">Browse</button><span>›</span><span>${esc(vehicle.manufacturer)}</span><span>›</span><strong>${esc([vehicle.model, vehicle.generation].filter(Boolean).join(" "))}</strong>`;
  $("pageTitle").textContent = vehicleName(vehicle);
  $("pageSubtitle").textContent = `${related("ecus", "vehicle_id", vehicle.id).length} zugeordnete Radarsensoren · interne Vehicle-ID ${vehicle.id}`;
  $("primaryAction").textContent = activeTab === "sensors" ? "+ Sensor hinzufügen" : activeTab === "diagnosis" ? "+ Diagnoseparameter" : "Fahrzeug bearbeiten";
  $("primaryAction").dataset.action = activeTab === "sensors" ? "newSensor" : activeTab === "diagnosis" ? "newParameter" : "editVehicle";
  $("primaryAction").disabled = state.locked || (activeTab === "diagnosis" && related("ecus", "vehicle_id", vehicle.id).length === 0);
  document.querySelectorAll(".tab").forEach(tab => tab.classList.toggle("active", tab.dataset.tab === activeTab));
  if (activeTab === "vehicle") renderVehicleTab(vehicle);
  if (activeTab === "sensors") renderSensorsTab(vehicle);
  if (activeTab === "diagnosis") renderDiagnosisTab(vehicle);
}

function fact(label, value) {
  return `<div class="fact"><span>${esc(label)}</span><strong>${esc(value ?? "—")}</strong></div>`;
}

function renderVehicleTab(vehicle) {
  $("detailContent").innerHTML = `<div class="section-heading"><div><h2>Fahrzeugdaten</h2><p>Allgemeine Daten des ausgewählten Fahrzeugs.</p></div>${action("Bearbeiten", "editVehicle")}</div>
    <div class="facts-grid">${fact("Hersteller", vehicle.manufacturer)}${fact("Modell", vehicle.model)}${fact("Baureihe", vehicle.generation)}${fact("Baujahr / Modelljahr", years(vehicle))}${fact("Interne Vehicle-ID", vehicle.id)}</div>
    <div class="description-box"><span>Beschreibung</span><p>${esc(vehicle.description || "Keine Beschreibung hinterlegt.")}</p></div>
    <div class="danger-zone"><div><strong>Fahrzeug löschen</strong><p>Nur möglich, wenn keine Sensoren mehr zugeordnet sind.</p></div>${action("Fahrzeug löschen", "deleteVehicle", vehicle.id, "danger")}</div>`;
}

function sensorSummary(sensor) {
  return `${esc(sensor.name)} · ${esc(sensor.channel)} · ${Number(sensor.bitrate).toLocaleString("de-DE")} bit/s`;
}

function renderSensorsTab(vehicle) {
  const sensors = related("ecus", "vehicle_id", vehicle.id);
  const cards = sensors.map(sensor => {
    const identifications = related("identification_parameters", "ecu_id", sensor.id);
    return `<article class="entity-card">
      <div class="entity-header"><div><p class="eyebrow">Radarsensor</p><h2>${esc(sensor.name)}</h2><p>${esc(sensor.channel)} · ${esc(sensor.interface.toUpperCase())} / ${esc(sensor.transport.toUpperCase())}</p></div><div class="button-row">${action("Bearbeiten", "editSensor", sensor.id)}${action("Löschen", "deleteSensor", sensor.id, "danger ghost")}</div></div>
      <div class="compact-facts">${fact("Request", hex(sensor.request_id))}${fact("Response", hex(sensor.response_id))}${fact("Bitrate", `${Number(sensor.bitrate).toLocaleString("de-DE")} bit/s`)}${fact("TX-Padding", sensor.tx_padding === null ? "—" : hex(sensor.tx_padding))}</div>
      <div class="subsection"><div class="section-heading"><div><h3>Hardware- und Softwarestände</h3><p>Auslesbare Identifikationsmerkmale und bekannte Serienwerte.</p></div>${action("+ Kennung", "newIdentification", sensor.id)}</div>
        ${identifications.length ? identifications.map(renderIdentification).join("") : `<p class="empty-inline">Noch keine Identifikationsmerkmale hinterlegt.</p>`}
      </div>
    </article>`;
  }).join("");
  $("detailContent").innerHTML = `<div class="section-heading"><div><h2>Radarsensoren</h2><p>Sensorpositionen, Kommunikation und Versionskennungen.</p></div>${action("+ Sensor hinzufügen", "newSensor")}</div>${cards || `<p class="empty-state">Noch kein Radarsensor angelegt.</p>`}`;
}

function renderIdentification(item) {
  const references = related("accepted_identification_values", "identification_parameter_id", item.id);
  return `<div class="nested-card">
    <div class="nested-main"><div><strong>${esc(item.label)}</strong><span>${esc(item.identifier_key)} · DID ${hex(item.did)} · ${esc(item.data_type)}</span></div><div class="button-row">${action("Bearbeiten", "editIdentification", item.id, "link-button")}${action("Löschen", "deleteIdentification", item.id, "link-button danger-text")}</div></div>
    <div class="reference-list">${references.map(ref => `<div class="reference-row"><div><code>${esc(ref.value)}</code>${ref.note ? `<span>${esc(ref.note)}</span>` : ""}</div><div class="button-row">${action("Bearbeiten", "editReference", ref.id, "link-button")}${action("Löschen", "deleteReference", ref.id, "link-button danger-text")}</div></div>`).join("") || `<span class="muted">Noch kein zulässiger Referenzwert</span>`}</div>
    ${action("+ Referenzwert", "newReference", item.id, "small-button")}
  </div>`;
}

function renderDiagnosisTab(vehicle) {
  const sensors = related("ecus", "vehicle_id", vehicle.id);
  if (!sensors.length) {
    $("detailContent").innerHTML = `<div class="empty-state"><h2>Zuerst einen Radarsensor anlegen</h2><p>Diagnoseparameter werden immer einem Sensor zugeordnet.</p>${action("+ Sensor hinzufügen", "newSensor")}</div>`;
    return;
  }
  $("detailContent").innerHTML = `<div class="section-heading"><div><h2>Diagnose</h2><p>Parameter, Signale und DTC-Abfragen nach Radarsensor.</p></div></div>${sensors.map(sensor => {
    const parameters = related("diagnostic_parameters", "ecu_id", sensor.id);
    const dtcs = related("dtc_config", "ecu_id", sensor.id);
    return `<article class="entity-card">
      <div class="entity-header"><div><p class="eyebrow">${esc(sensor.name)}</p><h2>Diagnoseparameter</h2><p>${sensorSummary(sensor)}</p></div>${action("+ Parameter", "newParameter", sensor.id)}</div>
      ${parameters.length ? parameters.map(renderParameter).join("") : `<p class="empty-inline">Noch keine Diagnoseparameter hinterlegt.</p>`}
      <div class="subsection"><div class="section-heading"><div><h3>DTC-Abfrage</h3><p>Fehlerspeicherabfrage dieses Steuergeräts.</p></div>${action("+ DTC-Abfrage", "newDtc", sensor.id)}</div>
      ${dtcs.map(dtc => `<div class="list-row"><div><strong>Service ${hex(dtc.service)}</strong><span>Subfunktion ${hex(dtc.subfunction)} · Statusmaske ${hex(dtc.status_mask)} · ${dtc.enabled ? "aktiv" : "inaktiv"}</span></div><div class="button-row">${action("Bearbeiten", "editDtc", dtc.id, "link-button")}${action("Löschen", "deleteDtc", dtc.id, "link-button danger-text")}</div></div>`).join("") || `<p class="empty-inline">Keine DTC-Abfrage konfiguriert.</p>`}</div>
    </article>`;
  }).join("")}`;
}

function renderParameter(parameter) {
  const fields = related("signal_fields", "parameter_id", parameter.id);
  return `<div class="nested-card">
    <div class="nested-main"><div><strong>${esc(parameter.name)}</strong><span>SID ${hex(parameter.service)} · DID/PID ${hex(parameter.did)}</span></div><div class="button-row">${action("Bearbeiten", "editParameter", parameter.id, "link-button")}${action("Löschen", "deleteParameter", parameter.id, "link-button danger-text")}</div></div>
    <div class="signal-list">${fields.map(field => `<div class="list-row"><div><strong>${esc(field.name)}</strong><span>Byte ${field.byte_offset}, ${field.byte_length} Byte · ${esc(field.data_type)} · Faktor ${field.factor}${field.unit ? ` · ${esc(field.unit)}` : ""}</span></div><div class="button-row">${action("Bearbeiten", "editField", field.id, "link-button")}${action("Löschen", "deleteField", field.id, "link-button danger-text")}</div></div>`).join("") || `<span class="muted">Noch kein Signalfeld definiert.</span>`}</div>
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
  table.columns.filter(column => column.name !== "id" && !(column.name in fixed)).forEach(column => {
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
    const choices = info.boolean ? [[1,"Ja"],[0,"Nein"]] : info.choices || relationChoices || signalChoices || (column.name === "data_type" ? state.data_types.map(value => [value,value]) : null);
    if (choices) {
      input = document.createElement("select");
      if (!column.notnull) input.add(new Option("Nicht angegeben", ""));
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
    if (state.hex_fields.includes(column.name) && value !== "") value = hex(value);
    input.value = value;
    wrapper.append(caption, input);
    $("editor").append(wrapper);
  });
  $("editorDialog").showModal();
}

async function saveEditor(event) {
  event.preventDefault();
  const {table, row, fixed, kind} = editorState;
  const payload = {...fixed, ...Object.fromEntries(new FormData($("editorForm")))};
  try {
    const result = await request(`/api/database/${table}${row ? "/" + row.id : ""}`, {
      method:row ? "PUT" : "POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)
    });
    if (kind === "vehicle" && !row) {
      selectedVehicleId = Number(result.id);
      history.pushState({}, "", `/database?vehicle=${selectedVehicleId}`);
    }
    $("editorDialog").close();
    await load("Gespeichert. Die Konfiguration wird bei der nächsten Verbindung neu geladen.");
  } catch (error) { message(error.message, true); }
}

async function remove(table, id, label) {
  if (!confirm(`${label} wirklich löschen? Vorher wird eine Datenbanksicherung erstellt.`)) return;
  try {
    await request(`/api/database/${table}/${id}`, {method:"DELETE"});
    if (table === "vehicles") {
      selectedVehicleId = null;
      history.pushState({}, "", "/database");
    }
    await load("Eintrag gelöscht. Eine Sicherung wurde erstellt.");
  } catch (error) { message(error.message, true); }
}

function handleAction(actionName, id) {
  const vehicle = selectedVehicleId ? find("vehicles", selectedVehicleId) : null;
  const actions = {
    back:() => { selectedVehicleId=null; activeTab="vehicle"; history.pushState({},"","/database"); render(); },
    newVehicle:() => openEditor("vehicle"), editVehicle:() => openEditor("vehicle", vehicle),
    deleteVehicle:() => remove("vehicles", id, "Fahrzeug"),
    newSensor:() => openEditor("sensor", null, {vehicle_id:selectedVehicleId}),
    editSensor:() => openEditor("sensor", find("ecus", id), {vehicle_id:selectedVehicleId}),
    deleteSensor:() => remove("ecus", id, "Radarsensor"),
    newIdentification:() => openEditor("identification", null, {ecu_id:id}),
    editIdentification:() => { const row=find("identification_parameters",id); openEditor("identification",row,{ecu_id:row.ecu_id}); },
    deleteIdentification:() => remove("identification_parameters",id,"Kennung"),
    newReference:() => openEditor("reference",null,{identification_parameter_id:id}),
    editReference:() => { const row=find("accepted_identification_values",id); openEditor("reference",row,{identification_parameter_id:row.identification_parameter_id}); },
    deleteReference:() => remove("accepted_identification_values",id,"Referenzwert"),
    newParameter:() => id ? openEditor("parameter",null,{ecu_id:id}) : openEditor("parameter"),
    editParameter:() => { const row=find("diagnostic_parameters",id); openEditor("parameter",row,{ecu_id:row.ecu_id}); },
    deleteParameter:() => remove("diagnostic_parameters",id,"Diagnoseparameter"),
    newField:() => openEditor("field",null,{parameter_id:id}),
    editField:() => { const row=find("signal_fields",id); openEditor("field",row,{parameter_id:row.parameter_id}); },
    deleteField:() => remove("signal_fields",id,"Signalfeld"),
    newDtc:() => openEditor("dtc",null,{ecu_id:id}),
    editDtc:() => { const row=find("dtc_config",id); openEditor("dtc",row,{ecu_id:row.ecu_id}); },
    deleteDtc:() => remove("dtc_config",id,"DTC-Abfrage")
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
document.addEventListener("keydown", event => {
  const card = event.target.closest("[data-open-vehicle]");
  if (card && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); card.click(); }
});
document.querySelectorAll(".tab").forEach(tab => tab.onclick = () => { activeTab=tab.dataset.tab; renderDetail(); document.querySelectorAll("button[data-action]").forEach(button => button.disabled=state.locked); });
[$("search"), $("yearFilter")].forEach(input => input.addEventListener("input", renderVehicleList));
$("manufacturerFilter").onchange = renderVehicleList;
$("reload").onclick = () => load();
$("editorForm").onsubmit = saveEditor;
$("cancelDialog").onclick = $("closeDialog").onclick = () => $("editorDialog").close();
window.onpopstate = () => { selectedVehicleId=Number(new URLSearchParams(location.search).get("vehicle")) || null; render(); };

load();
