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
    """Set up EcoFlow select platform."""
    manager: DeviceManager = hass.data[DOMAIN][entry.entry_id]

    if not manager.entity_generator:
        _LOGGER.error("Select platform: EntityGenerator not initialized")
        return False

    # Reģistrē callback dinamiskai entītiju pievienošanai
    manager.entity_generator.add_entities_callback = async_add_entities

    # Izveido sākotnējās select entītijas
    try:
        entities = manager.entity_generator.create_entities("select")
        if entities:
            async_add_entities(entities)
        _LOGGER.debug("Select platform: added %s initial selects", len(entities))
    except Exception as e:
        _LOGGER.error("Select platform: failed to create initial selects: %s", e)
        return False

    return True
