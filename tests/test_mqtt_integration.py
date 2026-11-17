import os
import socket
import threading
import uuid
import asyncio

import pytest

from iiot_agent.bus import MqttBus
from iiot_agent.config import from_dict
from iiot_agent.sources import run_mqtt


def test_run_mqtt_json_payload():
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

    async def scenario():
        topic = "iiot-test/" + uuid.uuid4().hex
        cfg = from_dict({"source": {"type": "mqtt", "host": host, "port": port},
                         "tags": [{"name": "test", "topic": topic}]})
        readings, stop = [], asyncio.Event()
        task = asyncio.create_task(run_mqtt(cfg, readings.append, stop))
        sender = await asyncio.to_thread(MqttBus, host, port)
        try:
            for _ in range(30):
                await asyncio.to_thread(sender.publish, topic, {"value": 7.2})
                await asyncio.sleep(0.1)
                if readings:
                    break
            assert readings and readings[0].value == 7.2
        finally:
            stop.set()
            await task
            await asyncio.to_thread(sender.close)
    asyncio.run(asyncio.wait_for(scenario(), 9))


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
