"""Thin, failure-tolerant wrapper around paho-mqtt (v2 callback API)."""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable

import paho.mqtt.client as mqtt

log = logging.getLogger("engine.mqtt")

MessageCallback = Callable[[str, dict[str, Any]], None]


class MqttClient:
    """Connects with retry, publishes JSON, dispatches subscriptions.

    All failures are logged, never raised to callers: losing the broker must
    not take the engine down. paho's internal loop handles reconnects once
    the first connection succeeds; ``connect`` retries the initial one.
    """

    def __init__(self, host: str, port: int, client_id: str = "horus-video-engine") -> None:
        self._host = host
        self._port = port
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            clean_session=True,
        )
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._subscriptions: dict[str, MessageCallback] = {}
        self._lock = threading.Lock()
        self._connected = threading.Event()
        self._stopping = False

    # -- lifecycle -----------------------------------------------------------

    def connect(self, retry_interval_s: float = 3.0, stop_event: threading.Event | None = None) -> bool:
        """Block until the first connection succeeds (or stop_event is set)."""
        self._client.loop_start()
        while not (stop_event and stop_event.is_set()):
            try:
                self._client.connect(self._host, self._port, keepalive=30)
                # Wait briefly for CONNACK.
                if self._connected.wait(timeout=10.0):
                    return True
            except Exception as exc:  # noqa: BLE001 - broker may simply be down
                log.warning("MQTT connect to %s:%s failed: %s; retrying in %.0fs",
                            self._host, self._port, exc, retry_interval_s)
            if stop_event:
                if stop_event.wait(retry_interval_s):
                    break
            else:
                threading.Event().wait(retry_interval_s)
        return False

    def close(self) -> None:
        self._stopping = True
        try:
            self._client.disconnect()
            self._client.loop_stop()
        except Exception:  # noqa: BLE001
            pass

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    # -- pub/sub -------------------------------------------------------------

    def publish_json(self, topic: str, payload: dict[str, Any], retain: bool = False, qos: int = 0) -> bool:
        try:
            body = json.dumps(payload, default=str)
            info = self._client.publish(topic, body, qos=qos, retain=retain)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                log.warning("MQTT publish to %s returned rc=%s", topic, info.rc)
                return False
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("MQTT publish to %s failed: %s", topic, exc)
            return False

    def subscribe(self, topic: str, callback: MessageCallback) -> None:
        with self._lock:
            self._subscriptions[topic] = callback
        try:
            self._client.subscribe(topic, qos=0)
        except Exception as exc:  # noqa: BLE001
            log.warning("MQTT subscribe to %s failed: %s", topic, exc)

    # -- paho callbacks --------------------------------------------------------

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any = None) -> None:
        log.info("MQTT connected to %s:%s (rc=%s)", self._host, self._port, reason_code)
        self._connected.set()
        with self._lock:
            topics = list(self._subscriptions)
        for topic in topics:  # re-subscribe after reconnects
            try:
                client.subscribe(topic, qos=0)
            except Exception:  # noqa: BLE001
                pass

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any = None) -> None:
        self._connected.clear()
        if not self._stopping:
            log.warning("MQTT disconnected (rc=%s); auto-reconnect engaged", reason_code)

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        with self._lock:
            callback = self._match(msg.topic)
        if callback is None:
            return
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            log.warning("Discarding non-JSON message on %s: %s", msg.topic, exc)
            return
        try:
            callback(msg.topic, payload)
        except Exception:  # noqa: BLE001
            log.exception("Subscriber callback for %s crashed", msg.topic)

    def _match(self, topic: str) -> MessageCallback | None:
        exact = self._subscriptions.get(topic)
        if exact is not None:
            return exact
        for pattern, callback in self._subscriptions.items():
            if mqtt.topic_matches_sub(pattern, topic):
                return callback
        return None
