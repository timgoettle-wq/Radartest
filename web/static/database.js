"use strict";
let state, editingId = null;
const $ = id => document.getElementById(id);
const labels = {
  manufacturer:"Hersteller", model:"Modell", generation:"Baureihe",
  year_from:"Baujahr von", year_to:"Baujahr bis", description:"Beschreibung",
  ecu_id:"Steuergerät", vehicle_id:"Fahrzeug", name:"Name",
  identifier_key:"Eindeutiger Schlüssel", label:"Anzeigename",
  byte_offset:"Byte-Offset", byte_length:"Byte-Länge", data_type:"Datentyp",
  required:"Erforderlich (Kennzeichnung)", enabled:"Aktiv", value:"Referenzwert",
  note:"Notiz / Quelle", service:"Service", did:"DID",
  request_id:"CAN Request-ID", response_id:"CAN Response-ID", tx_padding:"TX-Padding",
  parameter_id:"Messparameter", identification_parameter_id:"Identifikationsparameter",
  channel:"CAN-Kanal", bitrate:"Bitrate", interface:"Schnittstelle",
  transport:"Transport", factor:"Faktor", value_offset:"Wert-Offset", unit:"Einheit",
  subfunction:"Subfunktion", status_mask:"Statusmaske"
};
async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
  return data;
}
function message(text) { $("message").textContent = text; }
function display(value, key) {
  return value === null ? "—" : state.hex_fields.includes(key)
    ? "0x" + Number(value).toString(16).toUpperCase() : String(value);
}
function description(row) {
  return [row.id, row.manufacturer, row.model, row.label || row.name || row.identifier_key].filter(v => v !== undefined && v !== null).join(" · ");
}
async function load() {
  try {
    const previous = $("table").value;
    state = await request("/api/database");
    $("table").replaceChildren();
    for (const [key, table] of Object.entries(state.tables)) {
      $("table").add(new Option(table.label, key));
    }
    if (previous) $("table").value = previous;
    $("new").disabled = state.locked;
    $("editSection").hidden = true;
    message(state.locked ? "Nur Ansicht: Zum Bearbeiten zuerst das Testsystem trennen." : "Bereit. Änderungen werden vorab gesichert.");
    render();
  } catch (error) { message(error.message); }
}
function render() {
  const table = state.tables[$("table").value];
  const target = $("rows");
  target.replaceChildren();
  const head = target.createTHead().insertRow();
  for (const col of table.columns) {
    const th = document.createElement("th"); th.textContent = labels[col.name] || col.name; head.append(th);
  }
  head.append(document.createElement("th"));
  for (const row of table.rows) {
    const tr = target.insertRow();
    for (const col of table.columns) {
      const parent = table.foreign_keys[col.name];
      const referenced = parent && state.tables[parent].rows.find(item => item.id === row[col.name]);
      tr.insertCell().textContent = referenced ? description(referenced) : display(row[col.name], col.name);
    }
    const actions = tr.insertCell();
    for (const [text, action] of [
      ["Bearbeiten", () => edit(row)],
      ["Kopieren", () => edit(row, true)],
      ["Löschen", () => remove(row)]
    ]) {
      const button = document.createElement("button");
      button.textContent = text; button.disabled = state.locked;
      button.onclick = action; actions.append(button);
    }
  }
}
function edit(row = {}, copy = false) {
  editingId = copy ? null : (row.id ?? null);
  $("editTitle").textContent = editingId === null ? "Neuer Eintrag" : "Eintrag #" + editingId;
  const table = state.tables[$("table").value];
  $("editor").replaceChildren();
  for (const col of table.columns.filter(col => col.name !== "id")) {
    const label = document.createElement("label");
    label.textContent = (labels[col.name] || col.name) + (col.notnull ? " *" : "");
    let input;
    const parent = table.foreign_keys[col.name];
    const choices = parent ? state.tables[parent].rows.map(r => [r.id, description(r)])
      : col.name === "data_type" ? state.data_types.map(t => [t,t])
      : ["required","enabled"].includes(col.name) ? [[0,"Nein"],[1,"Ja"]] : null;
    if (choices) {
      input = document.createElement("select"); input.add(new Option("Bitte wählen", ""));
      choices.forEach(([value,text]) => input.add(new Option(text,value)));
    } else { input = document.createElement("input"); input.type = "text"; }
    input.name = col.name; input.required = Boolean(col.notnull);
    const fallback = col.dflt_value === null ? "" : String(col.dflt_value).replace(/^'|'$/g,"");
    const value = row[col.name] ?? fallback;
    input.value = state.hex_fields.includes(col.name) && value !== "" ? display(value,col.name) : value;
    label.append(input); $("editor").append(label);
  }
  $("editSection").hidden = false;
  $("editSection").scrollIntoView({behavior:"smooth"});
}
async function remove(row) {
  if (!confirm("Eintrag #" + row.id + " löschen? Vorher wird eine Datenbanksicherung angelegt.")) return;
  try {
    await request("/api/database/" + $("table").value + "/" + row.id, {method:"DELETE"});
    await load(); message("Eintrag gelöscht. Sicherung wurde erstellt.");
  } catch(error) { message(error.message); }
}
$("form").onsubmit = async event => {
  event.preventDefault();
  try {
    const payload = Object.fromEntries(new FormData($("form")));
    await request("/api/database/" + $("table").value + (editingId === null ? "" : "/" + editingId), {
      method: editingId === null ? "POST" : "PUT",
      headers: {"Content-Type":"application/json"}, body:JSON.stringify(payload)
    });
    await load(); message("Gespeichert. Bei der nächsten Verbindung wird die Konfiguration neu geladen.");
  } catch(error) { message(error.message); }
};
$("table").onchange = () => { $("editSection").hidden = true; render(); };
$("new").onclick = () => edit();
$("reload").onclick = load;
$("cancel").onclick = () => { $("editSection").hidden = true; };
load();
