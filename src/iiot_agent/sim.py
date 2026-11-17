import asyncio
import random

ENDPOINT = "opc.tcp://127.0.0.1:4841/iolink/"
NAMESPACE = "urn:iiot-agent:iolink-master"
SENSORS = {"Port1": ("vibration", "mm/s"), "Port2": ("temperature", "°C"),
           "Port3": ("pressure", "bar")}


def values_at(step: int, seed: int = 7, fault_start: int = 40) -> dict[str, float]:
    rng = random.Random(f"{seed}:{step}")
    wear = max(0, step - fault_start)
    return {"vibration": 1.8 + 0.05 * wear + rng.uniform(-0.02, 0.02),
            "temperature": 45.0 + 0.15 * wear + rng.uniform(-0.1, 0.1),
            "pressure": 6.0 + rng.uniform(-0.02, 0.02)}


def device_status(sensor: str, value: float) -> int:
    from .detect import evaluate

    return {"OK": 0, "WARN": 1, "ALARM": 2}[evaluate([value], sensor)]


async def serve(endpoint: str = ENDPOINT, period: float = 1.0, seed: int = 7,
                fault_start: int = 40, ready: asyncio.Event | None = None,
                stop: asyncio.Event | None = None) -> None:
    from asyncua import Server, ua

    if period <= 0:
        raise ValueError("Period must be positive")
    server = Server()
    await server.init()
    server.set_endpoint(endpoint)
    idx = await server.register_namespace(NAMESPACE)
    master = await server.nodes.objects.add_object(idx, "IOLinkMaster")
    nodes = {}
    for port, (sensor, unit) in SENSORS.items():
        obj = await master.add_object(idx, port)
        pv = await obj.add_variable(idx, "ProcessValue", values_at(0, seed, fault_start)[sensor],
                                    varianttype=ua.VariantType.Double)
        await obj.add_property(idx, "Unit", unit)
        await obj.add_property(idx, "VendorDevice", f"Generic simulated {sensor} sensor")
        status = await obj.add_variable(idx, "DeviceStatus", 0, varianttype=ua.VariantType.Int32)
        nodes[sensor] = (pv, status)
    async with server:
        if ready is not None:
            ready.set()
        step = 0
        while stop is None or not stop.is_set():
            for sensor, value in values_at(step, seed, fault_start).items():
                pv, status = nodes[sensor]
                await status.write_value(device_status(sensor, value), ua.VariantType.Int32)
                await pv.write_value(value)
            step += 1
            if stop is None:
                await asyncio.sleep(period)
            else:
                try:
                    await asyncio.wait_for(stop.wait(), period)
                except asyncio.TimeoutError:
                    pass
