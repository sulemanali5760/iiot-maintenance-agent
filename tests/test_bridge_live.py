import asyncio
import socket

from iiot_agent.bridge import run, to_message
from iiot_agent.bus import InMemoryBus
from iiot_agent.sim import serve, values_at


def test_message_and_seed():
    assert to_message("Port1", 2, "mm/s", 1, "now") == {
        "asset": "P101", "sensor": "vibration", "value": 2.0,
        "unit": "mm/s", "status": 1, "ts": "now"}
    assert values_at(20) == values_at(20)
    assert values_at(100)["vibration"] > values_at(20)["vibration"]


def test_live_subscription_all_sensors():
    async def scenario():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        endpoint = f"opc.tcp://127.0.0.1:{port}/iolink/"
        ready, stop, bridge_stop = asyncio.Event(), asyncio.Event(), asyncio.Event()
        messages, bus = [], InMemoryBus()
        bus.subscribe("plant/+/+/+", lambda topic, payload: messages.append(payload))
        server_task = asyncio.create_task(serve(endpoint, 0.1, ready=ready, stop=stop))
        bridge_task = None
        try:
            await asyncio.wait_for(ready.wait(), 4)
            bridge_task = asyncio.create_task(run(bus, endpoint, stop=bridge_stop))
            await asyncio.sleep(3)
            assert {m["sensor"] for m in messages} == {"vibration", "temperature", "pressure"}
            assert all(m["asset"] == "P101" and "status" in m for m in messages)
        finally:
            bridge_stop.set()
            try:
                if bridge_task is not None:
                    await bridge_task
            finally:
                stop.set()
                await server_task

    asyncio.run(asyncio.wait_for(scenario(), 9))
