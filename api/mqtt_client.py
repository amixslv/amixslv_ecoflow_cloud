import logging
import ssl
from typing import Callable, List, Optional

from homeassistant.core import HomeAssistant, callback
from homeassistant.components.mqtt.async_client import AsyncMQTTClient

from paho.mqtt.client import Client, MQTTMessage, ConnectFlags, DisconnectFlags
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

_LOGGER = logging.getLogger(__name__)


class MQTTClient:
    """
    Clean, modern MQTT client for amixslv_ecoflow_cloud.
    """

    def __init__(
        self,
        url: str,
        port: int,
        username: str,
        password: str,
        client_id: str,
        on_message_callback: Optional[Callable[[str, bytes], None]] = None,
    ):
        self.url = url
        self.port = port
        self.username = username
        self.password = password
        self.client_id = client_id

        self.connected = False
        self._topics: List[str] = []
        self._on_message_callback = on_message_callback

        # HA AsyncMQTTClient wrapper around Paho
        self._client: AsyncMQTTClient = AsyncMQTTClient(
            client_id=self.client_id,
            reconnect_on_failure=True,
            clean_session=True,
            callback_api_version=CallbackAPIVersion.VERSION2,
        )

        self._client.setup()
        self._client.username_pw_set(self.username, self.password)

        # Callbacks
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.on_socket_close = self._on_socket_close

    # ----------------------------------------------------------------------
    # ASYNC SETUP (TLS + CONNECT)
    # ----------------------------------------------------------------------
    async def async_setup(self, hass: HomeAssistant):
        """
        Setup MQTT connection with TLS in a non-blocking way.
        """

        def _setup_tls():
            # Correct TLS signature:
            # tls_set(ca_certs, certfile, keyfile, cert_reqs)
            self._client.tls_set(
                ca_certs=None,
                certfile=None,
                keyfile=None,
                cert_reqs=ssl.CERT_REQUIRED,
            )
            self._client.tls_insecure_set(False)

        # TLS must run in executor
        await hass.async_add_executor_job(_setup_tls)

        _LOGGER.info("Connecting to MQTT %s:%s as %s", self.url, self.port, self.client_id)

        # Connect (non-blocking)
        self._client.connect(self.url, self.port, keepalive=15)

        # Start network loop in background thread
        self._client.loop_start()

    # ----------------------------------------------------------------------
    # PUBLIC API
    # ----------------------------------------------------------------------
    def subscribe(self, topics: List[str]):
        """Subscribe to a new list of topics."""
        self._topics = list(set(topics))

        if self.connected and self._topics:
            topic_pairs = [(t, 1) for t in self._topics]
            self._client.subscribe(topic_pairs)
            _LOGGER.info("Subscribed to MQTT topics: %s", topic_pairs)

    def publish(self, topic: str, payload: bytes, qos: int = 0) -> bool:
        """Publish a message."""
        if not self.connected:
            _LOGGER.error("MQTT publish skipped (not connected): topic=%s", topic)
            return False
        try:
            info = self._client.publish(topic, payload, qos=qos)
            _LOGGER.debug("MQTT publish qos=%s topic=%s rc=%s", qos, topic, info.rc)
            return info.rc == 0
        except Exception as e:
            _LOGGER.error("MQTT publish error: %s", e)
            return False

    def stop(self):
        """Stop MQTT client (sync)."""
        try:
            if self._topics:
                self._client.unsubscribe(self._topics)
            self._client.loop_stop()
            self._client.disconnect()
        except Exception as e:
            _LOGGER.error("MQTT stop error: %s", e)

    async def async_unload(self, hass: HomeAssistant):
        """
        Async-friendly unload, ko var droši izsaukt no async_unload_entry.
        """
        await hass.async_add_executor_job(self.stop)

    # ----------------------------------------------------------------------
    # CALLBACKS
    # ----------------------------------------------------------------------
    @callback
    def _on_connect(
        self,
        client: Client,
        userdata,
        flags: ConnectFlags,
        rc: ReasonCode,
        properties: Properties | None = None,
    ):
        if rc == 0:
            self.connected = True
            if self._topics:
                topic_pairs = [(t, 1) for t in self._topics]
                self._client.subscribe(topic_pairs)
                _LOGGER.info("Subscribed to MQTT topics: %s", topic_pairs)
        else:
            _LOGGER.error("MQTT connect error: %s", rc.getName())

    @callback
    def _on_disconnect(
        self,
        client: Client,
        userdata,
        disconnect_flags: DisconnectFlags,
        reason_code: ReasonCode,
        properties: Properties | None,
    ):
        self.connected = False
        if reason_code.is_failure:
            _LOGGER.error("MQTT disconnect: %s", reason_code.getName())

    @callback
    def _on_socket_close(self, client: Client, userdata, sock):
        _LOGGER.info("MQTT socket closed: %s", sock)

    @callback
    def _on_message(self, client, userdata, message: MQTTMessage):
        """Forward message to message_router."""
        try:
            if self._on_message_callback:
                self._on_message_callback(message.topic, message.payload)
        except Exception:
            _LOGGER.error(
                "Error processing MQTT message on %s",
                message.topic,
                exc_info=True,
            )
