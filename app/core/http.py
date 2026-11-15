"""Small JSON-over-HTTP helper on the standard library, for calling outside APIs."""
import json
import urllib.error
import urllib.parse
import urllib.request


class HttpError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status   # 0 means the request never got an answer
        self.body = body


def request_json(url, *, method="GET", params=None, headers=None, body=None, timeout=30):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    data = None
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", **(headers or {})}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise HttpError(e.code, e.read().decode("utf-8", "replace")) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise HttpError(0, str(e)) from e
    try:
        return json.loads(text)
    except ValueError as e:
        raise HttpError(0, "reply was not JSON: " + text[:200]) from e
