import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

from . import bridge, notify, sim
from .agent import AnthropicLLM, build_notification
from .bus import InMemoryBus
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


def _browse(args):
    from opcua_tagmap.browse import browse
    from .config import SourceCfg
    from .sources import security

    src = SourceCfg(endpoint=args.endpoint, security_policy=args.security_policy,
                    security_mode=args.security_mode, cert_dir=args.cert_dir, username=args.user or "")
    result = asyncio.run(browse(args.endpoint, root=args.root, security=security(src)))
    for tag in result.tags:
        print(f"{tag.browse_path}\t{tag.node_id}\t{tag.datatype}")
    if result.errors:
        print(f"Browse: {len(result.errors)} node(s) could not be read")
    if result.truncated:
        print("Browse truncated at the node limit")


def _monitor(args):
    import threading
    import time
    from .config import load
    from .engine import Engine
    from .web import create_server

    try:
        cfg = load(args.config)
    except ValueError as error:
        # Schema errors contain no credential values or raw protocol responses.
        raise SystemExit(f"error: {error}") from None
    if args.command == "snapshot":
        # A one-shot job pushes exactly once, after its collection window.
        cfg.github.enabled = False
    engine = Engine(cfg)
    server = thread = None
    try:
        if args.command == "run" and not args.no_web:
            server = create_server(engine, args.config)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            print(f"Dashboard: http://{cfg.web.host}:{server.server_port}")
        engine.start()
        if args.command == "snapshot":
            time.sleep(args.duration)
            if not engine.readings:
                raise SystemExit(1)
            if args.push:
                engine.push()
        else:
            while True:
                time.sleep(0.5)
    finally:
        if server:
            server.shutdown()
            thread.join()
            server.server_close()
        engine.stop()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Condition monitoring with zero infrastructure")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("demo", "sim"):
        sub = commands.add_parser(name)
        if name in ("demo", "sim"):
            sub.add_argument("--seed", type=int, default=7)
            sub.add_argument("--fault-start", type=int, default=40)
        if name == "sim":
            sub.add_argument("--endpoint", default=sim.ENDPOINT)
        if name == "sim":
            sub.add_argument("--period", type=float, default=1.0)
        if name == "demo":
            sub.add_argument("--steps", type=int, default=160)
        if name == "demo":
            sub.add_argument("--db", default=":memory:" if name == "demo" else "readings.db")
        if name == "demo":
            sub.add_argument("--erp-url")
            sub.add_argument("--llm", action="store_true")
    sub = commands.add_parser("init")
    sub.add_argument("-o", "--output", default="iiot-agent.toml")
    sub = commands.add_parser("browse")
    sub.add_argument("endpoint")
    sub.add_argument("--root")
    sub.add_argument("--security-policy", default="None")
    sub.add_argument("--security-mode", default="SignAndEncrypt")
    sub.add_argument("--cert-dir", default="pki")
    sub.add_argument("--user")
    for name in ("run", "snapshot"):
        sub = commands.add_parser(name)
        sub.add_argument("-c", "--config", default="iiot-agent.toml")
        if name == "run":
            sub.add_argument("--no-web", action="store_true")
        else:
            sub.add_argument("--duration", type=float, default=60)
            sub.add_argument("--push", action="store_true")
    args = parser.parse_args(argv)
    if getattr(args, "llm", False) and not os.environ.get("ANTHROPIC_API_KEY"):
        parser.error("--llm requires ANTHROPIC_API_KEY")
    try:
        import logging
        logging.basicConfig(level=logging.WARNING)
        # Third-party protocol debug output can contain user identity information.
        logging.getLogger("asyncua").setLevel(logging.CRITICAL)
        if args.command == "snapshot":
            import math
            if not math.isfinite(args.duration) or args.duration <= 0:
                parser.error("--duration must be positive")
        if args.command == "demo":
            if args.steps <= 0:
                parser.error("--steps must be positive")
            _demo(args)
        elif args.command == "sim":
            asyncio.run(sim.serve(args.endpoint, args.period, args.seed, args.fault_start))
        elif args.command == "init":
            from pathlib import Path
            from .config import example
            with Path(args.output).open("x", encoding="utf-8") as stream:
                stream.write(example())
            print(f"Created {args.output}")
        elif args.command == "browse":
            _browse(args)
        else:
            _monitor(args)
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError):
        parser.exit(1, "error: invalid configuration, file or connection; check settings and credentials\n")
    except Exception:
        parser.exit(1, "error: operation failed; check server availability, security and credentials\n")
