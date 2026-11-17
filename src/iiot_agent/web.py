import asyncio
import json
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path

from .config import SourceCfg, dump, from_dict
from .sources import security


def create_server(engine, config_path):
    config_path = Path(config_path)
    mutation = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, data, content_type="application/json"):
            payload = json.dumps(data, allow_nan=False).encode() if content_type == "application/json" else data
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if self.path == "/api/state":
                return self.respond(200, engine.state())
            if self.path == "/api/config":
                return self.respond(200, asdict(engine.config))
            if self.path in ("/", "/setup"):
                name = "dashboard" if self.path == "/" else "setup"
                return self.respond(200, files("iiot_agent").joinpath(f"static/{name}.html").read_bytes(),
                                    "text/html; charset=utf-8")
            self.respond(404, {"error": "Not found"})

        def do_POST(self):
            if self.headers.get_content_type() != "application/json":
                self.close_connection = True
                return self.respond(415, {"error": "Content-Type must be application/json"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                size = -1
            if size < 0 or size > 1024 * 1024:
                self.close_connection = True
                return self.respond(413, {"error": "Body must be at most 1 MB"})
            try:
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError("Expected a JSON object")
            except (ValueError, UnicodeDecodeError):
                return self.respond(400, {"error": "Invalid JSON object"})
            if self.path == "/api/browse":
                try:
                    from opcua_tagmap.browse import browse

                    password = body.pop("password", None)
                    root = body.pop("root", None)
                    src = SourceCfg(**body)
                    # Validate the source without requiring any selected tags.
                    from_dict({"source": asdict(src)})
                    result = asyncio.run(browse(src.endpoint, root=root, security=security(src, password)))
                    return self.respond(200, {"tags": [
                        {"browse_path": t.browse_path, "display_name": t.display_name,
                         "node_id": t.node_id, "datatype": t.datatype} for t in result.tags],
                        "errors": ["Some nodes could not be read"] if result.errors else [],
                        "truncated": result.truncated})
                except Exception:
                    # Never echo a browse password, endpoint or protocol exception.
                    return self.respond(400, {"error": "Browse failed; check endpoint, security and server trust"})
            if self.path == "/api/config":
                try:
                    cfg = from_dict(body)
                    text = dump(cfg)
                    with mutation:
                        temporary = config_path.with_suffix(config_path.suffix + ".tmp")
                        temporary.write_text(text, encoding="utf-8")
                        temporary.replace(config_path)
                        engine.reload(cfg)
                    return self.respond(200, {"saved": True})
                except (ValueError, TypeError):
                    return self.respond(400, {"error": "Invalid configuration; check source, tags and limits"})
                except OSError:
                    return self.respond(500, {"error": "Could not save or load configuration files"})
            self.respond(404, {"error": "Not found"})

    server = ThreadingHTTPServer((engine.config.web.host, engine.config.web.port), Handler)
    server.daemon_threads = True
    return server
