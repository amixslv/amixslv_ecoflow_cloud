import logging
from homeassistant.components.switch import SwitchEntity

from .base import EcoFlowBaseEntity

_LOGGER = logging.getLogger(__name__)


class Switch(EcoFlowBaseEntity, SwitchEntity):
    """EcoFlow switch entity (PROTO-first)."""

    def __init__(self, generator, device_sn, device_type, field, meta):
        super().__init__(generator, device_sn, device_type, field, meta)
        self._attr_is_on = None

        # If we already have a known value in the cumulative proto snapshot, use it.
        state_paths = meta.get("state_field_paths") or [field]
        for candidate in state_paths:
            val = generator.get_field_value(candidate)
            if isinstance(val, bool):
                self._attr_is_on = val
                self._has_known_state = True
                break
            if isinstance(val, (int, float)):
                self._attr_is_on = val != 0
                self._has_known_state = True
                break

    @property
    def is_on(self):
        return self._attr_is_on

    async def async_turn_on(self, **kwargs):
        """Send SET command to EcoFlow Cloud."""
        sent = await self.generator.manager.send_set_command(self._field, 1)
        if not sent:
            return

        # Uzreiz atjaunojam UI (pirms MQTT atnāk atpakaļ)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Send SET command to EcoFlow Cloud."""
        sent = await self.generator.manager.send_set_command(self._field, 0)
        if not sent:
            return

        # Uzreiz atjaunojam UI (pirms MQTT atnāk atpakaļ)
        self._attr_is_on = False
        self.async_write_ha_state()
