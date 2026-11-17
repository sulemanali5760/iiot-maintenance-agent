import json
import threading
from collections.abc import Callable
from typing import Protocol

Callback = Callable[[str, dict], None]


class Publisher(Protocol):
    def publish(self, topic: str, payload: dict) -> None: ...

    def subscribe(self, topic_filter: str, callback: Callback) -> None: ...


def _valid_filter(topic_filter: str) -> None:
    parts = topic_filter.split("/")
    for i, part in enumerate(parts):
        if ("#" in part and (part != "#" or i != len(parts) - 1)) or (
            "+" in part and part != "+"
        ):
            raise ValueError("MQTT wildcards must occupy a complete level; # must be last")
    if not topic_filter:
        raise ValueError("Empty topic filter")


def _matches(topic_filter: str, topic: str) -> bool:
    filters, levels = topic_filter.split("/"), topic.split("/")
    if topic.startswith("$") and filters[0] in ("+", "#"):
        return False
    for i, part in enumerate(filters):
        if part == "#":
            return True
        if i >= len(levels) or (part != "+" and part != levels[i]):
            return False
    return len(filters) == len(levels)


class InMemoryBus:
    def __init__(self) -> None:
        self._subscriptions: list[tuple[str, Callback]] = []

    def subscribe(self, topic_filter: str, callback: Callback) -> None:
        _valid_filter(topic_filter)
        self._subscriptions.append((topic_filter, callback))

    def publish(self, topic: str, payload: dict) -> None:
        if not topic or "+" in topic or "#" in topic:
            raise ValueError("Invalid publication topic")
        for topic_filter, callback in self._subscriptions:
            if _matches(topic_filter, topic):
                callback(topic, payload.copy())


class MqttBus:
    def __init__(self, host: str = "localhost", port: int | None = None,
                 client_id: str = "", tls_ca: str | None = None,
                 tls_cert: str | None = None, tls_key: str | None = None) -> None:
        import paho.mqtt.client as mqtt

        if bool(tls_cert) != bool(tls_key):
            raise ValueError("Supply both TLS certificate and private key")
        self._subscriptions: list[tuple[str, Callback]] = []
        self._ready = threading.Event()
        self._error: str | None = None
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        tls = any((tls_ca, tls_cert, tls_key))
        if tls:
            self._client.tls_set(ca_certs=tls_ca, certfile=tls_cert, keyfile=tls_key)
        self._client.connect(host, port or (8883 if tls else 1883))
        self._client.loop_start()
        if not self._ready.wait(5) or self._error:
            self.close()
            raise ConnectionError(self._error or "MQTT connection timed out")

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            self._error = str(reason_code)
        else:
            for topic_filter, _ in self._subscriptions:
                client.subscribe(topic_filter, qos=1)
        self._ready.set()

    def _on_message(self, client, userdata, message) -> None:
        try:
            payload = json.loads(message.payload)
            if not isinstance(payload, dict):
                return
        except (ValueError, UnicodeDecodeError):
            return
        for topic_filter, callback in self._subscriptions:
            if _matches(topic_filter, message.topic):
                callback(message.topic, payload)

    def subscribe(self, topic_filter: str, callback: Callback) -> None:
        _valid_filter(topic_filter)
        self._subscriptions.append((topic_filter, callback))
        self._client.subscribe(topic_filter, qos=1)

    def publish(self, topic: str, payload: dict) -> None:
        result = self._client.publish(topic, json.dumps(payload, allow_nan=False), qos=1)
        result.wait_for_publish(timeout=5)
        if not result.is_published():
            raise TimeoutError("MQTT publication was not acknowledged")

    def close(self) -> None:
        self._client.disconnect()
        self._client.loop_stop()
