import logging
from homeassistant.components.button import ButtonEntity

from .base import EcoFlowBaseEntity

_LOGGER = logging.getLogger(__name__)


class Button(EcoFlowBaseEntity, ButtonEntity):
    """EcoFlow button entity (PROTO-first)."""

    async def async_press(self):
        """Send action command to EcoFlow Cloud."""
        await self.generator.manager.send_set_command(self._field, 1)
