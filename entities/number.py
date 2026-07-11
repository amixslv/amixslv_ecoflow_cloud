import logging
from homeassistant.components.number import NumberEntity

from .base import EcoFlowBaseEntity

_LOGGER = logging.getLogger(__name__)


class Number(EcoFlowBaseEntity, NumberEntity):
    """EcoFlow number entity (PROTO-first)."""

    def __init__(self, generator, device_sn, device_type, field, meta):
        super().__init__(generator, device_sn, device_type, field, meta)

        self._attr_native_value = None  # vērtība tiks iestatīta update_entities()
        self._attr_native_min_value = meta.get("min")
        self._attr_native_max_value = meta.get("max")
        self._attr_native_step = meta.get("step")

    @property
    def native_value(self):
        return self._attr_native_value

    async def async_set_native_value(self, value):
        """Send SET command to EcoFlow Cloud."""
        sent = await self.generator.manager.send_set_command(self._field, value)
        if not sent:
            return

        # Uzreiz atjaunojam UI (pirms MQTT atnāk atpakaļ)
        self._attr_native_value = value
        self.async_write_ha_state()
