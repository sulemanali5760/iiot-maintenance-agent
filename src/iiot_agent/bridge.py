import asyncio
from datetime import datetime, timezone

from .bus import Publisher
from .sim import ENDPOINT, NAMESPACE, SENSORS


def to_message(port_name: str, value: float, unit: str, status: int, ts: str) -> dict:
    return {"asset": "P101", "sensor": SENSORS[port_name][0], "value": float(value),
            "unit": unit, "ts": ts, "status": int(status)}


class _Handler:
    def __init__(self, publisher: Publisher, line: str, nodes: dict) -> None:
        self.publisher, self.line, self.nodes = publisher, line, nodes

    async def datachange_notification(self, node, value, data) -> None:
        port, unit_node, status_node = self.nodes[node.nodeid]
        unit, status = await unit_node.read_value(), await status_node.read_value()
        timestamp = data.monitored_item.Value.SourceTimestamp or datetime.now(timezone.utc)
        payload = to_message(port, value, unit, status, timestamp.isoformat())
        # paho publication acknowledgements block; keep the OPC UA event loop responsive.
        await asyncio.to_thread(self.publisher.publish,
                                f"plant/{self.line}/P101/{payload['sensor']}", payload)


async def run(publisher: Publisher, endpoint: str = ENDPOINT, line: str = "line1",
              stop: asyncio.Event | None = None, ready: asyncio.Event | None = None) -> None:
    from asyncua import Client

    async with Client(endpoint) as client:
        idx = await client.get_namespace_index(NAMESPACE)
        master = await client.nodes.objects.get_child(f"{idx}:IOLinkMaster")
        nodes, variables = {}, []
        for port in SENSORS:
            obj = await master.get_child(f"{idx}:{port}")
            pv = await obj.get_child(f"{idx}:ProcessValue")
            nodes[pv.nodeid] = (port, await obj.get_child(f"{idx}:Unit"),
                                await obj.get_child(f"{idx}:DeviceStatus"))
            variables.append(pv)
        subscription = await client.create_subscription(100, _Handler(publisher, line, nodes))
        try:
            await subscription.subscribe_data_change(variables)
            if ready is not None:
                ready.set()
            await (stop or asyncio.Event()).wait()
        finally:
            await subscription.delete()
