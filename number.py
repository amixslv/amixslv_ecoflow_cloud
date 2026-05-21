from __future__ import annotations
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry

from . import DOMAIN
from .core.device_manager import DeviceManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up EcoFlow number platform."""
    manager: DeviceManager = hass.data[DOMAIN][entry.entry_id]

    if not manager.entity_generator:
        _LOGGER.error("Number platform: EntityGenerator not initialized")
        return False

    # Reģistrē callback dinamiskai entītiju pievienošanai
    manager.entity_generator.add_entities_callback = async_add_entities

    # Izveido sākotnējās number entītijas
    try:
        entities = manager.entity_generator.create_entities("number")
        if entities:
            async_add_entities(entities)
        _LOGGER.debug("Number platform: added %s initial numbers", len(entities))
    except Exception as e:
        _LOGGER.error("Number platform: failed to create initial numbers: %s", e)
        return False

    return True
