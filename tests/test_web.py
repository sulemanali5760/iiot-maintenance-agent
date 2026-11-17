import json
import threading
from dataclasses import asdict
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from iiot_agent.config import from_dict, load
from iiot_agent.engine import Engine
from iiot_agent.web import create_server


def test_web_state_and_config(tmp_path):
    cfg = from_dict({"source": {"type": "sim", "sampling_ms": 20},
                     "store": {"path": ":memory:"}, "web": {"port": 0}})
    engine = Engine(cfg)
    path = tmp_path / "agent.toml"
    server = create_server(engine, path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    engine.start()
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(url + "/api/state") as response:
            assert len(json.load(response)["tags"]) == 3
        for route in ("/", "/setup"):
            with urlopen(url + route) as response:
                assert b"<!doctype html>" in response.read()
        with pytest.raises(HTTPError) as error:
            urlopen(Request(url + "/api/config", data=b"{}"))
        assert error.value.code == 415
        with pytest.raises(HTTPError) as error:
            urlopen(Request(url + "/api/config", data=b"{}",
                            headers={"Content-Type": "application/json",
                                     "Content-Length": str(1024 * 1024 + 1)}))
        assert error.value.code == 413
        data = asdict(cfg)
        data["github"]["label"] = "Saved machine"
        request = Request(url + "/api/config", data=json.dumps(data).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request) as response:
            assert response.status == 200
        assert load(path).github.label == "Saved machine"
        assert engine.state()["label"] == "Saved machine"
        data["source"]["password"] = "secret"
        with pytest.raises(HTTPError) as error:
            urlopen(Request(url + "/api/config", data=json.dumps(data).encode(),
                            headers={"Content-Type": "application/json"}))
        assert error.value.code == 400
        assert "secret" not in path.read_text(encoding="utf-8")
    finally:
        server.shutdown()
        thread.join(2)
        server.server_close()
        engine.stop()
