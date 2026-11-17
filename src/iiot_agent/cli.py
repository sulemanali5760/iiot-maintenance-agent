import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

from . import bridge, notify, sim
from .agent import AnthropicLLM, build_notification
from .bus import InMemoryBus, MqttBus
from .detect import LIMITS, evaluate, time_to_limit
from .model import Alarm, Reading
from .retrieve import Retriever
from .store import Store


def _notification(reading: Reading, store: Store, seen: set, retriever: Retriever, args) -> None:
    rows = store.latest(reading.asset, reading.sensor, 20)
    state = evaluate([row.value for row in rows], reading.sensor)
    key = (reading.asset, reading.sensor, state)
    if state == "OK" or key in seen:
        return
    seen.add(key)
    limit = LIMITS[reading.sensor].get("alarm")
    estimate = (time_to_limit([row.ts for row in rows], [row.value for row in rows], limit)
                if limit is not None else None)
    alarm = Alarm(reading.asset, reading.sensor, state, reading.value, reading.unit,
                  reading.ts, estimate)
    llm = AnthropicLLM() if args.llm else None
    notification = build_notification(alarm, store, retriever, llm)
    print(f"Alarm: {reading.sensor} {state} {reading.value:.3f} {reading.unit}; "
          f"time to alarm limit: {estimate:.1f} s" if estimate is not None else
          f"Alarm: {reading.sensor} {state} {reading.value:.3f} {reading.unit}; "
          "time to alarm limit: unavailable")
    print("Notification: " + json.dumps(notification.to_dict(), ensure_ascii=True))
    if args.erp_url:
        print(f"ERP HTTP status: {notify.send(notification, args.erp_url)}")


def _demo(args) -> None:
    store, bus, seen, retriever = Store(args.db), InMemoryBus(), set(), Retriever()
    count = 0

    def receive(topic, payload):
        nonlocal count
        reading = Reading(**payload)
        store.insert(reading)
        count += 1
        _notification(reading, store, seen, retriever, args)

    bus.subscribe("plant/+/+/+", receive)
    try:
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for step in range(args.steps):
            timestamp = (start + timedelta(seconds=step)).isoformat()
            values = sim.values_at(step, args.seed, args.fault_start)
            for port, (sensor, unit) in sim.SENSORS.items():
                payload = bridge.to_message(port, values[sensor], unit,
                                            sim.device_status(sensor, values[sensor]), timestamp)
                bus.publish(f"plant/line1/P101/{sensor}", payload)
        print(f"Readings stored: {count}")
    finally:
        store.close()


def _consume(args) -> None:
    # Process callbacks on the main thread so SQLite, reporting and ERP failures propagate.
    import queue

    messages = queue.Queue()
    bus = MqttBus(args.mqtt_host, args.mqtt_port, args.client_id,
                  args.tls_ca, args.tls_cert, args.tls_key)
    store, retriever, seen = Store(args.db), Retriever(), set()
    bus.subscribe(f"plant/{args.line}/+/+", lambda topic, payload: messages.put(payload))
    try:
        while True:
            payload = messages.get()
            try:
                reading = Reading(**payload)
                if reading.sensor not in LIMITS:
                    raise ValueError("Unknown sensor")
                store.insert(reading)
            except (TypeError, ValueError) as error:
                print(f"Rejected reading: {error}")
                continue
            if args.command == "watch":
                _notification(reading, store, seen, retriever, args)
    finally:
        bus.close()
        store.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Simulated IIoT maintenance chain")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("demo", "sim", "bridge", "store", "watch"):
        sub = commands.add_parser(name)
        if name in ("demo", "sim"):
            sub.add_argument("--seed", type=int, default=7)
            sub.add_argument("--fault-start", type=int, default=40)
        if name in ("sim", "bridge"):
            sub.add_argument("--endpoint", default=sim.ENDPOINT)
        if name == "sim":
            sub.add_argument("--period", type=float, default=1.0)
        if name == "demo":
            sub.add_argument("--steps", type=int, default=160)
        if name in ("demo", "store", "watch"):
            sub.add_argument("--db", default=":memory:" if name == "demo" else "readings.db")
        if name in ("demo", "watch"):
            sub.add_argument("--erp-url")
            sub.add_argument("--llm", action="store_true")
        if name in ("bridge", "store", "watch"):
            sub.add_argument("--mqtt-host", default="localhost")
            sub.add_argument("--mqtt-port", type=int)
            sub.add_argument("--client-id", default="")
            sub.add_argument("--tls-ca")
            sub.add_argument("--tls-cert")
            sub.add_argument("--tls-key")
            sub.add_argument("--line", default="line1")
    args = parser.parse_args(argv)
    if getattr(args, "llm", False) and not os.environ.get("ANTHROPIC_API_KEY"):
        parser.error("--llm requires ANTHROPIC_API_KEY")
    try:
        if args.command == "demo":
            if args.steps <= 0:
                parser.error("--steps must be positive")
            _demo(args)
        elif args.command == "sim":
            asyncio.run(sim.serve(args.endpoint, args.period, args.seed, args.fault_start))
        elif args.command == "bridge":
            bus = MqttBus(args.mqtt_host, args.mqtt_port, args.client_id,
                          args.tls_ca, args.tls_cert, args.tls_key)
            try:
                asyncio.run(bridge.run(bus, args.endpoint, args.line))
            finally:
                bus.close()
        else:
            _consume(args)
    except KeyboardInterrupt:
        pass
