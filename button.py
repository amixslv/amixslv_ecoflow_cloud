from __future__ import annotations
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry

from .cont import DOMAIN
from .core.device_manager import DeviceManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up EcoFlow button platform."""
    manager: DeviceManager = hass.data[DOMAIN][entry.entry_id]

    if not manager.entity_generator:
        _LOGGER.error("Button platform: EntityGenerator not initialized")
        return False

    manager.entity_generator.set_platform_callback("button", async_add_entities)

    try:
        entities = manager.entity_generator.create_entities("button")
        if entities:
            async_add_entities(entities)
        _LOGGER.debug("Button platform: added %s initial buttons", len(entities))
    except Exception as e:
        _LOGGER.error("Button platform: failed to create initial buttons: %s", e)
        return False

    return True
