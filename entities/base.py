import logging
from homeassistant.helpers.entity import Entity

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
        self._attr_name = meta.get("name", field)
        self._attr_icon = meta.get("icon")
        self._attr_entity_category = meta.get("entity_category")
        self._attr_native_unit_of_measurement = meta.get("unit")
        self._attr_device_class = meta.get("device_class")
        self._attr_state_class = meta.get("state_class")

        # Enable/disable by default
        self._attr_entity_registry_enabled_default = meta.get("enabled", True)

        # Controls sākotnēji uzskatām par pieejamiem,
        # sensoriem pieejamība tiks noteikta pēc vērtības.
        self._attr_available = meta.get("is_control", False)

        # Runtime metadata (firmware, hw, utt.)
        self.runtime_data = {}

    # ------------------------------------------------------------------
    # UNIQUE ID
    # ------------------------------------------------------------------
    @property
    def unique_id(self):
        # SN + proto source + field = stabils, nemainīgs, drošs
        return self._meta.get("unique_id", f"{self.device_sn}_{self._field}")

    @property
    def suggested_object_id(self):
        # Keep entity_id deterministic and short: <device_type>_<field_path>
        field_path = (self._meta.get("field_path") or self._field).replace(".", "_").lower()
        device_key = (self.device_type or "ecoflow").replace(" ", "_").lower()
        return f"{device_key}_{field_path}"

    # ------------------------------------------------------------------
    # DEVICE INFO
    # ------------------------------------------------------------------
    @property
    def device_info(self):
        # Cilvēciskais nosaukums (Delta 3 Plus)
        try:
            human_name = self.generator.manager.device_label
        except Exception:
            human_name = self.device_type

        info = {
            "identifiers": {("amixslv_ecoflow_cloud", self.device_sn)},
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
            info["via_device"] = ("amixslv_ecoflow_cloud", f"{self.device_sn}_bms")

        if "ip" in rd:
            info["connections"] = {("ip", rd["ip"])}

        if hasattr(self, "_meta") and "device_override" in self._meta:
            dev_id = self._meta["device_override"]
            return {
                "identifiers": {("amixslv_ecoflow_cloud", dev_id)},
                "manufacturer": "EcoFlow",
                "model": "Extra Battery",
                "name": f"Extra Battery {dev_id.split('_')[-1]}",
                "via_device": ("amixslv_ecoflow_cloud", self.device_sn),
            }

        return info

    # ------------------------------------------------------------------
    # AVAILABILITY
    # ------------------------------------------------------------------
    @property
    def available(self):
        # Controls vienmēr pieejami
        if self._meta.get("is_control"):
            return True

        # Sensori pieejami, ja tiem ir pēdējā zināmā vērtība
        # (update_entities() iestata _attr_native_value / _attr_is_on)
        if hasattr(self, "_attr_native_value"):
            return self._attr_native_value is not None

        if hasattr(self, "_attr_is_on"):
            # binary_sensor / switch – ja nekad nav bijis stāvoklis, uzskatām par nepieejamu
            return self._attr_is_on is not None

        return True
