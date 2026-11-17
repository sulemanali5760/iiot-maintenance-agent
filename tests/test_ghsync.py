import base64
import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files

import pytest

from iiot_agent.config import GithubCfg
from iiot_agent.ghsync import GithubError, fetch_previous, merge, push


def test_github_api_orphan_contents_race_and_redaction():
    content, calls = {}, []
    state = {"branch": False, "race": False, "fail": False}
    token = "test-token-must-not-leak"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, data):
            payload = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def record(self, body=None):
            assert self.headers.get("Authorization") == f"Bearer {token}"
            calls.append((self.command, self.path, body))

        def do_GET(self):
            self.record()
            if state["fail"]:
                return self.respond(403, {"message": token})
            if "/git/ref/heads/" in self.path:
                return self.respond(200 if state["branch"] else 404, {"object": {"sha": "commit"}})
            name = self.path.split("/contents/")[1].split("?")[0]
            if name not in content:
                return self.respond(404, {})
            self.respond(200, content[name])

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.record(body)
            if self.path.endswith("/git/commits"):
                assert body["parents"] == []
            if self.path.endswith("/git/refs"):
                assert body["ref"] == "refs/heads/gh-pages"
                state["branch"] = True
            self.respond(201, {"sha": "created"})

        def do_PUT(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.record(body)
            name = self.path.split("/contents/")[1]
            assert body["branch"] == "gh-pages"
            assert body["message"].startswith("snapshot ")
            if state["race"] and name == "snapshot.json":
                state["race"] = False
                content[name]["sha"] = "raced"
                return self.respond(409, {"message": token})
            if name in content:
                assert body["sha"] == content[name]["sha"]
            content[name] = {"sha": str(len(calls)), "content": body["content"]}
            self.respond(200, {})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cfg = GithubCfg(repo="owner/repo", api_url=f"http://127.0.0.1:{server.server_port}")
    snapshot = {"generated": datetime.now(timezone.utc).isoformat(), "tags": [], "notifications": []}
    try:
        assert fetch_previous(cfg, token) is None
        push(snapshot, cfg, token)
        assert state["branch"]
        assert set(content) == {"snapshot.json", "index.html"}
        assert fetch_previous(cfg, token) == snapshot
        assert base64.b64decode(content["index.html"]["content"]) == files("iiot_agent").joinpath("static/dashboard.html").read_bytes()
        # An older dashboard must be replaced with its current SHA too.
        content["index.html"]["content"] = base64.b64encode(b"old dashboard").decode()
        state["race"] = True
        push(snapshot, cfg, token)
        updates = [body for method, path, body in calls if method == "PUT" and "sha" in body]
        assert len(updates) == 3
        assert any(body["sha"] == "raced" for body in updates)
        state["fail"] = True
        with pytest.raises(GithubError) as error:
            push(snapshot, cfg, token)
        assert token not in str(error.value)
        assert token not in repr(error.value)
    finally:
        server.shutdown()
        thread.join(2)
        server.server_close()


def test_merge_retention_dedup_and_cap():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=1)).isoformat()
    old = (now - timedelta(days=8)).isoformat()
    def snapshot(history):
        return {"tags": [{"name": "tag", "asset": "A", "history": history}]}
    prev = snapshot([[old, 0], [recent, 1]])
    new = snapshot([[recent, 2], [now.isoformat(), 3]])
    result = merge(prev, new, 7)
    assert result["tags"][0]["history"] == [[recent, 2], [now.isoformat(), 3]]
    assert prev["tags"][0]["history"][1][1] == 1
    points = [[(now - timedelta(seconds=3000-i)).isoformat(), i] for i in range(3001)]
    history = merge(None, snapshot(points), 7)["tags"][0]["history"]
    assert len(history) == 2000
    assert history[0] == points[0] and history[-1] == points[-1]
