import pytest

from iiot_agent.cli import main
from iiot_agent.config import dump, from_dict, load


def test_init(tmp_path):
    path = tmp_path / "agent.toml"
    main(["init", "-o", str(path)])
    assert load(path).source.type == "opcua"
    original = path.read_bytes()
    with pytest.raises(SystemExit) as error:
        main(["init", "-o", str(path)])
    assert error.value.code == 1
    assert path.read_bytes() == original


def test_snapshot_no_readings_is_failure(tmp_path, monkeypatch):
    from iiot_agent import sources

    async def empty_source(cfg, on_reading, stop):
        await stop.wait()
    monkeypatch.setattr(sources, "run_sim", empty_source)
    cfg = from_dict({"source": {"type": "sim"}, "store": {"path": ":memory:"}})
    path = tmp_path / "agent.toml"
    path.write_text(dump(cfg), encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        main(["snapshot", "-c", str(path), "--duration", "0.05"])
    assert error.value.code == 1


def test_snapshot_pushes_once_after_collection(tmp_path, monkeypatch):
    from iiot_agent.engine import Engine

    counts = []
    monkeypatch.setattr(Engine, "push", lambda self: counts.append(self.readings))
    cfg = from_dict({"source": {"type": "sim", "sampling_ms": 10},
                     "store": {"path": ":memory:"}, "github": {"enabled": True}})
    path = tmp_path / "agent.toml"
    path.write_text(dump(cfg), encoding="utf-8")
    main(["snapshot", "-c", str(path), "--duration", "0.2", "--push"])
    assert len(counts) == 1 and counts[0] >= 3
