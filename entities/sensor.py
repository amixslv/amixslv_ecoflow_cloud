import logging
from homeassistant.components.sensor import SensorEntity

from .base import EcoFlowBaseEntity

_LOGGER = logging.getLogger(__name__)


class Sensor(EcoFlowBaseEntity, SensorEntity):
    """EcoFlow sensor entity (PROTO-first)."""

    def __init__(self, generator, device_sn, device_type, field, meta):
        super().__init__(generator, device_sn, device_type, field, meta)

        # Vērtība tiks iestatīta update_entities() pusē
        self._attr_native_value = None

    @property
    def native_value(self):
        """Atgriež pēdējo iestatīto vērtību."""
        return self._attr_native_value
