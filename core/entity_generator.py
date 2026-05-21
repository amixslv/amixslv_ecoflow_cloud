import logging
import base64
from typing import Any

from google.protobuf.descriptor import FieldDescriptor
from google.protobuf.json_format import MessageToDict

from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..entities.sensor import Sensor
from ..entities.number import Number
from ..entities.select import Select
from ..entities.switch import Switch
from ..entities.binary_sensor import BinarySensor
from ..entities.diagnostics import Diagnostics

from .field_map import FieldMap
from .utils import flatten_dict
from .header_parser import EcoFlowHeader
from ..supported_devices import DEVICE_TYPE_MAP

_LOGGER = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# PROTO LOADER
# ----------------------------------------------------------------------
def load_proto_messages(pb2_module: Any):
    display = None
    runtime = None
    set_cmd = None
    set_reply = None
    cms = None
    bms = None

    if not pb2_module:
        return {
            "display": None,
            "runtime": None,
            "set_cmd": None,
            "set_reply": None,
            "cms": None,
            "bms": None,
        }

    for name in dir(pb2_module):
        obj = getattr(pb2_module, name)
        if not hasattr(obj, "DESCRIPTOR"):
            continue

        if name.endswith("DisplayPropertyUpload"):
            display = obj
        elif name.endswith("RuntimePropertyUpload"):
            runtime = obj
        elif name.endswith("SetCommand"):
            set_cmd = obj
        elif name.endswith("SetReply"):
            set_reply = obj
        elif name.endswith("CMSHeartBeatReport"):
            cms = obj
        elif name.endswith("BMSHeartBeatReport"):
            bms = obj

    return {
        "display": display,
        "runtime": runtime,
        "set_cmd": set_cmd,
        "set_reply": set_reply,
        "cms": cms,
        "bms": bms,
    }


# ----------------------------------------------------------------------
# UNIVERSĀLS PROTO MESSAGE MAP
# ----------------------------------------------------------------------
PROTO_MSG_MAP = {
    (254, 21): "display",
    (254, 22): "runtime",
    (254, 17): "set_cmd",
    (254, 18): "set_reply",

    (32, 2): "cms",
    (32, 3): "bms",
}


