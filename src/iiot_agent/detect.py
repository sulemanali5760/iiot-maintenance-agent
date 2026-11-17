from datetime import datetime

LIMITS = {
    "vibration": {"warn": 4.5, "alarm": 7.1},
    "temperature": {"warn": 70.0, "alarm": 85.0},
    "pressure": {"low": 4.0},
}


def evaluate(values, sensor="vibration") -> str:
    from .config import TagCfg

    if isinstance(sensor, TagCfg):
        value, tag = values, sensor
        if ((tag.alarm is not None and value >= tag.alarm) or
                (tag.low_alarm is not None and value <= tag.low_alarm)):
            return "ALARM"
        if ((tag.warn is not None and value >= tag.warn) or
                (tag.low_warn is not None and value <= tag.low_warn)):
            return "WARN"
        return "OK"
    if not values:
        return "OK"
    limits = LIMITS[sensor]
    value = values[-1]
    if "low" in limits:
        return "ALARM" if value < limits["low"] else "OK"
    if value >= limits["alarm"]:
        return "ALARM"
    return "WARN" if value >= limits["warn"] else "OK"


def time_to_limit(timestamps: list[str | float], values: list[float],
                  limit: float) -> float | None:
    if len(timestamps) != len(values):
        raise ValueError("One timestamp is required per value")
    if len(values) < 2:
        return None
    times = [datetime.fromisoformat(t).timestamp() if isinstance(t, str) else float(t)
             for t in timestamps]
    x = [t - times[0] for t in times]
    mean_x, mean_y = sum(x) / len(x), sum(values) / len(values)
    denominator = sum((t - mean_x) ** 2 for t in x)
    if denominator == 0:
        return None
    slope = sum((t - mean_x) * (v - mean_y) for t, v in zip(x, values)) / denominator
    if slope <= 0:
        return None
    return max(0.0, (limit - values[-1]) / slope)
