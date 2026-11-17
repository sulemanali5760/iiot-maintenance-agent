import asyncio
import socket

import pytest

from iiot_agent.cli import main
from iiot_agent.config import from_dict
from iiot_agent.sources import run_mqtt, run_opcua


async def wait_until(predicate, timeout=3):
    async def poll():
        while not predicate():
            await asyncio.sleep(0.02)
    await asyncio.wait_for(poll(), timeout)


@pytest.mark.parametrize("reconnect", [False, True])
def test_opcua_readings_browse_and_reconnect(reconnect, capsys):
    from asyncua import Server

    async def scenario():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        endpoint = f"opc.tcp://127.0.0.1:{port}/test/"
        server = Server()
        await server.init()
        server.set_endpoint(endpoint)
        idx = await server.register_namespace("urn:iiot-agent:test")
        obj = await server.nodes.objects.add_object(idx, "Machine")
        first = await obj.add_variable(f"ns={idx};s=first", "First", 2.0)
        second = await obj.add_variable(f"ns={idx};s=second", "Second", 3.0)
        cfg = from_dict({"source": {"endpoint": endpoint, "sampling_ms": 50}, "tags": [
            {"name": "first", "node": first.nodeid.to_string()},
            {"name": "second", "node": second.nodeid.to_string()}]})
        readings, stop = [], asyncio.Event()
        task, running = None, False
        try:
            await server.start()
            running = True
            task = asyncio.create_task(run_opcua(cfg, readings.append, stop, backoff_start=0.2))
            await wait_until(lambda: {r.sensor for r in readings} == {"first", "second"})
            assert all(r.ts.endswith("+00:00") for r in readings)
            if reconnect:
                await server.stop()
                running = False
                await asyncio.sleep(0.7)
                readings.clear()
                await server.start()
                running = True
                await first.write_value(4.0)
                await second.write_value(5.0)
                await wait_until(lambda: any(r.sensor == "first" and r.value == 4 for r in readings)
                                 and any(r.sensor == "second" and r.value == 5 for r in readings), 4)
            else:
                await asyncio.to_thread(main, ["browse", endpoint])
                output = capsys.readouterr().out
                assert first.nodeid.to_string() in output
                assert second.nodeid.to_string() in output
        finally:
            stop.set()
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            if running:
                await server.stop()

    asyncio.run(asyncio.wait_for(scenario(), 9))


def test_mqtt_number_json_and_reconnect(monkeypatch):
    import iiot_agent.sources as sources

    buses = []
    class FakeBus:
        def __init__(self, *args):
            self._client = self
            self.connected = True
            self.callbacks = {}
            buses.append(self)

        def is_connected(self):
            return self.connected

        def subscribe(self, topic, callback):
            self.callbacks[topic] = callback

        def close(self):
            self.connected = False

    monkeypatch.setattr(sources, "MqttBus", FakeBus)

    async def scenario():
        cfg = from_dict({"source": {"type": "mqtt"}, "tags": [
            {"name": "value", "topic": "test", "json_key": "number"}]})
        readings, stop = [], asyncio.Event()
        task = asyncio.create_task(run_mqtt(cfg, readings.append, stop, backoff_start=0.01))
        try:
            await wait_until(lambda: buses and "test" in buses[0].callbacks)
            buses[0].callbacks["test"]("test", 2)
            buses[0].callbacks["test"]("test", {"number": 3})
            buses[0].callbacks["test"]("test", {"number": "invalid"})
            await wait_until(lambda: len(readings) == 2)
            assert [r.value for r in readings] == [2, 3]
            buses[0].connected = False
            await wait_until(lambda: len(buses) == 2 and "test" in buses[1].callbacks)
            buses[1].callbacks["test"]("test", {"number": 4})
            await wait_until(lambda: len(readings) == 3)
        finally:
            stop.set()
            await task

    asyncio.run(asyncio.wait_for(scenario(), 4))
