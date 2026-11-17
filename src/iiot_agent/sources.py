import asyncio
import logging
import math
import os
from datetime import datetime, timezone

from .bus import MqttBus
from .model import Reading
from .sim import values_at

LOG = logging.getLogger(__name__)


def security(source, password=None):
    from opcua_tagmap.security import Security

    return Security(source.security_policy, source.security_mode, source.cert_dir,
                    source.server_cert or None, source.username or None,
                    password if password is not None else os.environ.get("OPCUA_PASSWORD"))


async def _pause(stop, seconds):
    try:
        await asyncio.wait_for(stop.wait(), seconds)
    except asyncio.TimeoutError:
        pass


def _reading(tag, value, ts=None):
    if not isinstance(value, (bool, int, float)) or not math.isfinite(value):
        raise ValueError("Not a finite numeric reading")
    timestamp = ts or datetime.now(timezone.utc)
    return Reading(tag.asset, tag.name, float(value), tag.unit,
                   timestamp.astimezone(timezone.utc).isoformat())


async def run_opcua(cfg, on_reading, stop, backoff_start=1.0):
    from asyncua import Client
    from opcua_tagmap.security import apply

    skipped, delay = set(), backoff_start
    while not stop.is_set():
        nodes = {}

        class Handler:
            def datachange_notification(self, node, value, data):
                for tag in nodes[node.nodeid]:
                    try:
                        reading = _reading(tag, value, data.monitored_item.Value.SourceTimestamp)
                    except (ValueError, TypeError, OverflowError):
                        if tag.name not in skipped:
                            LOG.warning("Skipping non-numeric OPC UA tag %s", tag.name)
                            skipped.add(tag.name)
                        continue
                    on_reading(reading)

        try:
            client = Client(cfg.source.endpoint, timeout=2)
            for tag in cfg.tags:
                nodes.setdefault(client.get_node(tag.node).nodeid, []).append(tag)
            await apply(client, security(cfg.source))
            async with client:
                sub = await client.create_subscription(cfg.source.sampling_ms, Handler())
                if nodes:
                    await sub.subscribe_data_change([client.get_node(nid) for nid in nodes])
                while not stop.is_set():
                    # A real request detects silent disconnects even without changing values.
                    await client.nodes.server_state.read_value()
                    delay = backoff_start
                    await _pause(stop, 0.5)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Protocol errors can include credentials or endpoint userinfo: log no exception text.
            LOG.warning("OPC UA connection lost or unavailable; retrying in %.1f s", delay)
            await _pause(stop, delay)
            delay = min(60, delay * 2)


async def run_mqtt(cfg, on_reading, stop, backoff_start=1.0):
    queue = asyncio.Queue()
    loop, delay, skipped = asyncio.get_running_loop(), backoff_start, set()
    while not stop.is_set():
        bus = None
        try:
            src = cfg.source
            bus = await asyncio.to_thread(MqttBus, src.host, src.port, src.client_id,
                                          src.tls_ca or None, src.tls_cert or None,
                                          src.tls_key or None)
            for tag in cfg.tags:
                bus.subscribe(tag.topic, lambda topic, payload, tag=tag:
                              loop.call_soon_threadsafe(queue.put_nowait, (tag, payload)))
            while not stop.is_set():
                if not bus._client.is_connected():
                    raise ConnectionError("MQTT disconnected")
                delay = backoff_start
                try:
                    tag, payload = await asyncio.wait_for(queue.get(), 0.2)
                except asyncio.TimeoutError:
                    continue
                try:
                    value = payload[tag.json_key] if isinstance(payload, dict) else payload
                    reading = _reading(tag, value)
                except (KeyError, ValueError, TypeError, OverflowError):
                    if tag.name not in skipped:
                        LOG.warning("Skipping non-numeric MQTT tag %s", tag.name)
                        skipped.add(tag.name)
                    continue
                on_reading(reading)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.warning("MQTT connection lost or unavailable; retrying in %.1f s", delay)
            await _pause(stop, delay)
            delay = min(60, delay * 2)
        finally:
            if bus:
                await asyncio.to_thread(bus.close)


async def run_sim(cfg, on_reading, stop):
    step = 0
    while not stop.is_set():
        values = values_at(step, cfg.source.seed, cfg.source.fault_start)
        for tag in cfg.tags:
            on_reading(_reading(tag, values[tag.name]))
        step += 1
        await _pause(stop, cfg.source.sampling_ms / 1000)
