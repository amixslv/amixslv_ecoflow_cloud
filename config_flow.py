from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry as dr, entity_registry as er

from . import DOMAIN
from .supported_devices import SUPPORTED_DEVICE_LABELS, DEVICE_TYPE_MAP
from .api.cloud_client import CloudClient


class EcoflowConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for amixslv_ecoflow_cloud."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Step 1: Ask for username/password and VALIDATE login."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required("username"): str,
                        vol.Required("password"): str,
                    }
                ),
            )

        self._username = user_input["username"]
        self._password = user_input["password"]

        # --- LOGIN VALIDATION ---
        errors = {}
        try:
            self._client = CloudClient(
                username=self._username,
                password=self._password,
            )
            await self._client.login()
        except Exception:
            errors["base"] = "invalid_auth"
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required("username", default=self._username): str,
                        vol.Required("password"): str,
                    }
                ),
                errors=errors,
            )

        return await self.async_step_device()

    async def async_step_device(self, user_input=None) -> FlowResult:
        """Step 2: Select device label + SN."""
        if user_input is None:
            return self.async_show_form(
                step_id="device",
                data_schema=vol.Schema(
                    {
                        vol.Required("device_label"): vol.In(SUPPORTED_DEVICE_LABELS),
                        vol.Required("device_sn"): str,
                    }
                ),
            )

        self._device_label = user_input["device_label"]
        self._device_sn = user_input["device_sn"]

        # Check if device already exists in registry
        device_registry = dr.async_get(self.hass)
        for dev in device_registry.devices.values():
            if (DOMAIN, self._device_sn) in dev.identifiers:
                return await self.async_step_device_exists()

        return self._create_entry()

    async def async_step_device_exists(self, user_input=None) -> FlowResult:
        """Ask user whether to keep or reset existing device."""
        if user_input is None:
            return self.async_show_form(
                step_id="device_exists",
                description_placeholders={"sn": self._device_sn},
                data_schema=vol.Schema(
                    {
                        vol.Required("action", default="keep"): vol.In(
                            {
                                "keep": "Paturēt esošo konfigurāciju",
                                "reset": "Dzēst veco un uzstādīt no jauna",
                            }
                        )
                    }
                ),
            )

        action = user_input["action"]

        if action == "reset":
            await self._delete_old_device_and_entities()

        return self._create_entry()

    async def _delete_old_device_and_entities(self):
        """Delete old device + all its entities safely."""
        device_registry = dr.async_get(self.hass)
        entity_registry = er.async_get(self.hass)

        # Remove entities
        for entity in list(entity_registry.entities.values()):
            if entity.unique_id.startswith(self._device_sn):
                entity_registry.async_remove(entity.entity_id)

        # Remove device
        for dev in list(device_registry.devices.values()):
            if (DOMAIN, self._device_sn) in dev.identifiers:
                device_registry.async_remove_device(dev.id)

    def _create_entry(self) -> FlowResult:
        """Create final config entry."""
        return self.async_create_entry(
            title=f"{self._device_label} ({self._device_sn})",
            data={
                "mode": "cloud",
                "api_host": "api.ecoflow.com",
                "username": self._username,
                "password": self._password,
                "device_label": self._device_label,
                "device_type": DEVICE_TYPE_MAP[self._device_label]["device_type"],
                "device_sn": self._device_sn,
            },
        )
