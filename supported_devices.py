import os
import logging

_LOGGER = logging.getLogger(__name__)

PROTO_PATH = os.path.join(
    os.path.dirname(__file__),
    "protocol",
)


def _normalize_proto_name(filename: str):
    base = filename.replace(".proto", "")
    core = base[3:] if base.startswith("ef_") else base

    internal = core.upper()
    label = internal.replace("_", " ")
    name_clean = " ".join(word.capitalize() for word in core.replace("_", " ").split())
    device_type = core.lower()
    proto_prefix = name_clean.replace(" ", "")

    return label, internal, base, name_clean, device_type, proto_prefix


def _load_supported_devices():
    labels = set()
    mapping = {}

    if not os.path.isdir(PROTO_PATH):
        _LOGGER.error("Protocol folder not found: %s", PROTO_PATH)
        return [], {}

    for file in os.listdir(PROTO_PATH):
        if not file.endswith(".proto"):
            continue

        label, internal, base, name_clean, device_type, proto_prefix = _normalize_proto_name(file)

        payload = {
            "id": internal,
            "proto_file": file,
            "proto": f"{base}_pb2",
            "name": name_clean,
            "device_type": device_type,
            "proto_prefix": proto_prefix,
        }

        # Primārā izvēle UI
        mapping[name_clean] = payload
        # Atpakaļsaderība ar vecajiem ierakstiem
        mapping[label] = payload

        labels.add(name_clean)

    return sorted(labels), mapping


SUPPORTED_DEVICE_LABELS, DEVICE_TYPE_MAP = _load_supported_devices()
