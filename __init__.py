import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import async_get as async_get_device_registry

from .cont import DOMAIN, PLATFORMS
from .core.device_manager import DeviceManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up integration from a config entry."""
    manager = DeviceManager(hass, entry)

    hass.data.setdefault(DOMAIN, {})
    hass.data.setdefault(LEGACY_DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = manager
    hass.data[LEGACY_DOMAIN][entry.entry_id] = manager

    try:
        await manager.async_setup()
    except Exception as e:
        _LOGGER.error(f"Failed to set up EcoFlow manager: {e}")
        return False

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload integration."""
    manager: DeviceManager | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if manager is None:
        manager = hass.data.get(LEGACY_DOMAIN, {}).get(entry.entry_id)

    if manager and hasattr(manager, "mqtt"):
        await manager.mqtt.async_unload(hass)

    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    hass.data.get(LEGACY_DOMAIN, {}).pop(entry.entry_id, None)

    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Remove integration and clean up entities."""
    dev_registry = async_get_device_registry(hass)

    devices_to_remove = [
        device for device in dev_registry.devices.values()
        if entry.entry_id in device.config_entries
    ]

    for device in devices_to_remove:
        dev_registry.async_remove_device(device.id)
