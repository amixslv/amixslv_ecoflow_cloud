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
    """Set up EcoFlow binary_sensor platform."""
    manager: DeviceManager = hass.data[DOMAIN][entry.entry_id]

    if not manager.entity_generator:
        _LOGGER.error("Binary-Sensor platform: EntityGenerator not initialized")
        return False

    # Reģistrē callback dinamiskai entītiju pievienošanai
    manager.entity_generator.add_entities_callback = async_add_entities

    # Izveido sākotnējās binary_sensor entītijas
    try:
        entities = manager.entity_generator.create_entities("binary_sensor")
        if entities:
            async_add_entities(entities)
        _LOGGER.debug("Binary-Sensor platform: added %s initial binary sensors", len(entities))
    except Exception as e:
        _LOGGER.error("Binary-Sensor platform: failed to create initial binary sensors: %s", e)
        return False

    return True
