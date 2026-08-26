import sqlite3
from pathlib import Path


DB_FILE = Path(__file__).parent / "radar_test.db"


def create_database():
    connection = sqlite3.connect(DB_FILE)
    connection.execute("PRAGMA foreign_keys = ON")
    cursor = connection.cursor()

    # =========================================================
    # Fahrzeuge
    # =========================================================

    cursor.execute("""
        CREATE TABLE vehicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            manufacturer TEXT NOT NULL,
            model TEXT NOT NULL,
            generation TEXT,

            year_from INTEGER,
            year_to INTEGER,

            description TEXT
        )
    """)

    # =========================================================
    # Steuergeräte
    # =========================================================

    cursor.execute("""
        CREATE TABLE ecus (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            vehicle_id INTEGER NOT NULL,

            name TEXT NOT NULL,

            interface TEXT NOT NULL DEFAULT 'can',
            channel TEXT NOT NULL DEFAULT 'can0',

            bitrate INTEGER NOT NULL,

            request_id INTEGER NOT NULL,
            response_id INTEGER NOT NULL,

            FOREIGN KEY(vehicle_id)
                REFERENCES vehicles(id)
                ON DELETE CASCADE
        )
    """)

    # =========================================================
    # Diagnoseparameter
    # =========================================================

    cursor.execute("""
        CREATE TABLE diagnostic_parameters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            ecu_id INTEGER NOT NULL,

            name TEXT NOT NULL,

            service INTEGER NOT NULL,
            did INTEGER NOT NULL,

            FOREIGN KEY(ecu_id)
                REFERENCES ecus(id)
                ON DELETE CASCADE
        )
    """)

    # =========================================================
    # Signaldefinitionen
    # =========================================================

    cursor.execute("""
        CREATE TABLE signal_fields (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            parameter_id INTEGER NOT NULL,

            name TEXT NOT NULL,

            byte_offset INTEGER NOT NULL,
            byte_length INTEGER NOT NULL,

            data_type TEXT NOT NULL,

            factor REAL NOT NULL DEFAULT 1.0,
            value_offset REAL NOT NULL DEFAULT 0.0,

            unit TEXT,

            FOREIGN KEY(parameter_id)
                REFERENCES diagnostic_parameters(id)
                ON DELETE CASCADE
        )
    """)

    # =========================================================
    # Mercedes-Benz E-Class W213
    # =========================================================

    cursor.execute("""
        INSERT INTO vehicles (
            manufacturer,
            model,
            generation,
            year_from,
            year_to,
            description
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        "Mercedes-Benz",
        "E-Class",
        "W213",
        2016,
        2020,
        "Radar test vehicle"
    ))

    vehicle_id = cursor.lastrowid

    # =========================================================
    # Front Radar ECU
    # =========================================================

    cursor.execute("""
        INSERT INTO ecus (
            vehicle_id,
            name,
            interface,
            channel,
            bitrate,
            request_id,
            response_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        vehicle_id,
        "Front Radar",
        "can",
        "can0",
        500000,
        0x741,
        0x721
    ))

    ecu_id = cursor.lastrowid

    # =========================================================
    # DID 0x0201
    # =========================================================

    cursor.execute("""
        INSERT INTO diagnostic_parameters (
            ecu_id,
            name,
            service,
            did
        )
        VALUES (?, ?, ?, ?)
    """, (
        ecu_id,
        "radar_target",
        0x22,
        0x0201
    ))

    parameter_id = cursor.lastrowid

    # =========================================================
    # Felder innerhalb DID 0x0201
    # =========================================================

    fields = [
        (
            parameter_id,
            "status",
            3,
            1,
            "uint8",
            1.0,
            0.0,
            ""
        ),
        (
            parameter_id,
            "distance",
            4,
            4,
            "float32_be",
            1.0,
            0.0,
            "m"
        ),
        (
            parameter_id,
            "relative_speed",
            8,
            4,
            "float32_be",
            1.0,
            0.0,
            "km/h"
        ),
        (
            parameter_id,
            "angle",
            12,
            4,
            "float32_be",
            1.0,
            0.0,
            "deg"
        ),
        (
            parameter_id,
            "relative_acceleration",
            16,
            4,
            "float32_be",
            1.0,
            0.0,
            "m/s2"
        )
    ]

    cursor.executemany("""
        INSERT INTO signal_fields (
            parameter_id,
            name,
            byte_offset,
            byte_length,
            data_type,
            factor,
            value_offset,
            unit
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, fields)

    connection.commit()
    connection.close()

    print(f"Datenbank erstellt: {DB_FILE}")
    print(f"Vehicle ID: {vehicle_id}")
    print(f"ECU ID: {ecu_id}")
    print(f"Parameter ID: {parameter_id}")


if __name__ == "__main__":
    create_database()