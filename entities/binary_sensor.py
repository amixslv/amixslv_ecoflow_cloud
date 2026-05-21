import logging
from homeassistant.components.binary_sensor import BinarySensorEntity
from .base import EcoFlowBaseEntity

_LOGGER = logging.getLogger(__name__)


class BinarySensor(EcoFlowBaseEntity, BinarySensorEntity):
    """EcoFlow binary sensor entity (PROTO-first)."""

    def __init__(self, generator, device_sn, device_type, field, meta):
        super().__init__(generator, device_sn, device_type, field, meta)
        self._attr_is_on = None  # vērtība tiks iestatīta update_entities()

    @property
    def is_on(self):
        return self._attr_is_on
