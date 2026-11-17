from iiot_agent.agent import build_notification
from iiot_agent.model import Alarm, Reading
from iiot_agent.retrieve import Retriever
from iiot_agent.store import Store


def test_notification_and_fake_llm():
    store, retriever = Store(), Retriever()
    reading = Reading("P101", "vibration", 7.2, "mm/s", "2026-01-01T00:00:00+00:00")
    store.insert(reading)
    alarm = Alarm("P101", "vibration", "ALARM", 7.2, "mm/s", reading.ts, 0)

    class FakeLLM:
        def complete(self, prompt):
            self.prompt = prompt
            return "Inspect the bearing [Vibration and bearing wear]."

    try:
        notification = build_notification(alarm, store, retriever)
        assert notification.Priority == 1
        assert len(notification.ShortText) <= 40
        assert len(notification.Sources) == 3
        assert set(notification.Sources) <= {h for h, _ in retriever.sections}
        assert "7.2" in notification.LongText and "SQL stats" in notification.LongText
        fake = FakeLLM()
        result = build_notification(alarm, store, retriever, fake)
        assert result.LongText == "Inspect the bearing [Vibration and bearing wear]."
        assert "7.200" in fake.prompt and "using only" in fake.prompt
        assert "Manual passages:" in fake.prompt and "Example spare parts" not in fake.prompt
    finally:
        store.close()
