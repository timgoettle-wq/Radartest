import sqlite3
from pathlib import Path


DB_FILE = Path(__file__).parent / "radar_test.db"


def get_connection():
    connection = sqlite3.connect(DB_FILE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


def get_vehicles():
    connection = get_connection()

    rows = connection.execute("""
        SELECT
            id,
            manufacturer,
            model,
            generation,
            year_from,
            year_to,
            description

        FROM vehicles

        ORDER BY
            manufacturer,
            model,
            generation
    """).fetchall()

    connection.close()

    return [
        dict(row)
        for row in rows
    ]


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