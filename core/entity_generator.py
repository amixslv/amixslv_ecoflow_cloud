import base64
import copy
import logging
import time
from typing import Any

from google.protobuf.descriptor import FieldDescriptor
from google.protobuf.json_format import MessageToDict

from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory

from ..entities.binary_sensor import BinarySensor
from ..entities.button import Button
from ..entities.diagnostics import Diagnostics
from ..entities.number import Number
from ..entities.select import Select
from ..entities.sensor import Sensor
from ..entities.switch import Switch
from ..cont import (
    PROTO_HEADER_SRC_CLOUD,
    PROTO_MESSAGE_SOURCE_BY_SUFFIX,
    PROTO_MESSAGE_SUFFIXES,
)
from ..supported_devices import DEVICE_TYPE_MAP
from .header_parser import EcoFlowHeader
from .field_map import FieldMap
from .utils import flatten_dict

_LOGGER = logging.getLogger(__name__)

PROTO_MSG_MAP = {
    (254, 21): "display",
    (254, 22): "runtime",
    (254, 17): "set_cmd",
    (254, 18): "set_reply",
    (32, 2): "cms",
    (32, 3): "bms",
}


def load_proto_messages(pb2_module: Any) -> dict[str, Any]:
    messages = {
        "display": None,
        "runtime": None,
        "set_cmd": None,
        "set_reply": None,
        "cms": None,
        "bms": None,
    }

    if not pb2_module:
        return messages

    for name in dir(pb2_module):
        obj = getattr(pb2_module, name)
        if not hasattr(obj, "DESCRIPTOR"):
            continue

        for suffix, source in PROTO_MESSAGE_SOURCE_BY_SUFFIX.items():
            if name.endswith(suffix):
                messages[source] = obj
                break

    return messages


