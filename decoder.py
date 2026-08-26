import struct


def decode_value(data: bytes, field: dict):
    offset = field["offset"]
    length = field["length"]
    data_type = field["type"]

    raw = data[offset:offset + length]

    if len(raw) != length:
        raise ValueError(
            f"Nicht genügend Daten für {field['name']}: "
            f"erwartet {length}, erhalten {len(raw)}"
        )

    if data_type == "uint8":
        return raw[0]

    elif data_type == "uint16_be":
        return int.from_bytes(raw, byteorder="big", signed=False)

    elif data_type == "uint16_le":
        return int.from_bytes(raw, byteorder="little", signed=False)

    elif data_type == "int16_be":
        return int.from_bytes(raw, byteorder="big", signed=True)

    elif data_type == "int16_le":
        return int.from_bytes(raw, byteorder="little", signed=True)

    elif data_type == "float32_be":
        return struct.unpack(">f", raw)[0]

    elif data_type == "float32_le":
        return struct.unpack("<f", raw)[0]

    else:
        raise ValueError(f"Unbekannter Datentyp: {data_type}")


def decode_parameter(response: bytes, parameter_config: dict):
    result = {}

    for field in parameter_config["fields"]:
        value = decode_value(response, field)

        factor = field.get("factor", 1.0)
        value_offset = field.get("value_offset", 0.0)

        if isinstance(value, (int, float)):
            value = value * factor + value_offset

        result[field["name"]] = {
            "value": value,
            "unit": field.get("unit", "")
        }

    return result