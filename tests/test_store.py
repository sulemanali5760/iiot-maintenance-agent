import pytest
from datetime import datetime, timedelta, timezone

from iiot_agent.bus import InMemoryBus
from iiot_agent.model import Reading
from iiot_agent.store import Store


def test_history_downsampling_and_retention():
    store = Store()
    now = datetime.now(timezone.utc)
    try:
        for i in range(100):
            store.insert(Reading("P101", "x", i, "", (now - timedelta(seconds=100-i)).isoformat()))
        history = store.history("P101", "x", (now - timedelta(seconds=100)).isoformat(), 5)
        assert len(history) == 5
        assert history[0][1] < history[-1][1]
        old = (now - timedelta(days=40)).isoformat()
        store.insert(Reading("P101", "old", 1, "", old))
        store.add_notification(old, "P101", "old", {"Priority": 1})
        store.prune(30)
        assert store.latest("P101", "old", 1) == []
        assert store.notifications() == []
    finally:
        store.close()


def test_sql_queries():
    store = Store()
    try:
        for i in range(3):
            store.insert(Reading("P101", "vibration", float(i), "mm/s", f"2026-01-01T00:00:0{i}+00:00"))
        assert [r.value for r in store.latest("P101", "vibration", 2)] == [1, 2]
        assert len(store.window("P101", "vibration", "2026-01-01T00:00:01Z")) == 2
        assert store.stats("P101", "vibration", 2) == {"count": 2, "min": 1, "max": 2, "avg": 1.5}
        with pytest.raises(ValueError):
            store.insert(Reading("P101", "vibration", float("nan"), "mm/s", "2026-01-01T00:00:00Z"))
    finally:
        store.close()


def test_topic_filters():
    bus, received = InMemoryBus(), []
    bus.subscribe("plant/+/P101/#", lambda topic, payload: received.append(topic))
    for topic in ("plant/line1/P101", "plant/line1/P101/vibration", "plant/line2/P102/vibration"):
        bus.publish(topic, {})
    assert received == ["plant/line1/P101", "plant/line1/P101/vibration"]
    with pytest.raises(ValueError):
        bus.subscribe("plant/#/bad", lambda *_: None)
    system = []
    bus.subscribe("#", lambda topic, payload: system.append(topic))
    bus.publish("$SYS/status", {})
    assert system == []
