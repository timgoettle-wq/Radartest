"""Small, allowlisted configuration editor. Never exposes arbitrary SQL."""
import sqlite3
import math
from datetime import datetime, timezone
from contextlib import closing
from fastapi import APIRouter, HTTPException
from database.database import get_connection, DB_PATH

TABLES = {
    "vehicles": ("Fahrzeuge", {}),
    "ecus": ("Steuergeräte", {"vehicle_id": "vehicles"}),
    "diagnostic_parameters": ("Messparameter", {"ecu_id": "ecus"}),
    "signal_fields": ("Signalfelder", {"parameter_id": "diagnostic_parameters"}),
    "dtc_config": ("DTC-Konfiguration", {"ecu_id": "ecus"}),
    "identification_parameters": ("HW-/SW-Kennungen", {"ecu_id": "ecus"}),
    "accepted_identification_values": ("Referenzwerte", {"identification_parameter_id": "identification_parameters"}),
}
TYPES = {"uint8": 1, "int8": 1, "uint16_be": 2, "uint16_le": 2,
         "int16_be": 2, "int16_le": 2, "float32_be": 4, "float32_le": 4,
         "ascii": None, "hex": None, "version_triplet": 3}
HEX_FIELDS = {"did", "service", "request_id", "response_id", "subfunction",
              "status_mask", "tx_padding"}
SIGNAL_NAMES = {
    "status",
    "distance",
    "angle",
    "relative_speed",
    "relative_acceleration",
}


def columns(connection, table):
    if table not in TABLES:
        raise HTTPException(404, "Unbekannte Tabelle")
    return [dict(row) for row in connection.execute(f"PRAGMA table_info({table})")]


def validate(connection, table, payload):
    fields = columns(connection, table)
    allowed = {field["name"] for field in fields} - {"id"}
    if set(payload) != allowed:
        raise ValueError("Bitte alle Formularfelder übergeben; IDs sind unveränderlich.")
    result = {}
    for field in fields:
        name = field["name"]
        if name == "id":
            continue
        value = payload[name]
        if value == "" or value is None:
            if field["notnull"]:
                raise ValueError(f"{name} ist erforderlich")
            result[name] = None
            continue
        kind = field["type"].upper()
        if kind == "INTEGER":
            text = str(value).strip()
            value = int(text, 16 if text.lower().startswith("0x") else 10)
        elif kind == "REAL":
            value = float(value)
            if not math.isfinite(value):
                raise ValueError(f"{name}: ungültige Zahl")
        else:
            value = str(value).strip()
        result[name] = value
    for name, value in result.items():
        if value is None:
            continue
        if name in {"enabled", "required"} and value not in (0, 1):
            raise ValueError(f"{name}: nur 0 oder 1")
        limits = {"did": 65535, "service": 255, "subfunction": 255,
                  "status_mask": 255, "tx_padding": 255,
                  "request_id": 0x7FF, "response_id": 0x7FF}
        if name in limits and not 0 <= value <= limits[name]:
            raise ValueError(f"{name}: außerhalb des unterstützten Bereichs")
        if name in {"byte_offset", "byte_length", "bitrate"} and value < (0 if name == "byte_offset" else 1):
            raise ValueError(f"{name}: ungültiger Wert")
    if "data_type" in result:
        kind = result["data_type"]
        if kind not in TYPES:
            raise ValueError("Unbekannter Datentyp")
        expected = TYPES[kind]
        if expected and result["byte_length"] != expected:
            raise ValueError(f"{kind} benötigt {expected} Byte")
    if table == "ecus" and (result["transport"] != "isotp" or result["interface"] != "can"):
        raise ValueError("Aktuell werden CAN und ISO-TP unterstützt")
    if table == "identification_parameters" and result["service"] != 34:
        raise ValueError("Identifikation unterstützt nur ReadDataByIdentifier (0x22)")
    if table == "signal_fields" and result["name"] not in SIGNAL_NAMES:
        raise ValueError("Unbekannter standardisierter Signalname")
    return result


def backup(connection):
    folder = DB_PATH.parent / "backups"
    folder.mkdir(exist_ok=True)
    path = folder / (datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f") + ".db")
    with closing(sqlite3.connect(path)) as target:
        connection.backup(target)


def make_database_router(lock, connected):
    router = APIRouter(prefix="/api/database", tags=["Datenpflege"])

    @router.get("")
    def overview():
        with lock, closing(get_connection()) as connection:
            return {
                "locked": connected(),
                "tables": {name: {
                    "label": label, "foreign_keys": foreign_keys,
                    "columns": columns(connection, name),
                    "rows": [dict(row) for row in connection.execute(f"SELECT * FROM {name} ORDER BY id")],
                } for name, (label, foreign_keys) in TABLES.items()},
                "hex_fields": sorted(HEX_FIELDS),
                "data_types": list(TYPES),
                "signal_names": sorted(SIGNAL_NAMES),
            }

    def write(table, payload=None, row_id=None, delete=False):
        with lock:
            if connected():
                raise HTTPException(409, "Zuerst Testsystem trennen, dann Konfiguration bearbeiten.")
            with closing(get_connection()) as connection:
                columns(connection, table)
                try:
                    if row_id is not None and not connection.execute(
                        f"SELECT id FROM {table} WHERE id = ?", (row_id,)
                    ).fetchone():
                        raise HTTPException(404, "Datensatz nicht gefunden")
                    values = None if delete else validate(connection, table, payload)
                    if delete:
                        for child, (_, keys) in TABLES.items():
                            for key, parent in keys.items():
                                if parent == table and connection.execute(
                                    f"SELECT 1 FROM {child} WHERE {key} = ? LIMIT 1", (row_id,)
                                ).fetchone():
                                    raise ValueError(f"Zuerst abhängige Einträge in {TABLES[child][0]} entfernen.")
                    backup(connection)
                    saved_id = row_id
                    with connection:
                        if delete:
                            connection.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
                        elif row_id is None:
                            keys = list(values)
                            cursor = connection.execute(
                                f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",
                                list(values.values()))
                            saved_id = cursor.lastrowid
                        else:
                            connection.execute(
                                f"UPDATE {table} SET {','.join(key + ' = ?' for key in values)} WHERE id = ?",
                                [*values.values(), row_id])
                    return {"ok": True, "id": saved_id}
                except (ValueError, TypeError, sqlite3.IntegrityError) as error:
                    raise HTTPException(422, str(error)) from error

    @router.post("/{table}")
    def create(table: str, payload: dict):
        return write(table, payload)

    @router.put("/{table}/{row_id}")
    def update(table: str, row_id: int, payload: dict):
        return write(table, payload, row_id)

    @router.delete("/{table}/{row_id}")
    def delete(table: str, row_id: int):
        return write(table, row_id=row_id, delete=True)

    return router
