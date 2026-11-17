import os
import socket
import threading
import uuid

import pytest

from iiot_agent.bus import MqttBus


def test_real_mqtt_roundtrip():
    host = os.environ.get("MQTT_HOST")
    if not host:
        pytest.skip("Set MQTT_HOST to run against a broker")
    port = int(os.environ.get("MQTT_PORT", "1883"))
    try:
        with socket.create_connection((host, port), timeout=1):
            pass
    except OSError:
        if os.environ.get("CI"):
            pytest.fail("CI MQTT broker is unreachable")
        pytest.skip("MQTT broker is unreachable")
    receiver = MqttBus(host, port)
    sender = None
    received, ready = [], threading.Event()
    topic = f"plant/test/P101/{uuid.uuid4().hex}"
    try:
        receiver.subscribe(topic, lambda name, payload: (received.append(payload), ready.set()))
        sender = MqttBus(host, port)
        # Retry publication until SUBACK has arrived, without relying on a fixed sleep.
        for _ in range(10):
            sender.publish(topic, {"value": 7.2})
            if ready.wait(0.1):
                break
        assert ready.is_set()
        assert all(payload == {"value": 7.2} for payload in received)
    finally:
        if sender is not None:
            sender.close()
        receiver.close()
