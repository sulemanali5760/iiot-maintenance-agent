import pytest

from iiot_agent.detect import evaluate, time_to_limit
from iiot_agent.config import TagCfg


def test_configured_high_and_low_limits():
    tag = TagCfg("custom", warn=8, alarm=10, low_warn=3, low_alarm=1)
    for value, state in [(0, "ALARM"), (1, "ALARM"), (2, "WARN"), (3, "WARN"),
                         (5, "OK"), (8, "WARN"), (10, "ALARM")]:
        assert evaluate(value, tag) == state
    assert evaluate(100, TagCfg("no-limits")) == "OK"


def test_limits():
    for value, state in [(1.8, "OK"), (4.5, "WARN"), (7.1, "ALARM")]:
        assert evaluate([value]) == state
    assert evaluate([70], "temperature") == "WARN"
    assert evaluate([85], "temperature") == "ALARM"
    assert evaluate([3.9], "pressure") == "ALARM"
    assert evaluate([4.0], "pressure") == "OK"
    assert evaluate([]) == "OK"


def test_linear_estimate():
    assert time_to_limit([0, 2, 4], [1, 5, 9], 13) == pytest.approx(2)
    assert time_to_limit([0, 1], [5, 5], 10) is None
    assert time_to_limit([0, 1], [5, 4], 10) is None
    assert time_to_limit([0, 0], [1, 2], 10) is None
    assert time_to_limit([0, 1], [8, 9], 7) == 0
    with pytest.raises(ValueError):
        time_to_limit([0], [], 10)
