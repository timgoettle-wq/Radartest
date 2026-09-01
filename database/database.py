import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).parent / "radar_test.db"


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


def get_vehicles():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row

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