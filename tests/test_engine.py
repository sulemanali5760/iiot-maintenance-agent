import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from iiot_agent.config import from_dict
from iiot_agent.engine import Engine
from iiot_agent.model import Reading


def test_sim_state_and_notification():
    cfg = from_dict({"source": {"type": "sim", "sampling_ms": 20, "fault_start": -120},
                     "store": {"path": ":memory:"}})
    engine = Engine(cfg)
    engine.start()
    try:
        deadline = time.monotonic() + 2
        while engine.readings < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        state = engine.state()
        assert len(state["tags"]) == 3
        assert state["notifications"][0]["Sources"]
        assert all(t["history"] for t in state["tags"])
        assert cfg.source.endpoint not in json.dumps(state)
        assert "username" not in state
    finally:
        engine.stop()


def test_rearming_and_falling_trend():
    cfg = from_dict({"source": {"type": "mqtt"}, "store": {"path": ":memory:"}, "tags": [
        {"name": "level", "topic": "level", "warn": 8, "alarm": 10, "low_alarm": 1}]})
    engine = Engine(cfg)
    start = datetime.now(timezone.utc)
    def receive(value, step):
        engine.receive(Reading("P101", "level", value, "", (start + timedelta(seconds=step)).isoformat()))
    try:
        for i, value in enumerate([8, 8, 10, 8, 5, 8]):
            receive(value, i)
        assert len(engine.state()["notifications"]) == 3
        # A clean trend window models decreasing values toward the low alarm.
        for i in range(20):
            receive(5 - i * 0.1, 20 + i)
        assert engine.state()["tags"][0]["time_to_limit_s"] == pytest.approx(21, abs=0.01)
        engine.store.prune(30)
    finally:
        engine.stop()


def test_reload_restarts_source(tmp_path):
    cfg = from_dict({"source": {"type": "sim", "sampling_ms": 20}, "store": {"path": ":memory:"}})
    engine = Engine(cfg)
    engine.start()
    try:
        cfg.github.label = "Reloaded"
        engine.reload(cfg)
        deadline = time.monotonic() + 2
        while engine.readings < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert engine.state()["label"] == "Reloaded"
        assert engine.readings >= 3
    finally:
        engine.stop()
