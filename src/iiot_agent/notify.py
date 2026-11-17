import json
from urllib.request import Request, urlopen

from .model import Notification


def send(notification: Notification, url: str, timeout: float = 5) -> int:
    request = Request(url, data=json.dumps(notification.to_dict(), allow_nan=False).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=timeout) as response:
        return response.status
