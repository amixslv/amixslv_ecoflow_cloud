from __future__ import annotations

import re
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .cont import DOMAIN
from .supported_devices import SUPPORTED_DEVICE_LABELS, DEVICE_TYPE_MAP
from .api.cloud_client import CloudClient


class EcoflowConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for amixslv_ecoflow_cloud."""

    VERSION = 1

    def __init__(self) -> None:
        self._cloud_devices: dict[str, dict] = {}

    def _normalize_name(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.lower())

    def _extract_device_sn(self, payload: dict) -> str | None:
        for key in ("sn", "deviceSn", "device_sn", "snCode", "serialNumber", "snNumber"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _extract_device_name(self, payload: dict) -> str | None:
        for key in ("deviceName", "device_name", "name", "productName", "product_name", "model"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _guess_device_label(self, raw_name: str | None) -> str | None:
        if not raw_name:
            return None

        normalized_name = self._normalize_name(raw_name)
        for label, meta in DEVICE_TYPE_MAP.items():
            candidates = {
                label,
                meta.get("name", ""),
                meta.get("id", ""),
                meta.get("device_type", ""),
            }
            if any(
                (
                    self._normalize_name(candidate) == normalized_name
                    or self._normalize_name(candidate) in normalized_name
                    or normalized_name in self._normalize_name(candidate)
                )
                for candidate in candidates
                if candidate
            ):
                return meta.get("name", label)
        return None

    async def _load_cloud_devices(self) -> None:
        devices = await self._client.list_devices()

        choices: dict[str, dict] = {}
        for payload in devices:
            if not isinstance(payload, dict):
                continue

            sn = self._extract_device_sn(payload)
            if not sn:
                continue

            raw_name = self._extract_device_name(payload) or "Unknown device"
            display = f"{raw_name} ({sn})"
            guessed_label = self._guess_device_label(raw_name)

            choices[display] = {
                "sn": sn,
                "raw_name": raw_name,
                "device_label": guessed_label,
            }

        self._cloud_devices = choices

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
            await self._load_cloud_devices()
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
        """Step 2: Select account device (SN is not entered manually)."""
        if user_input is None:
            if not self._cloud_devices:
                return self.async_show_form(
                    step_id="device",
                    data_schema=vol.Schema({}),
                    errors={"base": "unknown"},
                )

            return self.async_show_form(
                step_id="device",
                data_schema=vol.Schema(
                    {
                        vol.Required("account_device"): vol.In(sorted(self._cloud_devices.keys())),
                    }
                ),
            )

        selected = user_input["account_device"]
        selected_device = self._cloud_devices[selected]
        self._device_sn = selected_device["sn"]
        self._device_label = selected_device.get("device_label")

        if not self._device_label:
            return await self.async_step_device_type()

        # Check if device already exists in registry
        device_registry = dr.async_get(self.hass)
        for dev in device_registry.devices.values():
            if (DOMAIN, self._device_sn) in dev.identifiers:
                return await self.async_step_device_exists()

        return self._create_entry()

    async def async_step_device_type(self, user_input=None) -> FlowResult:
        """Step 3: Manual device type mapping when cloud name is unknown."""
        if user_input is None:
            return self.async_show_form(
                step_id="device_type",
                data_schema=vol.Schema(
                    {
                        vol.Required("device_label"): vol.In(SUPPORTED_DEVICE_LABELS),
                    }
                ),
            )

        self._device_label = user_input["device_label"]

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
