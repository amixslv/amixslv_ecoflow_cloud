import json
import logging
from datetime import datetime, timezone
import importlib
import time
from pathlib import Path

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import async_get as async_get_device_registry

from ..api.cloud_client import CloudClient
from ..api.mqtt_client import MQTTClient
from ..core.entity_generator import EntityGenerator
from ..supported_devices import DEVICE_TYPE_MAP
from ..api.message import JSONMessage
from ..cont import (
    DOMAIN,
    MQTT_TOPIC_DEVICE_PROP_LEGACY,
    MQTT_TOPIC_DEVICE_PROPERTY,
    MQTT_TOPIC_USER_DEVICE_PROPERTY,
    PROTO_HEADER_D_DEST,
    PROTO_HEADER_D_SRC,
    PROTO_HEADER_DEST_MAIN,
    PROTO_HEADER_IS_RW_CMD,
    PROTO_HEADER_NEED_ACK,
    PROTO_HEADER_SRC_CLOUD,
    PROTO_SET_CMD_FUNC,
    PROTO_SET_CMD_ID,
)

_LOGGER = logging.getLogger(__name__)


class DeviceManager:
    """
    Pilnībā automātisks Device Manager:

    - pieslēdzas Cloud API
    - ielādē pareizo pb2 pēc device_type
    - inicializē MQTT
    - inicializē EntityGenerator vienu reizi
    - apstrādā MQTT ziņas (runtime values)
    """
    WRITE_FIELD_ALIASES = {
        "en_beep": "cfg_beep_en",
        "cms_max_chg_soc": "cfg_max_chg_soc",
        "cms_min_dsg_soc": "cfg_min_dsg_soc",
        "xboost_en": "cfg_xboost_en",
        "cfg_dc12v_out_open": "cfg_dc_12v_out_open",
        "cfg_dc_12v_out_open": "cfg_dc12v_out_open",
        "plug_in_info_ac_in_chg_pow_max": "cfg_plug_in_info_ac_in_chg_pow_max",
        "cms_oil_self_start": "cfg_cms_oil_self_start",
        "cms_oil_on_soc": "cfg_cms_oil_on_soc",
        "cms_oil_off_soc": "cfg_cms_oil_off_soc",
    }

    def __init__(self, hass: HomeAssistant, config_entry):
        self.hass = hass
        self.entry = config_entry

        self.username = config_entry.data["username"]
        self.password = config_entry.data["password"]

        self.device_label = config_entry.data["device_label"]
        self.device_type = DEVICE_TYPE_MAP[self.device_label]["device_type"]
        self.device_sn = config_entry.data["device_sn"]

        self.client: CloudClient | None = None
        self.entity_generator: EntityGenerator | None = None
        self.pb2_module = None
        self.mqtt: MQTTClient | None = None
        self.user_id: str | None = None
        self.client_id: str | None = None

        # RATE-LIMIT LOGGING
        self._last_log_time = 0.0
        self._log_interval = 10.0  # seconds

        # RATE-LIMIT ENTITY UPDATES
        self._last_update_time = 0.0
        self._update_interval = 0.5  # seconds
        self._pending_decoded: dict | None = None
        self._update_scheduled = False
        self._pending_debug_records: list[dict] = []
        self._debug_flush_scheduled = False
        self._debug_root = Path(self.hass.config.path(f"{DOMAIN}_debug")) / self.device_sn
        self._debug_latest_path = self._debug_root / "latest.json"
        self._debug_history_path = self._debug_root / "history.jsonl"

    # ----------------------------------------------------------------------
    # MAIN SETUP
    # ----------------------------------------------------------------------
    async def async_setup(self):
        """Setup Cloud API + MQTT + PB2 + EntityGenerator."""
        _LOGGER.info("DM: async_setup START for %s (%s)", self.device_label, self.device_sn)

        # 1. Cloud API login
        self.client = CloudClient(
            username=self.username,
            password=self.password,
        )
        try:
            mqtt_info = await self.client.login()
            self.user_id = self.client.user_id
            self.client_id = mqtt_info.client_id
            _LOGGER.info(
                "DM: Cloud login OK: host=%s port=%s user_id=%s",
                mqtt_info.host,
                mqtt_info.port,
                self.user_id,
            )
        except Exception as e:
            _LOGGER.error("DM: Cloud login FAILED: %s", e)
            raise

        # 2. Load pb2 module dynamically
        try:
            await self._load_pb2()
            _LOGGER.info("DM: PB2 loaded OK")
        except Exception as e:
            _LOGGER.error("DM: PB2 load FAILED: %s", e)
            raise

        # 3. Create EntityGenerator ONCE
        try:
            self.entity_generator = EntityGenerator(
                manager=self,
                hass=self.hass,
                device_sn=self.device_sn,
                device_type=self.device_type,
                pb2_module=self.pb2_module,
            )
            _LOGGER.info("DM: EntityGenerator initialized")
        except Exception as e:
            _LOGGER.error("DM: EntityGenerator init FAILED: %s", e)
            raise

        # 4. Setup MQTT after generator exists
        try:
            await self._setup_mqtt(mqtt_info)
            _LOGGER.info("DM: MQTT setup OK")
        except Exception as e:
            _LOGGER.error("DM: MQTT setup FAILED: %s", e)
            raise

        try:
            await self.hass.async_add_executor_job(self._prepare_debug_dump_dir)
            _LOGGER.info("DM: Debug dump path ready at %s", self._debug_root)
        except Exception as e:
            _LOGGER.error("DM: Debug dump setup FAILED: %s", e)
            raise

        try:
            cached_decoded = await self.hass.async_add_executor_job(self._load_cached_decoded_snapshot)
            if cached_decoded and self.entity_generator:
                self.entity_generator.raw_json.update(cached_decoded)
                _LOGGER.info("DM: Restored %s cached telemetry fields", len(cached_decoded))
        except Exception as e:
            _LOGGER.debug("DM: Cached telemetry restore skipped: %s", e)

        # 5. Register device in HA
        try:
            self._register_device()
            _LOGGER.info("DM: Device registered OK")
        except Exception as e:
            _LOGGER.error("DM: Device registration FAILED: %s", e)
            raise

        _LOGGER.info("DM: async_setup END for %s", self.device_sn)
        return True

    # ----------------------------------------------------------------------
    # PB2 LOADING
    # ----------------------------------------------------------------------
    async def _load_pb2(self):
        """Load the correct pb2 module based on DEVICE_TYPE_MAP."""
        try:
            proto_file = DEVICE_TYPE_MAP[self.device_label]["proto"]
        except KeyError:
            raise ValueError(f"Unsupported device_label: {self.device_label}")

        base_pkg = __package__.rsplit(".", 1)[0]
        full_path = f"{base_pkg}.protocol.{proto_file}"

        try:
            self.pb2_module = await self.hass.async_add_executor_job(
                importlib.import_module, full_path
            )
            _LOGGER.debug("DM: Loaded PB2 module: %s", full_path)
        except Exception as e:
            _LOGGER.error("DM: Failed to load PB2 module %s: %s", full_path, e)
            raise

    def _build_mqtt_subscription_topics(self) -> list[str]:
        topics: set[str] = set()
        base = [
            MQTT_TOPIC_DEVICE_PROPERTY.format(sn=self.device_sn),
            MQTT_TOPIC_DEVICE_PROP_LEGACY.format(sn=self.device_sn),
        ]

        for topic in base:
            topics.add(topic)
            topics.add(topic.lstrip("/"))

        if self.user_id:
            user_topic = MQTT_TOPIC_USER_DEVICE_PROPERTY.format(user_id=self.user_id, sn=self.device_sn)
            topics.add(user_topic)
            topics.add(user_topic.lstrip("/"))

        wildcard_user = f"/app/+/device/property/{self.device_sn}"
        topics.add(wildcard_user)
        topics.add(wildcard_user.lstrip("/"))

        return sorted(topics)

    # ----------------------------------------------------------------------
    # MQTT SETUP
    # ----------------------------------------------------------------------
    async def _setup_mqtt(self, mqtt_info):
        """Initialize MQTT client and subscribe to topics."""
        self.mqtt = MQTTClient(
            url=mqtt_info.host,
            port=mqtt_info.port,
            username=mqtt_info.username,
            password=mqtt_info.password,
            client_id=mqtt_info.client_id,
            on_message_callback=self._on_mqtt_message,
        )

        await self.mqtt.async_setup(self.hass)
        _LOGGER.debug("DM: MQTT async_setup completed")

        topics = self._build_mqtt_subscription_topics()
        self.mqtt.subscribe(topics)
        _LOGGER.info("DM: Subscribed to %s MQTT topics", len(topics))
        _LOGGER.debug("DM: MQTT subscription topics: %s", topics)

    # ----------------------------------------------------------------------
    # MQTT MESSAGE HANDLER
    # ----------------------------------------------------------------------
    @callback
    def _on_mqtt_message(self, topic: str, payload: bytes):
        """Handle incoming MQTT messages (called from Paho thread)."""
        now = time.time()

        # Rate-limit logging
        if now - self._last_log_time > self._log_interval:
            _LOGGER.debug("DM: MQTT MESSAGE topic=%s len=%s", topic, len(payload))
            self._last_log_time = now

        if not self.entity_generator:
            _LOGGER.error("DM: EntityGenerator not initialized yet")
            return

        # Decode PROTO
        try:
            decoded = self.entity_generator.decode_message(payload)
        except Exception as e:
            _LOGGER.error("DM: Failed to decode MQTT message: %s", e)
            self._queue_debug_record(
                self._build_debug_record(
                    topic=topic,
                    payload=payload,
                    decoded={},
                    decode_error=str(e),
                )
            )
            return

        self._queue_debug_record(
            self._build_debug_record(
                topic=topic,
                payload=payload,
                decoded=decoded,
            )
        )

        if not decoded:
            return

        if self._pending_decoded:
            self._pending_decoded.update(decoded)
        else:
            self._pending_decoded = dict(decoded)

        if self._update_scheduled:
            return

        self._update_scheduled = True
        self.hass.loop.call_soon_threadsafe(self._apply_pending_update)

    # ----------------------------------------------------------------------
    # APPLY PENDING UPDATE (HA EVENT LOOP)
    # ----------------------------------------------------------------------
    def _apply_pending_update(self):
        """Apply the latest decoded message on HA event loop."""
        payload = self._pending_decoded
        if not payload:
            self._update_scheduled = False
            return

        if not self.entity_generator:
            _LOGGER.error("DM: EntityGenerator not initialized in _apply_pending_update")
            self._update_scheduled = False
            return

        try:
            self._pending_decoded = None
            self.entity_generator.update_entities(payload)
        except Exception as e:
            _LOGGER.error("DM: update_entities FAILED: %s", e)
        finally:
            self._update_scheduled = False
            if self._pending_decoded is not None:
                self._update_scheduled = True
                self.hass.loop.call_soon(self._apply_pending_update)

    def _prepare_debug_dump_dir(self):
        self._debug_root.mkdir(parents=True, exist_ok=True)

    def _load_cached_decoded_snapshot(self) -> dict:
        latest_record = None
        if self._debug_latest_path.exists():
            try:
                latest_payload = json.loads(self._debug_latest_path.read_text(encoding="utf-8"))
                latest_record = latest_payload.get("last_record") if isinstance(latest_payload, dict) else None
            except Exception:
                latest_record = None

        if isinstance(latest_record, dict):
            decoded = latest_record.get("decoded")
            if isinstance(decoded, dict) and decoded:
                return decoded

        if self._debug_history_path.exists():
            try:
                lines = self._debug_history_path.read_text(encoding="utf-8").splitlines()
            except Exception:
                lines = []
            for line in reversed(lines[-200:]):
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                decoded = record.get("decoded") if isinstance(record, dict) else None
                if isinstance(decoded, dict) and decoded:
                    return decoded

        return {}

    def _build_debug_record(
        self,
        topic: str,
        payload: bytes,
        decoded: dict,
        decode_error: str | None = None,
    ) -> dict:
        proto_debug = (
            self.entity_generator.get_last_decode_debug()
            if self.entity_generator and hasattr(self.entity_generator, "get_last_decode_debug")
            else {}
        )
        return {
            "direction": "incoming",
            "received_at": datetime.now(timezone.utc).isoformat(),
            "device_sn": self.device_sn,
            "device_type": self.device_type,
            "topic": topic,
            "payload_len": len(payload),
            "payload_hex": payload.hex(),
            "decoded_field_count": len(decoded or {}),
            "decoded": decoded or {},
            "message_type": getattr(self.entity_generator, "_last_msg_type", None) if self.entity_generator else None,
            "proto_debug": proto_debug,
            "decode_error": decode_error,
        }

    def _build_command_debug_record(
        self,
        field: str,
        write_field: str,
        value,
        topic: str,
        topic_alt: str | None,
        payload: bytes,
        used_proto: bool,
    ) -> dict:
        return {
            "direction": "outgoing",
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "device_sn": self.device_sn,
            "device_type": self.device_type,
            "field": field,
            "write_field": write_field,
            "value": value,
            "used_proto": used_proto,
            "topic": topic,
            "topic_alt": topic_alt,
            "payload_len": len(payload),
            "payload_hex": payload.hex(),
        }

    def _queue_debug_record(self, record: dict):
        self._pending_debug_records.append(record)
        if self._debug_flush_scheduled:
            return

        self._debug_flush_scheduled = True
        self.hass.loop.call_soon_threadsafe(self._flush_debug_records)

    def _flush_debug_records(self):
        records = self._pending_debug_records
        self._pending_debug_records = []
        self._debug_flush_scheduled = False
        if not records:
            return

        self.hass.async_create_task(self._async_write_debug_records(records))

    async def _async_write_debug_records(self, records: list[dict]):
        try:
            await self.hass.async_add_executor_job(self._write_debug_records, records)
        except Exception as exc:
            _LOGGER.error("DM: Failed to write debug dump: %s", exc)

    def _write_debug_records(self, records: list[dict]):
        self._prepare_debug_dump_dir()

        with self._debug_history_path.open("a", encoding="utf-8") as history_file:
            for record in records:
                history_file.write(json.dumps(record, ensure_ascii=False) + "\n")

        latest = {
            "updated_at": records[-1].get("received_at") or records[-1].get("sent_at"),
            "device_sn": self.device_sn,
            "device_type": self.device_type,
            "last_record": records[-1],
        }
        self._debug_latest_path.write_text(
            json.dumps(latest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    # ----------------------------------------------------------------------
    # DEVICE REGISTRATION
    # ----------------------------------------------------------------------
    def _register_device(self):
        device_registry = async_get_device_registry(self.hass)

        device_registry.async_get_or_create(
            config_entry_id=self.entry.entry_id,
            identifiers={(self.entry.domain, self.device_sn)},
            manufacturer="EcoFlow",
            name=self.device_sn,
            model=self.device_type,
        )

        _LOGGER.debug("DM: Registered device %s (%s)", self.device_type, self.device_sn)


    def _build_set_params(self, field: str, value):
        """Build nested params dict from dotted proto field path."""
        parts = [p for p in field.split(".") if p]
        if not parts:
            return {}

        payload = value
        for part in reversed(parts):
            payload = {part: payload}
        return payload

    def _get_set_field_candidates(self, field: str) -> list[str]:
        candidates = [field]
        alias = self.WRITE_FIELD_ALIASES.get(field)
        if alias:
            candidates.append(alias)

        if field.startswith("cfg_"):
            candidates.append(field.removeprefix("cfg_"))
        else:
            candidates.append(f"cfg_{field}")

        if "dc12v" in field:
            candidates.append(field.replace("dc12v", "dc_12v"))
        if "dc_12v" in field:
            candidates.append(field.replace("dc_12v", "dc12v"))

        deduped: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in deduped:
                deduped.append(candidate)
        return deduped

    def _set_first_matching_proto_field(self, msg, field: str, value) -> str:
        last_error = None
        for candidate in self._get_set_field_candidates(field):
            try:
                self._set_proto_field_value(msg, candidate, value)
                return candidate
            except Exception as exc:
                last_error = exc
                continue

        raise ValueError(f"No matching SetCommand field for {field}: {last_error}")

    # ----------------------------------------------------------------------
    def _set_proto_field_value(self, msg, field_path: str, value):
        from google.protobuf.descriptor import FieldDescriptor

        parts = [part for part in field_path.split(".") if part]
        if not parts:
            raise ValueError("empty proto field path")

        current = msg
        for part in parts[:-1]:
            current = getattr(current, part)

        # Cast value to match the proto field type
        last = parts[-1]
        field_desc = current.DESCRIPTOR.fields_by_name.get(last)
        if field_desc:
            int_types = {
                FieldDescriptor.TYPE_INT32, FieldDescriptor.TYPE_INT64,
                FieldDescriptor.TYPE_UINT32, FieldDescriptor.TYPE_UINT64,
                FieldDescriptor.TYPE_SINT32, FieldDescriptor.TYPE_SINT64,
                FieldDescriptor.TYPE_FIXED32, FieldDescriptor.TYPE_FIXED64,
                FieldDescriptor.TYPE_SFIXED32, FieldDescriptor.TYPE_SFIXED64,
                FieldDescriptor.TYPE_BOOL,
            }
            float_types = {FieldDescriptor.TYPE_FLOAT, FieldDescriptor.TYPE_DOUBLE}
            if field_desc.type in int_types:
                value = int(value)
            elif field_desc.type in float_types:
                value = float(value)

        setattr(current, last, value)

    # SEND SET COMMAND
    # ----------------------------------------------------------------------
    async def send_set_command(self, field: str, value) -> bool:
        if not self.mqtt:
            _LOGGER.error("DM: MQTT client not initialized, cannot send set command")
            return False

        write_field = field
        data = {
            "sn": self.device_sn,
            "params": self._build_set_params(write_field, value),
        }

        payload = b""
        used_proto = False

        try:
            proto_prefix = DEVICE_TYPE_MAP[self.device_label]["proto_prefix"]
            cmd_cls = getattr(self.pb2_module, f"{proto_prefix}SetCommand", None) if self.pb2_module else None
            header_cls = getattr(self.pb2_module, f"{proto_prefix}Header", None) if self.pb2_module else None
            send_cls = getattr(self.pb2_module, f"{proto_prefix}SendHeaderMsg", None) if self.pb2_module else None

            if cmd_cls and header_cls and send_cls:
                cmd_msg = cmd_cls()
                write_field = self._set_first_matching_proto_field(cmd_msg, field, value)
                data["params"] = self._build_set_params(write_field, value)

                header = header_cls()
                header.pdata = cmd_msg.SerializeToString()
                header.cmd_func = PROTO_SET_CMD_FUNC
                header.cmd_id = PROTO_SET_CMD_ID
                header.seq = int(time.time()) & 0xFFFF
                header.is_rw_cmd = PROTO_HEADER_IS_RW_CMD
                header.need_ack = PROTO_HEADER_NEED_ACK
                header.time_snap = int(time.time())
                # Module routing: src=32 (cloud/IoT), dest=5 (PD/main controller)
                header.src = PROTO_HEADER_SRC_CLOUD
                header.dest = PROTO_HEADER_DEST_MAIN
                header.d_src = PROTO_HEADER_D_SRC
                header.d_dest = PROTO_HEADER_D_DEST
                if self.device_sn:
                    header.device_sn = self.device_sn
                if self.client_id:
                    try:
                        setattr(header, "from", self.client_id)
                    except (AttributeError, TypeError):
                        pass

                wrapper = send_cls()
                wrapper.msg.append(header)
                payload = wrapper.SerializeToString()
                used_proto = True
                _LOGGER.debug(
                    "DM: PROTO CMD header src=%s dest=%s cmd_func=%s cmd_id=%s seq=%s req_field=%s write_field=%s val=%s payload_hex=%s",
                    header.src, header.dest, header.cmd_func, header.cmd_id, header.seq,
                    field, write_field, value, payload.hex()[:80],
                )
        except Exception as e:
            _LOGGER.debug("DM: Proto command build failed, falling back to JSON: %s", e)

        if not payload:
            if not data["params"]:
                _LOGGER.error("DM: Invalid set command field: %s", field)
                return False

            msg = JSONMessage(data)
            payload = msg.to_mqtt_payload()

            if not payload:
                _LOGGER.error("DM: Empty MQTT payload for set command %s=%s", field, value)
                return False

        # Primary topic same as telemetry topic (App API community-verified).
        # Also send to userId-prefixed topic as fallback in case broker routing differs.
        topic = MQTT_TOPIC_DEVICE_PROPERTY.format(sn=self.device_sn)
        topic_alt = (
            MQTT_TOPIC_USER_DEVICE_PROPERTY.format(
                user_id=self.user_id,
                sn=self.device_sn,
            )
            if self.user_id
            else None
        )

        _LOGGER.debug("DM: SEND SET %s=%s topic=%s proto=%s", field, value, topic, used_proto)
        self._queue_debug_record(
            self._build_command_debug_record(
                field=field,
                write_field=write_field,
                value=value,
                topic=topic,
                topic_alt=topic_alt,
                payload=payload,
                used_proto=used_proto,
            )
        )
        sent_primary = self.mqtt.publish(topic, payload, qos=1)
        sent_alt = False
        if topic_alt and topic_alt != topic:
            sent_alt = self.mqtt.publish(topic_alt, payload, qos=1)

        if not sent_primary and not sent_alt:
            _LOGGER.error("DM: Failed to publish set command %s=%s", field, value)
            return False

        if self.entity_generator and hasattr(self.entity_generator, "register_pending_write"):
            self.entity_generator.register_pending_write(field, value)
            if write_field != field:
                self.entity_generator.register_pending_write(write_field, value)

        return True
