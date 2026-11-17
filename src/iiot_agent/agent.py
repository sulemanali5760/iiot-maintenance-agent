from .model import Alarm, Notification
from .retrieve import Retriever
from .store import Store


def build_notification(alarm: Alarm, store: Store, retriever: Retriever, llm=None) -> Notification:
    passages = retriever.search(f"{alarm.sensor} {alarm.state} rising trend bearing wear", 3)
    stats = store.stats(alarm.asset, alarm.sensor, 20)
    estimate = (f"{alarm.time_to_limit:.1f} seconds" if alarm.time_to_limit is not None
                else "unavailable (no positive linear trend)")
    measurements = (f"{alarm.sensor}: {alarm.value:.3f} {alarm.unit} at {alarm.ts}; "
                    f"state {alarm.state}. Last 20 readings SQL stats: {stats}. "
                    f"Linear trend time to alarm limit: {estimate}.")
    if llm is None:
        steps = " ".join(f"[{heading}] {text.split('. ')[0].splitlines()[0]}"
                         for _, heading, text in passages)
        long_text = f"{measurements}\nRecommended steps: {steps}"
    else:
        context = "\n\n".join(f"[{h}]\n{t}" for _, h, t in passages)
        long_text = llm.complete(
            "Write a maintenance summary using only the measurements and manual passages below. "
            "Cite manual headings in brackets. Do not invent facts or instructions.\n"
            f"Measurements:\n{measurements}\nManual passages:\n{context}")
    return Notification("M2", alarm.asset, f"PLANT-LINE1-{alarm.asset}",
                        1 if alarm.state == "ALARM" else 2,
                        f"{alarm.sensor} {alarm.state}: {alarm.asset}"[:40],
                        long_text, [h for _, h, _ in passages])


class AnthropicLLM:
    def complete(self, prompt: str) -> str:
        import os
        import anthropic

        response = anthropic.Anthropic().messages.create(
            model=os.environ.get("IIOT_AGENT_MODEL", "claude-sonnet-5-5"),
            max_tokens=800, messages=[{"role": "user", "content": prompt}])
        return "\n".join(block.text for block in response.content if block.type == "text")
