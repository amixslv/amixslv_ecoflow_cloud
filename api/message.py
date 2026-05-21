import json
import logging

_LOGGER = logging.getLogger(__name__)


class JSONMessage:
    """
    Wrapper for EcoFlow MQTT JSON messages.

    Responsibilities:
    - Build correct JSON payload for SET commands
    - Encode to bytes for MQTT publish
    - Provide consistent logging
    """

    def __init__(self, data: dict):
        """
        data = {
            "sn": "<device_sn>",
            "params": { "<field>": <value> }
        }
        """
        self.data = data

    # ----------------------------------------------------------------------
    # MQTT PAYLOAD
    # ----------------------------------------------------------------------
    def to_mqtt_payload(self) -> bytes:
        """
        Convert JSON dict to MQTT payload (bytes).
        EcoFlow Cloud API expects UTF‑8 encoded JSON.
        """
        try:
            payload = json.dumps(self.data, separators=(",", ":"))
            return payload.encode("utf-8")
        except Exception as e:
            _LOGGER.error(f"Failed to encode MQTT payload: {e}")
            return b""

    # ----------------------------------------------------------------------
    # DEBUG
    # ----------------------------------------------------------------------
    def __repr__(self):
        return f"JSONMessage({self.data})"
