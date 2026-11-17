import tomllib

import pytest

from iiot_agent.config import dump, example, from_dict, load


def test_example_roundtrip(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(example(), encoding="utf-8")
    cfg = load(path)
    assert from_dict(tomllib.loads(dump(cfg))) == cfg
    assert "password =" not in dump(cfg).lower()


@pytest.mark.parametrize("data,message", [
    ({"source": {"type": "bad"}}, "Unknown source"),
    ({"tags": [{"name": "x"}]}, "missing node"),
    ({"source": {"type": "mqtt"}, "tags": [{"name": "x"}]}, "missing topic"),
    ({"source": {"type": "sim"}, "tags": [{"name": "pressure"}, {"name": "pressure"}]}, "unique"),
    ({"source": {"type": "sim"}, "tags": [{"name": "pressure", "warn": 3, "alarm": 2}]}, "warn"),
    ({"source": {"type": "sim"}, "tags": [{"name": "pressure", "low_warn": 2, "low_alarm": 3}]}, "low_alarm"),
    ({"source": {"password": "never-store-this"}}, "Invalid configuration"),
    ({"source": {"sampling_ms": 0}}, "sampling_ms"),
    ({"source": {"endpoint": 3}}, "must be text"),
])
def test_validation(data, message):
    with pytest.raises(ValueError, match=message):
        from_dict(data)


def test_sim_defaults_and_public_example():
    assert len(from_dict({"source": {"type": "sim"}}).tags) == 3
    cfg = load("examples/public-demo.toml")
    assert len(cfg.tags) == 2
    assert cfg.github.branch == "gh-pages"