class EntityGenerator:
    CONTROL_SWITCH_HINTS = (
        "flag",
        "enable",
        "enabled",
        "switch",
        "open",
        "close",
        "beep",
        "alarm",
        "warn",
        "fault",
        "xboost_en",
    )

    CONTROL_SELECT_HINTS = (
        "mode",
        "type",
        "level",
        "charge_type",
        "chg_type",
        "led_mode",
    )

    def __init__(self, manager, hass, device_sn: str, device_type: str, pb2_module: Any):
        self.manager = manager
        self.hass = hass
        self.device_sn = device_sn
        self.device_type = device_type
        self.pb2 = pb2_module
        self.field_map = FieldMap()

        self.entities: dict[str, object] = {}
        self._field_meta: dict[str, dict] = {}
        self._field_index: dict[str, list[str]] = {}
        self.raw_json: dict = {}
        self._platform_callbacks: dict[str, AddEntitiesCallback] = {}
        self._last_msg_type: str | None = None
        self._last_proto_key: str | None = None
        self._last_decode_debug: dict[str, Any] = {}
        self._pending_writes: dict[str, tuple[Any, float]] = {}

        if self.pb2:
            self._load_proto_definitions()

    # Keep backward compat: legacy single callback assignment from platform files
    @property
    def add_entities_callback(self):
        return None

    @add_entities_callback.setter
    def add_entities_callback(self, value):
        pass  # no-op; platforms must use set_platform_callback()

    def set_platform_callback(self, platform: str, callback: AddEntitiesCallback):
        self._platform_callbacks[platform] = callback

    def _entity_key(self, source: str, field_path: str) -> str:
        return f"{source}:{field_path}"

    def _add_index(self, field_path: str, entity_key: str):
        self._field_index.setdefault(field_path, [])
        if entity_key not in self._field_index[field_path]:
            self._field_index[field_path].append(entity_key)

    def _resolve_nested_message(self, field: FieldDescriptor):
        nested_name = getattr(field.message_type, "name", None)
        if not nested_name:
            return None

        return getattr(self.pb2, nested_name, None)

    def _load_proto_definitions(self):
        messages = load_proto_messages(self.pb2)

        for source in ("display", "runtime", "cms", "bms"):
            message_cls = messages.get(source)
            if message_cls:
                self._register_message_fields(message_cls, source=source, is_control=False)

        set_cmd = messages.get("set_cmd")
        if set_cmd:
            self._register_message_fields(set_cmd, source="set_cmd", is_control=True)

    def _register_message_fields(self, message_cls, source: str, is_control: bool, parent_path: str = ""):
        for field in message_cls.DESCRIPTOR.fields:
            if field.label == FieldDescriptor.LABEL_REPEATED and field.type != FieldDescriptor.TYPE_MESSAGE:
                continue

            field_path = f"{parent_path}.{field.name}" if parent_path else field.name

            if field.type == FieldDescriptor.TYPE_MESSAGE:
                nested_cls = self._resolve_nested_message(field)
                if nested_cls:
                    self._register_message_fields(nested_cls, source=source, is_control=is_control, parent_path=field_path)
                continue

            entity_key = self._entity_key(source, field_path)
            if entity_key in self._field_meta:
                continue

            meta = self._build_field_meta(field, field_path, source, is_control)
            self._field_meta[entity_key] = meta
            self._add_index(field_path, entity_key)

    def _build_field_meta(self, field: FieldDescriptor, field_path: str, source: str, is_control: bool) -> dict:
        name = self.field_map.get_name(field_path)
        unit = self.field_map.get_unit(field_path)
        icon = self.field_map.get_icon(field_path)
        device_class = self.field_map.get_device_class(field_path)
        state_class = self.field_map.get_state_class(field_path)
        entity_category = self.field_map.get_category(field_path, is_control)

        state_field_paths = [field_path]
        if is_control:
            alias = field_path
            if field_path.startswith("cfg_energy_backup."):
                alias = field_path.split(".", 1)[1]
            elif field_path == "cfg_dc12v_out_open":
                alias = "dc_out_open"
            elif field_path == "cfg_led_mode":
                alias = "led_mode"
            elif field_path.startswith("cfg_"):
                alias = field_path.removeprefix("cfg_")
            if alias not in state_field_paths:
                state_field_paths.append(alias)

        meta: dict[str, Any] = {
            "name": name,
            "unit": unit,
            "icon": icon,
            "device_class": device_class,
            "state_class": state_class,
            "entity_category": entity_category,
            "enabled": self.field_map.is_default_enabled(field_path, is_control, source),
            "field_path": field_path,
            "state_field_paths": state_field_paths,
            "source": source,
            "is_control": is_control,
            "unique_id": self._entity_key(source, field_path),
        }

        if is_control:
            forced_control_type = self.field_map.get_control_type(field_path)
            options = self.field_map.get_options(field_path)
            if forced_control_type == "button":
                meta["type"] = "button"
            elif forced_control_type == "switch":
                meta["type"] = "switch"
            elif forced_control_type == "number":
                meta["type"] = "number"
                guessed_min, guessed_max, guessed_step = self.field_map.guess_range(field_path)
                meta["min"] = self.field_map.get_min(field_path) or guessed_min
                meta["max"] = self.field_map.get_max(field_path) or guessed_max
                meta["step"] = self.field_map.get_step(field_path) or guessed_step
            elif options:
                meta["type"] = "select"
                meta["options"] = options
            elif field.type == FieldDescriptor.TYPE_BOOL:
                meta["type"] = "switch"
            elif self._looks_like_toggle(field_path):
                meta["type"] = "switch"
            else:
                meta["type"] = "number"
                guessed_min, guessed_max, guessed_step = self.field_map.guess_range(field_path)
                meta["min"] = self.field_map.get_min(field_path) or guessed_min
                meta["max"] = self.field_map.get_max(field_path) or guessed_max
                meta["step"] = self.field_map.get_step(field_path) or guessed_step
        else:
            if field.type == FieldDescriptor.TYPE_STRING:
                meta["type"] = "sensor"
            elif self._looks_like_toggle(field_path):
                meta["type"] = "binary_sensor"
            else:
                meta["type"] = "sensor"

        if is_control:
            # Controls: switch/button only. Number/select should be in Configuration.
            if meta.get("type") in ("number", "select"):
                meta["entity_category"] = EntityCategory.CONFIG
            else:
                meta["entity_category"] = None

        return meta

    def _looks_like_toggle(self, field_path: str) -> bool:
        field_name = field_path.split(".")[-1].lower()
        if field_name.endswith(("_en", "_enable", "_enabled", "_switch", "_open", "_close", "_flag")):
            return True
        return any(
            field_name.endswith(f"_{hint}") or f"_{hint}_" in field_name or field_name == hint
            for hint in self.CONTROL_SWITCH_HINTS
        )

    def _looks_like_select(self, field_path: str) -> bool:
        field_name = field_path.split(".")[-1].lower()
        return any(hint in field_name for hint in self.CONTROL_SELECT_HINTS)

    def _decode_proto_candidates(self, prefix: str, pdata: bytes) -> tuple[str | None, dict, int]:
        best_suffix = None
        best_data: dict = {}
        best_score = -1

        for suffix in PROTO_MESSAGE_SUFFIXES:
            message_cls = getattr(self.pb2, f"{prefix}{suffix}", None)
            if not message_cls:
                continue

            try:
                msg = message_cls()
                msg.ParseFromString(pdata)
                raw = MessageToDict(msg, preserving_proto_field_name=True)
                flat = flatten_dict(raw)
                if not flat:
                    continue
                score = sum(1 for key in flat if key in self._field_index)
                if score > best_score:
                    best_suffix = suffix
                    best_data = flat
                    best_score = score
            except Exception:
                continue

        return best_suffix, best_data, best_score

    def _decode_header_message_headers(self, prefix: str, headers) -> tuple[str | None, dict, int]:
        merged: dict = {}
        matched_suffixes: list[str] = []
        total_score = 0

        for header in headers:
            pdata = getattr(header, "pdata", b"")
            if not pdata:
                continue

            if getattr(header, "enc_type", 0) == 1 and getattr(header, "src", None) != PROTO_HEADER_SRC_CLOUD:
                seq = int(getattr(header, "seq", 0))
                pdata = bytes([(b ^ seq) & 0xFF for b in pdata])

            suffix, decoded, score = self._decode_proto_candidates(prefix, pdata)
            if not decoded:
                continue

            merged.update(decoded)
            if suffix:
                matched_suffixes.append(suffix)
            if score > 0:
                total_score += score

        if not merged:
            return None, {}, 0

        matched = "+".join(dict.fromkeys(matched_suffixes)) if matched_suffixes else None
        return matched, merged, total_score or len(merged)

    def _decode_proto_payload(self, payload: bytes) -> tuple[str | None, dict]:
        if not self.pb2:
            self._last_decode_debug = {
                "decode_path": None,
                "matched_proto": None,
                "matched_fields": 0,
                "header": None,
                "note": "pb2_not_loaded",
            }
            return None, {}

        self._last_decode_debug = {
            "decode_path": None,
            "matched_proto": None,
            "matched_fields": 0,
            "header": None,
        }

        try:
            payload = base64.b64decode(payload, validate=True)
        except Exception:
            pass

        prefix = None
        try:
            prefix = DEVICE_TYPE_MAP[self.manager.entry.data["device_label"]]["proto_prefix"]
        except Exception:
            prefix = None

        if prefix:
            HeaderMessage = getattr(self.pb2, f"{prefix}HeaderMessage", None)
            if HeaderMessage:
                try:
                    header_msg = HeaderMessage()
                    header_msg.ParseFromString(payload)
                    headers = list(header_msg.header)
                    header = headers[-1]
                    self._last_decode_debug["header"] = {
                        "parser": "header_message",
                        "src": getattr(header, "src", None),
                        "dest": getattr(header, "dest", None),
                        "d_src": getattr(header, "d_src", None),
                        "d_dest": getattr(header, "d_dest", None),
                        "cmd_func": getattr(header, "cmd_func", None),
                        "cmd_id": getattr(header, "cmd_id", None),
                        "enc_type": getattr(header, "enc_type", None),
                        "seq": getattr(header, "seq", None),
                        "time_snap": getattr(header, "time_snap", None),
                        "device_sn": getattr(header, "device_sn", None),
                        "from": getattr(header, "from", None),
                        "header_count": len(headers),
                    }
                    _LOGGER.debug(
                        "PROTO header: src=%s dest=%s cmd_func=%s cmd_id=%s enc=%s seq=%s",
                        header.src, header.dest, header.cmd_func, header.cmd_id,
                        header.enc_type, header.seq,
                    )
                    _bsh, _bdh, _bsc = self._decode_header_message_headers(prefix, headers)
                    if _bdh:
                        self._last_decode_debug["decode_path"] = (
                            "header_message_multi" if len(headers) > 1 else "header_message"
                        )
                        self._last_decode_debug["matched_proto"] = _bsh
                        self._last_decode_debug["matched_fields"] = _bsc
                        return _bsh, _bdh
                except Exception as exc:
                    _LOGGER.debug("PROTO-first decode failed: %s", exc)
                    self._last_decode_debug["header_message_error"] = str(exc)

        header = EcoFlowHeader(payload)
        if not header.valid:
            self._last_decode_debug["note"] = "invalid_header"
            return None, {}

        self._last_decode_debug["header"] = {
            "parser": "legacy_header",
            "src": header.src,
            "dest": header.dest,
            "d_src": header.d_src,
            "d_dest": header.d_dest,
            "cmd_func": header.cmd_func,
            "cmd_id": header.cmd_id,
            "enc_type": header.enc_type,
            "seq": header.seq,
            "data_len": header.data_len,
        }

        try:
            prefix = DEVICE_TYPE_MAP[self.manager.entry.data["device_label"]]["proto_prefix"]
        except Exception:
            prefix = None

        if not prefix:
            return None, {}

        pdata = header.pdata
        if header.enc_type == 1 and header.src != PROTO_HEADER_SRC_CLOUD:
            pdata = bytes([(b ^ header.seq) & 0xFF for b in pdata])

        _bsb, _bdb, _bscb = None, {}, -1
        for suffix in PROTO_MESSAGE_SUFFIXES:
            message_cls = getattr(self.pb2, f"{prefix}{suffix}", None)
            if not message_cls:
                continue

            try:
                msg = message_cls()
                msg.ParseFromString(pdata)
                raw = MessageToDict(msg, preserving_proto_field_name=True)
                _dd = flatten_dict(raw)
                if not _dd:
                    continue
                _sc = sum(1 for k in _dd if k in self._field_index)
                if _sc > _bscb:
                    _bscb, _bsb, _bdb = _sc, suffix, _dd
            except Exception:
                continue

        if _bdb:
            self._last_decode_debug["decode_path"] = "header_parser"
            self._last_decode_debug["matched_proto"] = _bsb
            self._last_decode_debug["matched_fields"] = _bscb
        return (_bsb, _bdb) if _bdb else (None, {})

    def decode_message(self, payload: bytes) -> dict:
        """Decode MQTT payload to a flattened proto dictionary."""
        msg_type, decoded = self._decode_proto_payload(payload)
        if msg_type:
            self._last_msg_type = msg_type
            self._last_proto_key = msg_type
        return decoded

    def create_entities(self, platform: str):
        entities = []

        for meta in self._field_meta.values():
            if meta.get("type") != platform:
                continue

            entity_key = meta["unique_id"]
            field_path = meta["field_path"]

            if entity_key in self.entities:
                continue

            ent = self._create_entity(field_path, meta)
            if ent:
                self.entities[entity_key] = ent
                entities.append(ent)

        if platform == "sensor" and "diagnostics" not in self.entities:
            diag = Diagnostics(self, self.device_sn, self.device_type)
            self.entities["diagnostics"] = diag
            entities.append(diag)

        return entities

    def update_entities(self, decoded: dict):
        """Update entity states from a flattened proto payload."""
        if not decoded:
            return

        self.raw_json.update(decoded)

        diag = self.entities.get("diagnostics")
        if diag and hasattr(diag, "set_last_message_type"):
            diag.set_last_message_type(self._last_msg_type, self._last_proto_key)

        if self._platform_callbacks:
            for field_path, value in decoded.items():
                if isinstance(value, (dict, list)):
                    continue

                for entity_key in self._field_index.get(field_path, []):
                    meta = self._field_meta.get(entity_key)
                    if not meta:
                        continue

                    if entity_key not in self.entities:
                        ent = self._create_entity(field_path, meta)
                        if ent:
                            self.entities[entity_key] = ent
                            cb = self._platform_callbacks.get(meta.get("type"))
                            if cb:
                                cb([ent])

        for entity_key, ent in self.entities.items():
            meta = getattr(ent, "_meta", {})
            state_paths = meta.get("state_field_paths") or [meta.get("field_path")]
            if not state_paths:
                continue

            val = None
            found_path = None
            for candidate in state_paths:
                if candidate and candidate in decoded:
                    val = decoded[candidate]
                    found_path = candidate
                    break
            if not found_path:
                continue

            pending = self._get_pending_write(found_path)
            if pending is not None:
                expected, _ = pending
                if str(val) == str(expected):
                    self._clear_pending_write(found_path)
                else:
                    # Ignore stale telemetry while waiting for command confirmation.
                    continue

            if isinstance(val, float):
                val = round(val, 2)

            if hasattr(ent, "_attr_is_on"):
                coerced = self._coerce_bool(val)
                if coerced is None:
                    continue
                ent._attr_is_on = coerced
            elif hasattr(ent, "_attr_current_option"):
                coerced = self._coerce_option(ent, val)
                if coerced is None:
                    continue
                ent._attr_current_option = coerced
            else:
                if val is None:
                    continue
                ent._attr_native_value = val

            if hasattr(ent, "_has_known_state"):
                ent._has_known_state = True

            if ent.hass:
                ent.async_write_ha_state()

    def _coerce_bool(self, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "on", "yes")
        return None

    def _coerce_option(self, ent, value):
        options = getattr(ent, "_attr_options", []) or []
        if isinstance(value, str):
            if value in options:
                return value
            return value

        if isinstance(value, (int, float)) and options:
            index = int(value)
            if 0 <= index < len(options):
                return options[index]

        return str(value) if value is not None else None

    def _create_entity(self, field: str, meta: dict):
        t = meta.get("type")

        if t == "sensor":
            return Sensor(self, self.device_sn, self.device_type, field, meta)
        if t == "number":
            return Number(self, self.device_sn, self.device_type, field, meta)
        if t == "select":
            return Select(self, self.device_sn, self.device_type, field, meta)
        if t == "switch":
            return Switch(self, self.device_sn, self.device_type, field, meta)
        if t == "button":
            return Button(self, self.device_sn, self.device_type, field, meta)
        if t == "binary_sensor":
            return BinarySensor(self, self.device_sn, self.device_type, field, meta)

        return None

    def register_pending_write(self, field_path: str, value: Any, ttl_seconds: float = 5.0):
        expires_at = time.time() + ttl_seconds
        self._pending_writes[field_path] = (value, expires_at)

    def _get_pending_write(self, field_path: str) -> tuple[Any, float] | None:
        pending = self._pending_writes.get(field_path)
        if not pending:
            return None
        expected, expires_at = pending
        if time.time() > expires_at:
            self._pending_writes.pop(field_path, None)
            return None
        return expected, expires_at

    def _clear_pending_write(self, field_path: str):
        self._pending_writes.pop(field_path, None)

    def has_field(self, field_path: str) -> bool:
        return field_path in self._field_index

    def get_field_value(self, field: str):
        return self.raw_json.get(field)

    def get_raw_json(self):
        return self.raw_json

    def get_last_decode_debug(self):
        return copy.deepcopy(self._last_decode_debug)
