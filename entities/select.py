import logging
from homeassistant.components.select import SelectEntity

from .base import EcoFlowBaseEntity

_LOGGER = logging.getLogger(__name__)


class Select(EcoFlowBaseEntity, SelectEntity):
    """EcoFlow select entity (PROTO-first)."""

    def __init__(self, generator, device_sn, device_type, field, meta):
        super().__init__(generator, device_sn, device_type, field, meta)
        self._attr_options = meta.get("options", [])
        self._attr_current_option = None  # vērtība tiks iestatīta update_entities()

    # ------------------------------------------------------------------
    # CURRENT OPTION
    # ------------------------------------------------------------------
    @property
    def current_option(self):
        return self._attr_current_option

    # ------------------------------------------------------------------
    # SET OPTION
    # ------------------------------------------------------------------
    async def async_select_option(self, option):
        """Send SET command to EcoFlow Cloud."""

        if option not in self._attr_options:
            _LOGGER.warning("Invalid option '%s' for %s", option, self._field)
            return

        # ENUM (index)
        try:
            index = self._attr_options.index(option)
            send_value = index
        except Exception:
            # STRING
            send_value = option

        sent = await self.generator.manager.send_set_command(self._field, send_value)
        if not sent:
            return

        # Uzreiz atjaunojam UI (pirms MQTT atnāk atpakaļ)
        self._attr_current_option = option
        self.async_write_ha_state()
