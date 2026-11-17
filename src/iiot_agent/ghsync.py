"""GitHub Contents/Git Data API transport; no git checkout or credentials on disk."""

import base64
import copy
import json
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class GithubError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f"GitHub API request failed (status {status})")


def _request(cfg, token, method, path, data=None, missing=False):
    url = cfg.api_url.rstrip("/") + "/repos/" + quote(cfg.repo, safe="/") + path
    request = Request(url, method=method,
                      headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                               "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28"},
                      data=json.dumps(data, allow_nan=False).encode() if data is not None else None)
    try:
        with urlopen(request, timeout=10) as response:
            return json.load(response)
    except HTTPError as error:
        if missing and error.code == 404:
            return None
        raise GithubError(error.code) from None
    except (URLError, OSError, ValueError):
        raise GithubError("transport or invalid response") from None


def _get(cfg, token, name):
    return _request(cfg, token, "GET", "/contents/" + name + "?ref=" + quote(cfg.branch, safe=""),
                    missing=True)


def _decode(content):
    return base64.b64decode(content["content"])


def fetch_previous(cfg, token):
    content = _get(cfg, token, "snapshot.json")
    if content is None:
        return None
    try:
        return json.loads(_decode(content))
    except (ValueError, KeyError):
        raise GithubError("invalid snapshot") from None


def push(snapshot, cfg, token):
    message = "snapshot " + datetime.now(timezone.utc).isoformat()
    dashboard = files("iiot_agent").joinpath("static/dashboard.html").read_bytes()
    branch = "/git/ref/heads/" + quote(cfg.branch, safe="")
    if _request(cfg, token, "GET", branch, missing=True) is None:
        blob = _request(cfg, token, "POST", "/git/blobs",
                        {"content": base64.b64encode(dashboard).decode(), "encoding": "base64"})
        tree = _request(cfg, token, "POST", "/git/trees", {"tree": [
            {"path": "index.html", "mode": "100644", "type": "blob", "sha": blob["sha"]}]})
        commit = _request(cfg, token, "POST", "/git/commits",
                          {"message": message, "tree": tree["sha"], "parents": []})
        try:
            _request(cfg, token, "POST", "/git/refs",
                     {"ref": "refs/heads/" + cfg.branch, "sha": commit["sha"]})
        except GithubError as error:
            if error.status not in (409, 422) or _request(cfg, token, "GET", branch, missing=True) is None:
                raise
    contents = {"snapshot.json": json.dumps(snapshot, allow_nan=False).encode(), "index.html": dashboard}
    for name, payload in contents.items():
        for attempt in range(2):
            current = _get(cfg, token, name)
            if name == "index.html" and current and _decode(current) == payload:
                break
            body = {"message": message, "branch": cfg.branch,
                    "content": base64.b64encode(payload).decode()}
            if current:
                body["sha"] = current["sha"]
            try:
                _request(cfg, token, "PUT", "/contents/" + name, body)
                break
            except GithubError as error:
                if attempt or error.status not in (409, 422):
                    raise


def merge(prev, new, history_days):
    result = copy.deepcopy(new)
    cutoff = datetime.now(timezone.utc) - timedelta(days=history_days)
    previous = {(t["asset"], t["name"]): t for t in (prev or {}).get("tags", [])}
    for tag in result["tags"]:
        history = previous.get((tag["asset"], tag["name"]), {}).get("history", []) + tag["history"]
        points = {}
        for ts, value in history:
            stamp = datetime.fromisoformat(ts).astimezone(timezone.utc)
            if stamp >= cutoff:
                points[stamp.isoformat()] = value
        points = sorted(points.items())
        # Evenly sample the retained window rather than dropping its oldest portion.
        if len(points) > 2000:
            points = [points[round(i * (len(points) - 1) / 1999)] for i in range(2000)]
        tag["history"] = [list(point) for point in points]
    return result
