import base64
import logging
from typing import Any

from google.protobuf.descriptor import FieldDescriptor
from google.protobuf.json_format import MessageToDict

from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..entities.binary_sensor import BinarySensor
from ..entities.diagnostics import Diagnostics
from ..entities.number import Number
from ..entities.select import Select
from ..entities.sensor import Sensor
from ..entities.switch import Switch
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

        if name.endswith("DisplayPropertyUpload"):
            messages["display"] = obj
        elif name.endswith("RuntimePropertyUpload"):
            messages["runtime"] = obj
        elif name.endswith("SetCommand"):
            messages["set_cmd"] = obj
        elif name.endswith("SetReply"):
            messages["set_reply"] = obj
        elif name.endswith("CMSHeartBeatReport"):
            messages["cms"] = obj
        elif name.endswith("BMSHeartBeatReport"):
            messages["bms"] = obj

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

        meta: dict[str, Any] = {
            "name": name,
            "unit": unit,
            "icon": icon,
            "device_class": device_class,
            "state_class": state_class,
            "entity_category": entity_category,
            "enabled": self.field_map.is_default_enabled(field_path, is_control, source),
            "field_path": field_path,
            "source": source,
            "is_control": is_control,
            "unique_id": self._entity_key(source, field_path),
        }

        if is_control:
            forced_control_type = self.field_map.get_control_type(field_path)
            options = self.field_map.get_options(field_path)
            if forced_control_type == "switch":
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
                meta["entity_category"] = "config"
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

    def _decode_proto_payload(self, payload: bytes) -> tuple[str | None, dict]:
        if not self.pb2:
            return None, {}

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
                    header = header_msg.header[-1]
                    pdata = header.pdata

                    _bsh, _bdh, _bsc = None, {}, -1
                    for suffix in (
                        "DisplayPropertyUpload",
                        "RuntimePropertyUpload",
                        "CMSHeartBeatReport",
                        "BMSHeartBeatReport",
                        "SetCommand",
                        "SetReply",
                    ):
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
                            if _sc > _bsc:
                                _bsc, _bsh, _bdh = _sc, suffix, _dd
                        except Exception:
                            continue
                    if _bdh:
                        return _bsh, _bdh
                except Exception as exc:
                    _LOGGER.debug("PROTO-first decode failed: %s", exc)

        header = EcoFlowHeader(payload)
        if not header.valid:
            return None, {}

        try:
            prefix = DEVICE_TYPE_MAP[self.manager.entry.data["device_label"]]["proto_prefix"]
        except Exception:
            prefix = None

        if not prefix:
            return None, {}

        pdata = header.pdata
        if header.enc_type == 1 and header.src != 32:
            pdata = bytes([(b ^ header.seq) & 0xFF for b in pdata])

        _bsb, _bdb, _bscb = None, {}, -1
        for suffix in (
            "DisplayPropertyUpload",
            "RuntimePropertyUpload",
            "CMSHeartBeatReport",
            "BMSHeartBeatReport",
            "SetCommand",
            "SetReply",
        ):
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

        self.raw_json = decoded

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
            field_path = meta.get("field_path")
            if not field_path or field_path not in decoded:
                continue

            val = decoded[field_path]

            if isinstance(val, float):
                val = round(val, 2)

            if hasattr(ent, "_attr_is_on"):
                ent._attr_is_on = self._coerce_bool(val)
            elif hasattr(ent, "_attr_current_option"):
                ent._attr_current_option = self._coerce_option(ent, val)
            else:
                ent._attr_native_value = val

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
        if t == "binary_sensor":
            return BinarySensor(self, self.device_sn, self.device_type, field, meta)

        return None

    def has_field(self, field_path: str) -> bool:
        return field_path in self._field_index

    def get_field_value(self, field: str):
        return self.raw_json.get(field)

    def get_raw_json(self):
        return self.raw_json
