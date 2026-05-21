import logging
from homeassistant.helpers.entity import EntityCategory

from .base import EcoFlowBaseEntity

_LOGGER = logging.getLogger(__name__)


class Diagnostics(EcoFlowBaseEntity):
    """
    EcoFlow diagnostics entity:
    - rāda pilnu raw JSON
    - rāda nezināmos laukus
    - rāda pēdējo MQTT ziņojuma tipu (cmd_func:cmd_id)
    - rāda pēdējo PROTO message tipu (display/runtime/set/cms/bms)
    - rāda pb2 moduļa nosaukumu
    - rāda PROTO prefix
    - rāda entītiju skaitu
    - rāda ierīces info
    """

    _attr_has_entity_name = True
    _attr_name = "Diagnostics"
    _attr_icon = "mdi:information-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, generator, device_sn, device_type):
        super().__init__(
            generator=generator,
            device_sn=device_sn,
            device_type=device_type,
            field="diagnostics",
            meta={
                "name": "Diagnostics",
                "icon": "mdi:information-outline",
                "entity_category": EntityCategory.DIAGNOSTIC,
                "enabled": True,
                "is_control": False,
            },
        )

        self._last_msg_type = None
        self._last_proto_key = None
        self._last_header_hex = None

    # ------------------------------------------------------------------
    # RAW ATTRIBUTES
    # ------------------------------------------------------------------
    @property
    def extra_state_attributes(self):
        attrs = {}

        raw = self.generator.get_raw_json() or {}
        attrs["raw"] = raw

        # Unknown fields
        unknown = []
        for field in raw:
            if field not in self.generator._field_meta:
                unknown.append(field)
        attrs["unknown_fields"] = unknown

        # Proto module
        try:
            attrs["pb2_module"] = self.generator.pb2.__name__
        except Exception:
            attrs["pb2_module"] = None

        # Proto prefix
        try:
            attrs["proto_prefix"] = self.generator.manager.device_label.replace(" ", "")
        except Exception:
            attrs["proto_prefix"] = None

        # Device info
        attrs["device_sn"] = self.device_sn
        attrs["device_type"] = self.device_type
        attrs["device_label"] = getattr(self.generator.manager, "device_label", None)

        # Field count
        attrs["field_count"] = len(raw)

        # Last message info
        attrs["last_message_type"] = self._last_msg_type
        attrs["last_proto_key"] = self._last_proto_key
        attrs["last_header_hex"] = self._last_header_hex

        return attrs

    # ------------------------------------------------------------------
    # VALUE = number of fields
    # ------------------------------------------------------------------
    @property
    def native_value(self):
        raw = self.generator.get_raw_json() or {}
        return len(raw)

    # ------------------------------------------------------------------
    # UPDATE HOOK (called by EntityGenerator)
    # ------------------------------------------------------------------
    def set_last_message_type(self, msg_type: str, proto_key: str = None, header_hex: str = None):
        self._last_msg_type = msg_type
        self._last_proto_key = proto_key
        self._last_header_hex = header_hex
