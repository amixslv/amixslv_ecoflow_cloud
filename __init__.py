import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .cont import DOMAIN, LEGACY_DOMAIN, PLATFORMS
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

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload integration."""
    manager: DeviceManager = hass.data[DOMAIN].get(entry.entry_id)

    if manager and getattr(manager, "_snapshot_task", None):
        manager._snapshot_task.cancel()

    if manager and hasattr(manager, "mqtt"):
        await manager.mqtt.async_unload()

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unloaded:
        return False

    hass.data[DOMAIN].pop(entry.entry_id, None)

    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove integration data from HA registries when entry is deleted."""
    _purge_registry_data(hass, entry)


def _purge_registry_data(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete registry entities/devices that belong to this config entry."""
    entity_registry = er.async_get(hass)
    for entity in list(er.async_entries_for_config_entry(entity_registry, entry.entry_id)):
        entity_registry.async_remove(entity.entity_id)

    device_registry = dr.async_get(hass)
    devices_to_remove = list(dr.async_entries_for_config_entry(device_registry, entry.entry_id))

    device_sn = entry.data.get("device_sn")
    if device_sn:
        for dev in list(device_registry.devices.values()):
            if (
                (DOMAIN, device_sn) in dev.identifiers
                or (LEGACY_DOMAIN, device_sn) in dev.identifiers
            ) and dev not in devices_to_remove:
                devices_to_remove.append(dev)

    for dev in devices_to_remove:
        device_registry.async_remove_device(dev.id)
