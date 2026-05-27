import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .cont import DOMAIN, PLATFORMS
from .core.device_manager import DeviceManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up integration from a config entry."""
    manager = DeviceManager(hass, entry)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = manager

    try:
        await manager.async_setup()
    except Exception as e:
        _LOGGER.error(f"Failed to set up EcoFlow manager: {e}")
        return False

    # ←←← ŠIS IR KRITISKI SVARĪGI
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload integration."""
    manager: DeviceManager = hass.data[DOMAIN].get(entry.entry_id)

    if manager and hasattr(manager, "mqtt"):
        await manager.mqtt.async_unload()

    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    hass.data[DOMAIN].pop(entry.entry_id, None)

    return True
