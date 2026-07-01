import base64
import logging
import aiohttp
from homeassistant.util import uuid

from .base import EcoflowApiBase, EcoflowException
from ..cont import (
    API_CERTIFICATION_PATH,
    API_DEVICE_LIST_PATHS,
    API_HOST,
    API_LOGIN_PATH,
)

_LOGGER = logging.getLogger(__name__)


class CloudClient(EcoflowApiBase):
    """
    Cloud API klients (vecā App API loģika).
    """

    def __init__(self, username: str, password: str):
        super().__init__()
        self.username = username
        self.password = password

        self.token = None
        self.user_id = None
        self.user_name = None

    async def login(self):
        """Login uz Cloud API (App API)."""
        encoded_pw = base64.b64encode(self.password.encode()).decode()

        url = f"https://{API_HOST}{API_LOGIN_PATH}"
        headers = {"lang": "en_US", "content-type": "application/json"}
        data = {
            "email": self.username,
            "password": encoded_pw,
            "scene": "IOT_APP",
            "userType": "ECOFLOW",
        }

        _LOGGER.info(f"Logging in to EcoFlow Cloud at {API_HOST}")

        async with aiohttp.ClientSession() as session:
            resp = await session.post(url, headers=headers, json=data)
            js = await self._get_json_response(resp)

            try:
                self.token = js["data"]["token"]
                self.user_id = js["data"]["user"]["userId"]
                self.user_name = js["data"]["user"].get("name", "<no user name>")
            except KeyError as key:
                raise EcoflowException(f"Missing key {key} in login response: {js}")

            _LOGGER.info(f"Login OK as {self.user_name}")

            return await self._fetch_mqtt_credentials(session)

    async def _fetch_mqtt_credentials(self, session):
        """Iegūst MQTT credentials no Cloud API."""
        url = f"https://{API_HOST}{API_CERTIFICATION_PATH}"
        headers = {
            "lang": "en_US",
            "authorization": f"Bearer {self.token}",
            "content-type": "application/json",
        }

        resp = await session.get(url, headers=headers)
        js = await self._get_json_response(resp)

        self._accept_mqqt_certification(js)

        self.mqtt_info.client_id = (
            f"ANDROID_{str(uuid.random_uuid_hex()).upper()}_{self.user_id}"
        )

        return self.mqtt_info

    async def list_devices(self):
        """Atgriež visas ierīces no EcoFlow Cloud (App API)."""
        candidate_urls = tuple(
            f"https://{API_HOST}{path}" for path in API_DEVICE_LIST_PATHS
        )
        headers = {
            "lang": "en_US",
            "authorization": f"Bearer {self.token}",
            "content-type": "application/json",
        }

        data = {"pageSize": 100, "pageNum": 1}

        async with aiohttp.ClientSession() as session:
            last_error = None

            for url in candidate_urls:
                try:
                    resp = await session.post(url, headers=headers, json=data)
                    js = await self._get_json_response(resp)

                    if js.get("code") != 0 or "data" not in js:
                        raise EcoflowException(f"Device list error: {js}")

                    devices = js["data"].get("list", js["data"])
                    if not isinstance(devices, list):
                        raise EcoflowException(f"Unexpected device list format: {js}")

                    _LOGGER.info("Fetched %s devices from EcoFlow Cloud (%s)", len(devices), url)
                    return devices
                except Exception as exc:
                    last_error = exc

            raise EcoflowException(f"Device list fetch failed for all known endpoints: {last_error}")
