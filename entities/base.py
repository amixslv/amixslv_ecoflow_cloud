import logging
from homeassistant.helpers.entity import Entity

from ..cont import DOMAIN, LEGACY_DOMAIN

_LOGGER = logging.getLogger(__name__)


class EcoFlowBaseEntity(Entity):
    """Common base class for all EcoFlow entities (PROTO-first)."""

    def __init__(self, generator, device_sn, device_type, field, meta):
        self.generator = generator
        self.device_sn = device_sn
        self.device_type = device_type
        self._field = field
        self._meta = meta

        # -----------------------------
        # BASIC ATTRIBUTES
        # -----------------------------
        self._attr_has_entity_name = False
        self._attr_name = meta.get("name", field)
        self._attr_icon = meta.get("icon")
        self._attr_entity_category = meta.get("entity_category")
        self._attr_native_unit_of_measurement = meta.get("unit")
        self._attr_device_class = meta.get("device_class")
        self._attr_state_class = meta.get("state_class")

        # Enable/disable by default
        self._attr_entity_registry_enabled_default = meta.get("enabled", True)

        # Controls sĆ„ĀkotnĆ„ā€ji uzskatĆ„Ām par pieejamiem,
        # sensoriem pieejamĆ„Ā«ba tiks noteikta pĆ„ā€c vĆ„ā€rtĆ„Ā«bas.
        self._attr_available = meta.get("is_control", False)

        # Runtime metadata (firmware, hw, utt.)
        self.runtime_data = {}

    # ------------------------------------------------------------------
    # UNIQUE ID
    # ------------------------------------------------------------------
    @property
    def unique_id(self):
        # SN + proto source + field = stabils, nemainĆ„Ā«gs, droĆ…ļ£¼s
        return self._meta.get("unique_id", f"{self.device_sn}_{self._field}")

    @property
    def suggested_object_id(self):
        # Use field_path only (already unique across proto sources)
        return (self._meta.get("field_path") or self._field).replace(".", "_").lower()

    @property
    def device_info(self):
        # CilvĆ„ā€ciskais nosaukums (Delta 3 Plus)
        try:
            human_name = self.generator.manager.device_label
        except Exception:
            human_name = self.device_type

        info = {
            "identifiers": {(DOMAIN, self.device_sn), (LEGACY_DOMAIN, self.device_sn)},
            "manufacturer": "EcoFlow",
            "model": human_name,
            "name": human_name,
            "serial_number": self.device_sn,
        }

        rd = self.runtime_data or {}

        if "fw_version" in rd:
            info["sw_version"] = rd["fw_version"]

        if "hw_version" in rd:
            info["hw_version"] = rd["hw_version"]

        if "bms_version" in rd:
            info["via_device"] = (DOMAIN, f"{self.device_sn}_bms")

        if "ip" in rd:
            info["connections"] = {("ip", rd["ip"])}

        if hasattr(self, "_meta") and "device_override" in self._meta:
            dev_id = self._meta["device_override"]
            return {
                "identifiers": {(DOMAIN, dev_id), (LEGACY_DOMAIN, dev_id)},
                "manufacturer": "EcoFlow",
                "model": "Extra Battery",
                "name": f"Extra Battery {dev_id.split('_')[-1]}",
                "via_device": (DOMAIN, self.device_sn),
            }

        return info

    # ------------------------------------------------------------------
    # AVAILABILITY
    # ------------------------------------------------------------------
    @property
    def available(self):
        # Controls vienmĆ„ā€r pieejami
        if self._meta.get("is_control"):
            return True

        # Sensori pieejami, ja tiem ir pĆ„ā€dĆ„ā€jĆ„Ā zinĆ„ĀmĆ„Ā vĆ„ā€rtĆ„Ā«ba
        # (update_entities() iestata _attr_native_value / _attr_is_on)
        if hasattr(self, "_attr_native_value"):
            return self._attr_native_value is not None

        if hasattr(self, "_attr_is_on"):
            # binary_sensor / switch Äā‚¬ā€ ja nekad nav bijis stĆ„Āvoklis, uzskatĆ„Ām par nepieejamu
            return self._attr_is_on is not None

        return True

