import logging

_LOGGER = logging.getLogger(__name__)


class EcoflowException(Exception):
    """Generic EcoFlow API exception."""
    pass


class EcoflowApiBase:
    """
    Minimal base class for CloudClient.
    Provides JSON parsing and MQTT credential storage.
    """

    def __init__(self):
        self.mqtt_info = type("MqttInfo", (), {})()

    async def _get_json_response(self, resp):
        """Parse JSON or raise EcoflowException."""
        try:
            js = await resp.json()
        except Exception as e:
            text = await resp.text()
            raise EcoflowException(f"Invalid JSON: {e}, raw={text}")

        if js.get("code") not in (0, "0", None):
            raise EcoflowException(f"API error: {js}")

        return js

    def _accept_mqqt_certification(self, js):
        """Extract MQTT credentials from Cloud API response."""
        try:
            data = js["data"]
            # Jaunais EcoFlow Cloud formāts
            self.mqtt_info.host = data.get("url", "mqtt-e.ecoflow.com")
            self.mqtt_info.port = int(data.get("port", 8883))
            self.mqtt_info.username = data.get("certificateAccount")
            self.mqtt_info.password = data.get("certificatePassword")
            self.mqtt_info.topic = data.get("protocol", "mqtts")
        except KeyError as key:
            raise EcoflowException(f"Missing MQTT key {key} in response: {js}")
