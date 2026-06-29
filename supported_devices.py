import os
import logging

_LOGGER = logging.getLogger(__name__)

# Path to protocol folder
PROTO_PATH = os.path.join(
    os.path.dirname(__file__),
    "protocol"
)


def _normalize_proto_name(filename: str):
    """
    filename: ef_delta3_plus.proto

    Atgriež:
    - label: "DELTA 3 PLUS"
    - internal id: "DELTA_3_PLUS"
    - base: "ef_delta3_plus"
    - name_clean: "Delta 3 Plus"
    - device_type: "delta_3_plus"   ← entītiju ID shēmai
    - proto_prefix: "Delta3Plus"    ← PROTO klases prefikss (HeaderMessage, RuntimePropertyUpload utt.)
    """
    base = filename.replace(".proto", "")  # ef_delta3_plus

    # noņem ef_ prefiksu cilvēku lasāmajam nosaukumam
    core = base[3:] if base.startswith("ef_") else base

    # internal ID (DELTA_3_PLUS)
    internal = core.upper()

    # label UI dropdownam (DELTA 3 PLUS)
    label = internal.replace("_", " ")

    # cilvēcisks nosaukums (Delta 3 Plus)
    name_clean = " ".join(word.capitalize() for word in core.replace("_", " ").split())

    # device_type (delta_3_plus) — izmanto entītiju unique_id
    device_type = core.lower()

    # proto_prefix (Delta3Plus) — izmanto PROTO klases nosaukumu ģenerēšanai
    proto_prefix = name_clean.replace(" ", "")

    return label, internal, base, name_clean, device_type, proto_prefix


def _load_supported_devices():
    labels = set()
    mapping = {}

    if not os.path.isdir(PROTO_PATH):
        _LOGGER.error("Protocol folder not found: %s", PROTO_PATH)
        return labels, mapping

    for file in os.listdir(PROTO_PATH):
        if not file.endswith(".proto"):
            continue

        label, internal, base, name_clean, device_type, proto_prefix = _normalize_proto_name(file)

        payload = {
            "id": internal,                 # DELTA_3_PLUS
            "proto_file": file,             # ef_delta3_plus.proto
            "proto": f"{base}_pb2",         # ef_delta3_plus_pb2
            "name": name_clean,             # Delta 3 Plus
            "device_type": device_type,     # delta_3_plus
            "proto_prefix": proto_prefix,   # Delta3Plus
        }
        # Primary key: human-readable English label
        mapping[name_clean] = payload
        # Backward compatibility for already saved entries using uppercase label
        mapping[label] = payload

        labels.add(name_clean)

    return sorted(labels), mapping


SUPPORTED_DEVICE_LABELS, DEVICE_TYPE_MAP = _load_supported_devices()