# ----------------------------------------------------------------------
# ENTITY GENERATOR
# ----------------------------------------------------------------------
class EntityGenerator:
    CONTROL_REGEX = (
        "ac_.*on",
        "dc_.*on",
        "xboost",
        "force",
        "restart",
        "output",
        "inverter",
        "charger",
        "power_off",
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
        self.raw_json: dict = {}
        self.add_entities_callback: AddEntitiesCallback | None = None

        if self.pb2:
            self._load_proto_definitions()

    # ------------------------------------------------------------------
    # LOAD PROTO DEFINITIONS (ONLY FOR CONTROLS)
    # ------------------------------------------------------------------
    def _load_proto_definitions(self):
        msgs = load_proto_messages(self.pb2)
        set_cmd = msgs["set_cmd"]

        if not set_cmd:
            _LOGGER.warning("No SetCommand message found in pb2 module for %s", self.device_type)
            return

        for field in set_cmd.DESCRIPTOR.fields:
            self._register_control_field(field)

    # ------------------------------------------------------------------
    # REGISTER CONTROL FIELD
    # ------------------------------------------------------------------
    def _register_control_field(self, field: FieldDescriptor):
        field_name = field.name

        if field.type == FieldDescriptor.TYPE_MESSAGE:
            return

        meta: dict[str, Any] = {
            "name": self.field_map.get_name(field_name),
            "unit": None,
            "icon": self.field_map.get_icon(field_name),
            "enabled": True,
            "is_control": True,
        }

        if field.type == FieldDescriptor.TYPE_BOOL:
            meta["type"] = "switch"
            if any(r in field_name for r in self.CONTROL_REGEX):
                meta["entity_category"] = None
            else:
                meta["entity_category"] = EntityCategory.CONFIG

        elif field.type in (
            FieldDescriptor.TYPE_INT32,
            FieldDescriptor.TYPE_UINT32,
            FieldDescriptor.TYPE_INT64,
            FieldDescriptor.TYPE_UINT64,
            FieldDescriptor.TYPE_FLOAT,
            FieldDescriptor.TYPE_DOUBLE,
        ):
            meta["type"] = "number"
            meta["entity_category"] = EntityCategory.CONFIG
            meta["min"] = self.field_map.get_min(field_name) or 0
            meta["max"] = self.field_map.get_max(field_name) or 100
            meta["step"] = self.field_map.get_step(field_name) or 1

        elif field.type == FieldDescriptor.TYPE_ENUM:
            meta["type"] = "select"
            meta["entity_category"] = EntityCategory.CONFIG
            meta["options"] = self.field_map.get_options(field_name)

        self._field_meta[field_name] = meta

    # ------------------------------------------------------------------
    # DECODE MQTT MESSAGE (SMART MODE)
    # ------------------------------------------------------------------
    def decode_message(self, payload: bytes) -> dict:
        """Universāls PROTO dekoders display/runtime/set/cms/bms ziņām."""
        if not self.pb2:
            return {}

        # 0) Base64 decode (ja vajag)
        try:
            payload = base64.b64decode(payload, validate=True)
        except Exception:
            pass

        # ------------------------------------------------------------------
        # 1) PROTO-FIRST HEADER PARSER (ar proto_prefix)
        # ------------------------------------------------------------------
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
                    cmd_func = header.cmd_func
                    cmd_id = header.cmd_id

                    module = self.pb2

                    def cls(name: str):
                        return getattr(module, f"{prefix}{name}", None)

                    # Mēģinām visas zināmās ziņu klases pēc kārtas
                    for suffix in [
                        "DisplayPropertyUpload",
                        "RuntimePropertyUpload",
                        "CMSHeartBeatReport",
                        "BMSHeartBeatReport",
                        "SetCommand",
                        "SetReply",
                    ]:
                        c = cls(suffix)
                        if not c:
                            continue
                        try:
                            msg = c()
                            msg.ParseFromString(pdata)
                            raw = MessageToDict(msg, preserving_proto_field_name=True)
                            return flatten_dict(raw)
                        except Exception:
                            continue

                except Exception as e:
                    _LOGGER.debug("PROTO-first decode failed: %s", e)

        # ------------------------------------------------------------------
        # 2) UNIVERSĀLAIS HEADER PARSER (fallback)
        # ------------------------------------------------------------------
        header = EcoFlowHeader(payload)
        if not header.valid:
            return {}

        try:
            prefix = DEVICE_TYPE_MAP[self.manager.entry.data["device_label"]]["proto_prefix"]
        except Exception:
            prefix = None

        if not prefix:
            return {}

        module = self.pb2

        def cls(name: str):
            return getattr(module, f"{prefix}{name}", None)

        pdata = header.pdata

        # XOR decode, ja vajag
        if header.enc_type == 1 and header.src != 32:
            pdata = bytes([(b ^ header.seq) & 0xFF for b in pdata])

        for suffix in [
            "DisplayPropertyUpload",
            "RuntimePropertyUpload",
            "CMSHeartBeatReport",
            "BMSHeartBeatReport",
            "SetCommand",
            "SetReply",
        ]:
            c = cls(suffix)
            if not c:
                continue
            try:
                msg = c()
                msg.ParseFromString(pdata)
                raw = MessageToDict(msg, preserving_proto_field_name=True)
                return flatten_dict(raw)
            except Exception:
                continue

        return {}

    # ------------------------------------------------------------------
    # CREATE ENTITIES
    # ------------------------------------------------------------------
    def create_entities(self, platform: str):
        entities = []

        for field, meta in self._field_meta.items():
            if meta.get("type") != platform:
                continue

            if field in self.entities:
                continue

            ent = self._create_entity(field, meta)
            if ent:
                self.entities[field] = ent
                entities.append(ent)

        # Diagnostics only once
        if platform == "sensor" and self.add_entities_callback:
            if "diagnostics" not in self.entities:
                diag = Diagnostics(self, self.device_sn, self.device_type)
                self.entities["diagnostics"] = diag
                entities.append(diag)

        return entities
    # ------------------------------------------------------------------
    # UPDATE ENTITIES
    # ------------------------------------------------------------------
    def update_entities(self, decoded: dict):
        """Universāla entītiju ģenerēšana no jebkura PROTO decoded dict."""
        self.raw_json = decoded

        if not self.add_entities_callback:
            return

        # ---------------------------------------------------------
        # EXTRA BATTERY SUPPORT (BMS modules with num > 0)
        # ---------------------------------------------------------
        if "num" in decoded and isinstance(decoded["num"], int):
            num = decoded["num"]

            # 0 = main battery, 1..n = extra batteries
            if num > 0:
                prefix = f"extra_battery_{num}"

                mapping = {
                    "soc": "soc",
                    "temp": "temperature",
                    "vol": "voltage",
                    "remain_cap": "remaining_capacity",
                    "full_cap": "full_capacity",
                    "soh": "soh",
                }

                for src, dst in mapping.items():
                    if src in decoded:
                        field = f"{prefix}_{dst}"
                        self.raw_json[field] = decoded[src]

                        if field not in self._field_meta:
                            self._field_meta[field] = {
                                "name": f"Extra Battery {num} {dst.replace('_',' ').title()}",
                                "unit": self.field_map.get_unit(dst),
                                "icon": self.field_map.get_icon(dst),
                                "device_class": self.field_map.get_device_class(dst),
                                "state_class": self.field_map.get_state_class(dst),
                                "type": "sensor",
                                "enabled": True,
                                "is_control": False,
                                "device_override": f"{self.device_sn}_bms_{num}",
                            }

        # ---------------------------------------------------------
        # NORMAL SENSOR + CONTROL FIELD HANDLING
        # ---------------------------------------------------------
        for field, value in decoded.items():
            if isinstance(value, (dict, list)):
                continue

            # Normalizē lauka vārdu (noņem proto prefiksus)
            normalized = field
            for prefix in (
                "display.",
                "runtime.",
                "set_cmd.",
                "setcmd.",
                "set_reply.",
                "cms.",
                "bms.",
                "msg32_2_1.",
                "msg32_2_2.",
                "msg254_21_1.",
                "msg254_22_1.",
            ):
                if normalized.startswith(prefix):
                    normalized = normalized[len(prefix):]
                    break

            # Ja normalized lauks ir kontrole → izmanto kontroles meta
            if normalized in self._field_meta and self._field_meta[normalized].get("is_control"):
                self.raw_json[normalized] = value
                continue

            # Ja normalized lauks jau ir meta → ejam tālāk
            if normalized in self._field_meta:
                self.raw_json[normalized] = value
                continue

            # Automātiska tipa noteikšana
            if isinstance(value, bool):
                ent_type = "binary_sensor"
            elif isinstance(value, (int, float)):
                ent_type = "sensor"
            elif isinstance(value, str):
                ent_type = "sensor"
            else:
                continue

            # FieldMap device_class → vienmēr sensor
            if self.field_map.get_device_class(normalized):
                ent_type = "sensor"

            # Izveido meta
            self._field_meta[normalized] = {
                "name": self.field_map.get_name(normalized),
                "unit": self.field_map.get_unit(normalized),
                "icon": self.field_map.get_icon(normalized),
                "device_class": self.field_map.get_device_class(normalized),
                "state_class": self.field_map.get_state_class(normalized),
                "entity_category": self.field_map.get_category(normalized, False),
                "type": ent_type,
                "enabled": True,
                "is_control": False,
            }

            self.raw_json[normalized] = value

        # ---------------------------------------------------------
        # CREATE MISSING ENTITIES
        # ---------------------------------------------------------
        for fname, meta in self._field_meta.items():
            if fname not in self.entities:
                ent = self._create_entity(fname, meta)
                if ent:
                    self.entities[fname] = ent
                    self.add_entities_callback([ent])

        # ---------------------------------------------------------
        # UPDATE ENTITY VALUES
        # ---------------------------------------------------------
        for fname, ent in self.entities.items():
            if fname in self.raw_json:
                val = self.raw_json[fname]

                # Noapaļošana skaitļiem
                if isinstance(val, float):
                    val = round(val, 2)

                # Switch / BinarySensor
                if hasattr(ent, "_attr_is_on"):
                    if isinstance(val, bool):
                        ent._attr_is_on = val
                    elif isinstance(val, (int, float)):
                        ent._attr_is_on = val != 0
                    elif isinstance(val, str):
                        v = val.strip().lower()
                        ent._attr_is_on = v in ("1", "true", "on")
                else:
                    ent._attr_native_value = val

            if ent.hass:
                ent.async_write_ha_state()

    # ------------------------------------------------------------------
    # ENTITY FACTORY
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # VALUE ACCESSORS
    # ------------------------------------------------------------------
    def get_field_value(self, field: str):
        return self.raw_json.get(field)

    def get_raw_json(self):
        return self.raw_json
