import asyncio
import json
import logging
import time
from datetime import datetime, timezone
import importlib
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
    MQTT_TOPIC_USER_THING_PROPERTY_GET,
    MQTT_TOPIC_USER_THING_PROPERTY_GET_REPLY,
    MQTT_TOPIC_USER_THING_PROPERTY_SET,
    MQTT_TOPIC_USER_THING_PROPERTY_SET_REPLY,
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

        self._pending_debug_records: list[dict] = []
        self._debug_flush_scheduled = False
        self._debug_root = Path(self.hass.config.path(f"{DOMAIN}_debug")) / self.device_sn
        self._debug_latest_path = self._debug_root / "latest.json"
        self._debug_history_path = self._debug_root / "history.jsonl"
        self._last_real_telemetry_at = 0.0
        self._snapshot_task: asyncio.Task | None = None

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

        # 5. Register device in HA
        try:
            self._register_device()
            _LOGGER.info("DM: Device registered OK")
        except Exception as e:
            _LOGGER.error("DM: Device registration FAILED: %s", e)
            raise

        if not self._snapshot_task:
            self._snapshot_task = self.hass.async_create_task(self._snapshot_watchdog())

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

        topic1 = MQTT_TOPIC_DEVICE_PROPERTY.format(sn=self.device_sn)
        topic2 = MQTT_TOPIC_DEVICE_PROP_LEGACY.format(sn=self.device_sn)
        topic_get_reply = (
            MQTT_TOPIC_USER_THING_PROPERTY_GET_REPLY.format(
                user_id=self.user_id,
                sn=self.device_sn,
            )
            if self.user_id
            else None
        )
        topic_set_reply = (
            MQTT_TOPIC_USER_THING_PROPERTY_SET_REPLY.format(
                user_id=self.user_id,
                sn=self.device_sn,
            )
            if self.user_id
            else None
        )
        topics = [
            topic1,
            topic2,
            topic1.lstrip("/"),
            topic2.lstrip("/"),
            "/app/device/property/+",
            "app/device/property/+",
        ]

        if self.user_id:
            topic3 = MQTT_TOPIC_USER_DEVICE_PROPERTY.format(
                user_id=self.user_id, sn=self.device_sn
            )
            topics.extend(
                [
                    topic3,
                    topic3.lstrip("/"),
                    topic_get_reply,
                    topic_get_reply.lstrip("/"),
                    topic_set_reply,
                    topic_set_reply.lstrip("/"),
                    f"/app/{self.user_id}/device/property/+",
                    f"app/{self.user_id}/device/property/+",
                ]
            )
            _LOGGER.info("DM: Subscribed to topics: %s", topics)
        else:
            _LOGGER.info("DM: Subscribed to topics %s and %s (no user_id)", topic1, topic2)

        self.mqtt.subscribe(topics)

    # ----------------------------------------------------------------------
    # MQTT MESSAGE HANDLER
    # ----------------------------------------------------------------------
    @callback
    def _on_mqtt_message(self, topic: str, payload: bytes):
        """Handle incoming MQTT messages (called from Paho thread)."""
        _LOGGER.debug("DM: MQTT MESSAGE topic=%s len=%s", topic, len(payload))

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

        debug = self.entity_generator.get_last_decode_debug()
        header = debug.get("header") or {}
        src = header.get("src")
        if topic.endswith("/thing/property/get_reply") or (src is not None and src != PROTO_HEADER_SRC_CLOUD):
            self._last_real_telemetry_at = time.time()

        self.hass.loop.call_soon_threadsafe(self._apply_decoded_update, decoded)

    async def _snapshot_watchdog(self):
        await asyncio.sleep(2)
        while True:
            try:
                if self.mqtt and self.mqtt.connected:
                    idle_for = time.time() - self._last_real_telemetry_at
                    if self._last_real_telemetry_at == 0.0 or idle_for >= 2.0:
                        await self._request_full_snapshot()
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _LOGGER.error("DM: Snapshot watchdog failed: %s", exc)
                await asyncio.sleep(2)

    async def _request_full_snapshot(self):
        if not self.mqtt or not self.user_id:
            return

        payload = self._build_full_snapshot_payload()
        if not payload:
            return

        topic = MQTT_TOPIC_USER_THING_PROPERTY_GET.format(
            user_id=self.user_id,
            sn=self.device_sn,
        )
        _LOGGER.debug("DM: REQUEST SNAPSHOT topic=%s", topic)
        self.mqtt.publish(topic, payload, qos=1)

    def _build_full_snapshot_payload(self) -> bytes:
        try:
            proto_prefix = DEVICE_TYPE_MAP[self.device_label]["proto_prefix"]
            header_cls = getattr(self.pb2_module, f"{proto_prefix}Header", None) if self.pb2_module else None
            send_cls = getattr(self.pb2_module, f"{proto_prefix}SendHeaderMsg", None) if self.pb2_module else None
            if not header_cls or not send_cls:
                return b""

            header = header_cls()
            header.src = PROTO_HEADER_SRC_CLOUD
            header.dest = PROTO_HEADER_SRC_CLOUD
            header.seq = int(time.time() * 1000) & 0x7FFFFFFF
            if self.device_sn:
                header.device_sn = self.device_sn
            try:
                setattr(header, "from", self.client_id or "HomeAssistant")
            except (AttributeError, TypeError):
                pass

            wrapper = send_cls()
            wrapper.msg.append(header)
            return wrapper.SerializeToString()
        except Exception as exc:
            _LOGGER.error("DM: Failed to build snapshot payload: %s", exc)
            return b""

    # ----------------------------------------------------------------------
    # APPLY PENDING UPDATE (HA EVENT LOOP)
    # ----------------------------------------------------------------------
    def _apply_decoded_update(self, payload: dict):
        """Apply decoded message on HA event loop immediately."""
        if not self.entity_generator:
            _LOGGER.error("DM: EntityGenerator not initialized in _apply_decoded_update")
            return

        try:
            self.entity_generator.update_entities(payload)
        except Exception as e:
            _LOGGER.error("DM: update_entities FAILED: %s", e)

    def _prepare_debug_dump_dir(self):
        self._debug_root.mkdir(parents=True, exist_ok=True)

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

        self._prune_debug_history(max_age_hours=3)

    def _prune_debug_history(self, max_age_hours: int = 3):
        """Remove history entries older than max_age_hours."""
        if not self._debug_history_path.exists():
            return
        cutoff = time.time() - max_age_hours * 3600
        kept: list[str] = []
        try:
            with self._debug_history_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        ts_str = rec.get("received_at") or rec.get("sent_at") or ""
                        if ts_str:
                            ts = datetime.fromisoformat(ts_str).timestamp()
                        else:
                            ts = cutoff  # unknown → keep on the boundary
                        if ts >= cutoff:
                            kept.append(line)
                    except Exception:
                        kept.append(line)  # malformed → keep to avoid data loss
        except Exception as exc:
            _LOGGER.warning("DM: Could not prune debug history: %s", exc)
            return
        with self._debug_history_path.open("w", encoding="utf-8") as fh:
            for line in kept:
                fh.write(line + "\n")

        latest = {
            "updated_at": records[-1]["received_at"],
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

        if len(parts) >= 2 and parts[-1].isdigit():
            index = int(parts[-1])
            list_field = parts[-2]
            base_path = ".".join(parts[:-1])
            list_payload = self._build_repeated_scalar_payload(base_path, index, value)
            payload = {list_field: list_payload}
            for part in reversed(parts[:-2]):
                payload = {part: payload}
            return payload

        payload = value
        for part in reversed(parts):
            payload = {part: payload}
        return payload

    # ----------------------------------------------------------------------
    def _set_proto_field_value(self, msg, field_path: str, value):
        from google.protobuf.descriptor import FieldDescriptor

        parts = [part for part in field_path.split(".") if part]
        if not parts:
            raise ValueError("empty proto field path")

        # Repeated scalar slot: cfg_tou_strategy.tou_hours_strategy.<index>
        if len(parts) >= 2 and parts[-1].isdigit():
            index = int(parts[-1])
            repeated_name = parts[-2]
            repeated_base_path = ".".join(parts[:-1])
            current = msg
            for part in parts[:-2]:
                current = getattr(current, part)

            field_desc = current.DESCRIPTOR.fields_by_name.get(repeated_name)
            if not field_desc:
                raise ValueError(f"unknown repeated field: {repeated_name}")

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

            repeated_field = getattr(current, repeated_name)
            values = self._build_repeated_scalar_payload(repeated_base_path, index, value)
            repeated_field.extend(values)
            return

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

    def _build_repeated_scalar_payload(self, base_path: str, index: int, value):
        values_by_index: dict[int, float | int | str] = {}
        max_index = index

        if self.entity_generator and hasattr(self.entity_generator, "get_raw_json"):
            raw_json = self.entity_generator.get_raw_json() or {}
            prefixes = [f"{base_path}."]
            if base_path.startswith("cfg_"):
                prefixes.append(f"{base_path.removeprefix('cfg_')}.")
            for key, cached in raw_json.items():
                for prefix in prefixes:
                    if not key.startswith(prefix):
                        continue
                    suffix = key[len(prefix):]
                    if not suffix.isdigit():
                        continue
                    idx = int(suffix)
                    values_by_index[idx] = cached
                    if idx > max_index:
                        max_index = idx
                    break

        values = [0] * (max_index + 1)
        for idx, cached in values_by_index.items():
            if 0 <= idx <= max_index:
                values[idx] = cached
        values[index] = value
        return values

    @staticmethod
    def _is_true_value(value) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "on", "yes")
        return False

    @staticmethod
    def _is_tou_mode_field(field: str) -> bool:
        return field == "cfg_energy_strategy_operate_mode.operate_tou_mode_open"

    @staticmethod
    def _is_self_powered_field(field: str) -> bool:
        return field in {
            "cms_oil_self_start",
            "cfg_energy_strategy_operate_mode.operate_self_powered_open",
        }

    async def _send_set_command_internal(self, field: str, value):
        if not self.mqtt:
            _LOGGER.error("DM: MQTT client not initialized, cannot send set command")
            return False

        data = {
            "sn": self.device_sn,
            "params": self._build_set_params(field, value),
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
                self._set_proto_field_value(cmd_msg, field, value)

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
                    "DM: PROTO CMD header src=%s dest=%s cmd_func=%s cmd_id=%s seq=%s field=%s val=%s payload_hex=%s",
                    header.src, header.dest, header.cmd_func, header.cmd_id, header.seq,
                    field, value, payload.hex()[:80],
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
        set_topic = (
            MQTT_TOPIC_USER_THING_PROPERTY_SET.format(
                user_id=self.user_id,
                sn=self.device_sn,
            )
            if self.user_id
            else None
        )
        published = False
        if set_topic:
            published = self.mqtt.publish(set_topic, payload, qos=1) or published
        published = self.mqtt.publish(topic, payload, qos=0) or published
        if topic_alt and topic_alt != topic:
            published = self.mqtt.publish(topic_alt, payload, qos=0) or published

        if published and self.entity_generator:
            # Keep UI stable while broker/device sends delayed snapshots.
            self.entity_generator.register_pending_write(field, value, ttl_seconds=5.0)
            if field.startswith("cfg_energy_backup."):
                self.entity_generator.register_pending_write(
                    field.split(".", 1)[1], value, ttl_seconds=5.0
                )
            elif field == "cfg_dc12v_out_open":
                self.entity_generator.register_pending_write("dc_out_open", value, ttl_seconds=5.0)
            elif field == "cfg_led_mode":
                self.entity_generator.register_pending_write("led_mode", value, ttl_seconds=5.0)
            elif field.startswith("cfg_"):
                self.entity_generator.register_pending_write(
                    field.removeprefix("cfg_"), value, ttl_seconds=5.0
                )

        return published

    # SEND SET COMMAND
    # ----------------------------------------------------------------------
    async def send_set_command(self, field: str, value):
        published = await self._send_set_command_internal(field, value)
        if not published:
            return False

        # TOU un Self-powered ir savstarpēji ekskluzīvi režīmi.
        if self._is_true_value(value) and self._is_tou_mode_field(field):
            if not await self._send_set_command_internal("cfg_energy_strategy_operate_mode.operate_self_powered_open", 0):
                await self._send_set_command_internal("cms_oil_self_start", 0)
        elif self._is_true_value(value) and self._is_self_powered_field(field):
            await self._send_set_command_internal("cfg_energy_strategy_operate_mode.operate_tou_mode_open", 0)

        return True
