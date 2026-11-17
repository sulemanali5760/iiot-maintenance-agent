import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from iiot_agent.model import Notification
from iiot_agent.notify import send


def test_json_post():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(201)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    notification = Notification("M2", "P101", "PLANT-LINE1-P101", 1, "Bearing", "Inspect", ["Bearing"])
    try:
        assert send(notification, f"http://127.0.0.1:{server.server_port}/") == 201
        assert received == [notification.to_dict()]
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
