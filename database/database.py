import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).parent / "radar_test.db"


def _ensure_identification_schema(connection):
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS identification_parameters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ecu_id INTEGER NOT NULL,
            identifier_key TEXT NOT NULL,
            label TEXT NOT NULL,
            service INTEGER NOT NULL DEFAULT 34,
            did INTEGER NOT NULL,
            byte_offset INTEGER NOT NULL DEFAULT 3,
            byte_length INTEGER,
            data_type TEXT NOT NULL DEFAULT 'ascii',
            required INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,

            UNIQUE(ecu_id, identifier_key),

            FOREIGN KEY(ecu_id)
                REFERENCES ecus(id)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS accepted_identification_values (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            identification_parameter_id INTEGER NOT NULL,
            value TEXT NOT NULL,
            note TEXT,

            UNIQUE(identification_parameter_id, value),

            FOREIGN KEY(identification_parameter_id)
                REFERENCES identification_parameters(id)
                ON DELETE CASCADE
        );
    """)

    connection.commit()


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    _ensure_identification_schema(connection)

    return connection


def get_vehicles():
    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        "SELECT * FROM vehicles ORDER BY id"
    )

    vehicles = [
        dict(row)
        for row in cursor.fetchall()
    ]

    connection.close()

    return vehicles
    


def get_vehicle(vehicle_id):
    connection = get_connection()

    row = connection.execute("""
        SELECT *
        FROM vehicles
        WHERE id = ?
    """, (
        vehicle_id,
    )).fetchone()

    connection.close()

    if row is None:
        return None

    return dict(row)

def get_dtc_configs(vehicle_id):

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            dtc_config.id AS dtc_config_id,
            dtc_config.ecu_id,
            dtc_config.service,
            dtc_config.subfunction,
            dtc_config.status_mask,
            dtc_config.enabled,

            ecus.name AS ecu_name,
            ecus.interface,
            ecus.transport,
            ecus.channel,
            ecus.bitrate,
            ecus.request_id,
            ecus.response_id,
            ecus.tx_padding

        FROM dtc_config

        JOIN ecus
            ON dtc_config.ecu_id = ecus.id

        WHERE
            ecus.vehicle_id = ?
            AND dtc_config.enabled = 1

        ORDER BY
            dtc_config.id
        """,
        (
            vehicle_id,
        )
    )

    configs = [
        dict(row)
        for row in cursor.fetchall()
    ]

    connection.close()

    return configs


def get_parameters(vehicle_id):
    connection = get_connection()

    rows = connection.execute("""
        SELECT
            dp.id,
            dp.ecu_id,
            dp.name,
            dp.service,
            dp.did,

            e.name AS ecu_name,
            e.interface,
            e.transport,
            e.channel,
            e.bitrate,
            e.request_id,
            e.response_id,
            e.tx_padding

        FROM diagnostic_parameters dp

        JOIN ecus e
            ON dp.ecu_id = e.id

        WHERE e.vehicle_id = ?

        ORDER BY
            e.id,
            dp.id
    """, (
        vehicle_id,
    )).fetchall()

    result = []

    for row in rows:
        parameter = dict(row)

        fields = connection.execute("""
            SELECT *
            FROM signal_fields

            WHERE parameter_id = ?

            ORDER BY byte_offset
        """, (
            parameter["id"],
        )).fetchall()

        parameter["fields"] = [
            {
                "name": field["name"],
                "offset": field["byte_offset"],
                "length": field["byte_length"],
                "type": field["data_type"],
                "factor": field["factor"],
                "value_offset": field["value_offset"],
                "unit": field["unit"]
            }
            for field in fields
        ]

        result.append(parameter)

    connection.close()

    return result


def get_parameter(vehicle_id, parameter_name):
    parameters = get_parameters(vehicle_id)

    for parameter in parameters:
        if parameter["name"] == parameter_name:
            return parameter

    return None


def get_identification_parameters(vehicle_id):
    connection = get_connection()

    rows = connection.execute("""
        SELECT
            ip.id,
            ip.ecu_id,
            ip.identifier_key,
            ip.label,
            ip.service,
            ip.did,
            ip.byte_offset,
            ip.byte_length,
            ip.data_type,
            ip.required,

            e.name AS ecu_name,
            e.interface,
            e.transport,
            e.channel,
            e.bitrate,
            e.request_id,
            e.response_id,
            e.tx_padding

        FROM identification_parameters ip

        JOIN ecus e
            ON ip.ecu_id = e.id

        WHERE
            e.vehicle_id = ?
            AND ip.enabled = 1

        ORDER BY
            e.id,
            ip.id
    """, (
        vehicle_id,
    )).fetchall()

    result = []

    for row in rows:
        parameter = dict(row)

        accepted_rows = connection.execute("""
            SELECT value, note
            FROM accepted_identification_values
            WHERE identification_parameter_id = ?
            ORDER BY id
        """, (
            parameter["id"],
        )).fetchall()

        parameter["accepted_values"] = [
            {
                "value": accepted["value"],
                "note": accepted["note"]
            }
            for accepted in accepted_rows
        ]

        parameter["fields"] = [
            {
                "name": "identification_value",
                "offset": parameter["byte_offset"],
                "length": parameter["byte_length"],
                "type": parameter["data_type"],
                "factor": 1.0,
                "value_offset": 0.0,
                "unit": ""
            }
        ]

        result.append(parameter)

    connection.close()

    return result
