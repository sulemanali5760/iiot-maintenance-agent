from dataclasses import asdict, dataclass


@dataclass
class Reading:
    asset: str
    sensor: str
    value: float
    unit: str
    ts: str
    status: int = 0


@dataclass
class Alarm:
    asset: str
    sensor: str
    state: str
    value: float
    unit: str
    ts: str
    time_to_limit: float | None = None


@dataclass
class Notification:
    NotificationType: str
    Equipment: str
    FunctionalLocation: str
    Priority: int
    ShortText: str
    LongText: str
    Sources: list[str]

    def to_dict(self) -> dict:
        return asdict(self)
