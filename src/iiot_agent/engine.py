import asyncio
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import notify, sources
from .agent import build_notification
from .config import validate
from .detect import evaluate, time_to_limit
from .model import Alarm
from .retrieve import Retriever
from .store import Store

LOG = logging.getLogger(__name__)


class Engine:
    def __init__(self, config):
        self._lock = threading.RLock()
        self._lifecycle = threading.RLock()
        self._thread = None
        self._loop = self._task = self._stop_event = None
        self._configure(config)

    def _prepare(self, config):
        validate(config)
        retriever = Retriever(Path(config.manual.path).read_text(encoding="utf-8")
                              if config.manual.path else None)
        return Store(config.store.path), retriever

    def _configure(self, config, prepared=None):
        self.store, self.retriever = prepared or self._prepare(config)
        self.config = config
        self._states, self._estimates, self._notified = {}, {}, {}
        self.readings = 0
        self.store.prune(config.store.keep_days)

    def receive(self, reading):
        with self._lock:
            tag = next(t for t in self.config.tags if t.name == reading.sensor)
            self.store.insert(reading)
            self.readings += 1
            rows = self.store.latest(tag.asset, tag.name, 20)
            timestamps, values = [r.ts for r in rows], [r.value for r in rows]
            state = evaluate(reading.value, tag)
            estimate = None
            if len(values) > 1:
                if tag.alarm is not None:
                    estimate = time_to_limit(timestamps, values, tag.alarm)
                if estimate is None and tag.low_alarm is not None:
                    estimate = time_to_limit(timestamps, [-v for v in values], -tag.low_alarm)
            self._states[tag.name], self._estimates[tag.name] = state, estimate
            if state == "OK":
                self._notified[tag.name] = set()
            elif state not in self._notified.setdefault(tag.name, set()):
                alarm = Alarm(tag.asset, tag.name, state, reading.value, tag.unit, reading.ts, estimate)
                notification = build_notification(alarm, self.store, self.retriever)
                self.store.add_notification(reading.ts, tag.asset, tag.name, notification.to_dict())
                self._notified[tag.name].add(state)
                if self.config.erp.url:
                    try:
                        notify.send(notification, self.config.erp.url)
                    except Exception:
                        LOG.warning("ERP notification delivery failed")

    def state(self):
        with self._lock:
            cfg = self.config
            since = (datetime.now(timezone.utc) - timedelta(days=cfg.github.history_days)).isoformat()
            tags = []
            for tag in cfg.tags:
                rows = self.store.latest(tag.asset, tag.name, 1)
                latest = rows[-1] if rows else None
                tags.append({"name": tag.name, "asset": tag.asset, "unit": tag.unit,
                             "limits": tag.limits(),
                             "state": self._states.get(tag.name, evaluate(latest.value, tag) if latest else "OK"),
                             "value": latest.value if latest else None,
                             "ts": latest.ts if latest else None,
                             "time_to_limit_s": self._estimates.get(tag.name),
                             "history": self.store.history(tag.asset, tag.name, since, 2000)})
            return {"generated": datetime.now(timezone.utc).isoformat(), "label": cfg.github.label,
                    "source": cfg.source.type, "tags": tags, "notifications": self.store.notifications()}

    async def _run(self):
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(getattr(sources, "run_" + self.config.source.type)(
            self.config, self.receive, self._stop_event))
        next_push, next_prune = time.monotonic(), time.monotonic() + 3600
        try:
            while not self._stop_event.is_set():
                if self._task.done():
                    await self._task
                    break
                now = time.monotonic()
                if now >= next_prune:
                    self.store.prune(self.config.store.keep_days)
                    next_prune = now + 3600
                if self.config.github.enabled and self.readings and now >= next_push:
                    try:
                        await asyncio.to_thread(self.push)
                    except Exception:
                        LOG.warning("GitHub snapshot push failed")
                    next_push = now + self.config.github.every_minutes * 60
                await sources._pause(self._stop_event, 0.2)
        finally:
            # Let a pending MQTT constructor finish so its network thread is closed too.
            if not self._stop_event.is_set():
                self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def push(self):
        from .ghsync import fetch_previous, merge, push

        cfg = self.config.github
        token = os.environ.get(cfg.token_env)
        if not token:
            raise ValueError("GitHub token environment variable is not set")
        snapshot = merge(fetch_previous(cfg, token), self.state(), cfg.history_days)
        push(snapshot, cfg, token)

    def start(self):
        with self._lifecycle:
            if self._thread is not None:
                return
            def worker():
                try:
                    asyncio.run(self._run())
                except Exception:
                    LOG.error("Monitoring source stopped unexpectedly")
            self._thread = threading.Thread(target=worker, daemon=True)
            self._thread.start()

    def _halt(self):
        if self._thread is not None:
            # start() can return before the thread has installed its event loop.
            while self._thread.is_alive() and self._stop_event is None:
                self._thread.join(0.01)
            if self._loop is not None and self._thread.is_alive():
                self._loop.call_soon_threadsafe(self._stop_event.set)
            self._thread.join()
            self._thread = self._loop = self._task = self._stop_event = None

    def stop(self):
        with self._lifecycle:
            self._halt()
            with self._lock:
                self.store.close()

    def reload(self, config):
        with self._lifecycle:
            prepared = self._prepare(config)
            self._halt()
            with self._lock:
                self.store.close()
                self._configure(config, prepared)
            self.start()
