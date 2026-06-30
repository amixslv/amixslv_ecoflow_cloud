import logging
import importlib
import time

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import async_get as async_get_device_registry

from ..api.cloud_client import CloudClient
from ..api.mqtt_client import MQTTClient
from ..core.entity_generator import EntityGenerator
from ..supported_devices import DEVICE_TYPE_MAP
from ..api.message import JSONMessage

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

        # RATE-LIMIT LOGGING
        self._last_log_time = 0.0
        self._log_interval = 10.0  # seconds

        # RATE-LIMIT ENTITY UPDATES
        self._last_update_time = 0.0
        self._update_interval = 0.5  # seconds
        self._pending_decoded: dict | None = None
        self._update_scheduled = False

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

        full_path = f"custom_components.amixslv_ecoflow_cloud.protocol.{proto_file}"

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

        topic1 = f"/app/device/property/{self.device_sn}"
        topic2 = f"/app/device/prop/{self.device_sn}"

        self.mqtt.subscribe([topic1, topic2])
        _LOGGER.info("DM: Subscribed to topics %s and %s", topic1, topic2)

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
            return

        if not decoded:
            return

        self._pending_decoded = decoded

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
    async def send_set_command(self, field: str, value):
        if not self.mqtt:
            _LOGGER.error("DM: MQTT client not initialized, cannot send set command")
            return

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
                header.cmd_func = 254
                header.cmd_id = 17
                header.seq = int(time.time()) & 0xFFFF
                header.is_rw_cmd = 1
                header.need_ack = 1
                header.time_snap = int(time.time())
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
        except Exception as e:
            _LOGGER.debug("DM: Proto command build failed, falling back to JSON: %s", e)

        if not payload:
            if not data["params"]:
                _LOGGER.error("DM: Invalid set command field: %s", field)
                return

            msg = JSONMessage(data)
            payload = msg.to_mqtt_payload()

            if not payload:
                _LOGGER.error("DM: Empty MQTT payload for set command %s=%s", field, value)
                return

        if self.user_id:
            topic = f"/app/{self.user_id}/device/property/{self.device_sn}"
        else:
            topic = f"/app/device/property/{self.device_sn}"

        _LOGGER.debug("DM: SEND SET %s=%s ? topic=%s proto=%s", field, value, topic, used_proto)
        self.mqtt.publish(topic, payload)
