"""Bounded HTTPS transport. A mutation is never retried by this layer."""
import json
import http.client
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from .common import UserError


class ApiError(UserError):
    def __init__(self, status, message, uncertain=False):
        super().__init__(message, {401: "unauthorized", 403: "forbidden", 429: "rate_limited"}.get(status, "api_error"))
        self.status = status
        self.uncertain = uncertain


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_user(resource):
    """Validate account fields before replacing access-critical cached state."""
    if not isinstance(resource, dict) or not resource.get("id") or resource.get("object") != "user":
        raise ApiError(0, "WaniKani returned an invalid account response.")
    data = resource.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("subscription"), dict):
        raise ApiError(0, "WaniKani returned incomplete account access information.")
    maximum = data["subscription"].get("max_level_granted")
    level = data.get("level")
    if type(maximum) is not int or not 0 <= maximum <= 60 or type(level) is not int or not 1 <= level <= 60:
        raise ApiError(0, "WaniKani returned invalid account access information.")
    return resource


class Api:
    BASE = "https://api.wanikani.com/v2/"

    def __init__(self, token, clock=time.time):
        self.token = token
        self.clock = clock
        self.next_allowed = 0
        self.server_offset = 0
        self.opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))

    def request(self, path, method="GET", data=None, etag=None):
        url = path if path.startswith("https://") else self.BASE + path.lstrip("/")
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "api.wanikani.com" or not parsed.path.startswith("/v2/"):
            raise ApiError(0, "Rejected an unexpected API address.")
        wait = self.next_allowed - self.clock()
        if wait > 0:
            # Sleep only this network worker, never the QML/UI command thread.
            time.sleep(min(wait, 60))
            if self.next_allowed > self.clock():
                raise ApiError(429, "WaniKani rate limit reached. Synchronization will resume later.")
        headers = {"Authorization": "Bearer " + self.token, "Wanikani-Revision": "20170710", "Accept": "application/json", "User-Agent": "Omarchy-WaniKani/0.1"}
        if etag:
            headers["If-None-Match"] = etag
        body = None
        if data is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
            body = json.dumps(data).encode()
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        self.next_allowed = self.clock() + 1.05
        try:
            response = self.opener.open(request, timeout=15)
            with response:
                self._headers(response.headers)
                raw = response.read(16 * 1024 * 1024 + 1)
                if len(raw) > 16 * 1024 * 1024:
                    raise ApiError(0, "API response exceeded the size limit.", method != "GET")
                try:
                    value = json.loads(raw)
                except (ValueError, UnicodeError):
                    raise ApiError(0, "WaniKani returned an unreadable response.", method != "GET")
                if not isinstance(value, dict):
                    raise ApiError(0, "Unexpected API response.", method != "GET")
                return value, response.headers.get("ETag")
        except urllib.error.HTTPError as error:
            self._headers(error.headers)
            if error.code == 304 and method == "GET" and etag:
                return None, etag
            messages = {
                401: "Your API token was rejected. Reconnect in Settings.",
                403: "This token cannot perform that action. Check its API permissions and subscription.",
                404: "This item is no longer available on WaniKani.",
                422: "WaniKani rejected this change. Refresh progress before continuing.",
                429: "WaniKani rate limit reached. Synchronization will resume later.",
            }
            raise ApiError(error.code, messages.get(error.code, "WaniKani is temporarily unavailable."), method != "GET" and (error.code >= 500 or error.code in (304, 408))) from None
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError, http.client.HTTPException):
            raise ApiError(0, "You are offline or WaniKani could not be reached.", method != "GET") from None

    def _headers(self, headers):
        try:
            if int(headers.get("RateLimit-Remaining", "1")) <= 0:
                self.next_allowed = max(self.next_allowed, float(headers.get("RateLimit-Reset", self.clock() + 60)))
            if headers.get("Retry-After", "").isdigit():
                self.next_allowed = max(self.next_allowed, self.clock() + int(headers["Retry-After"]))
            if headers.get("Date"):
                from email.utils import parsedate_to_datetime
                self.server_offset = parsedate_to_datetime(headers["Date"]).timestamp() - self.clock()
        except (ValueError, TypeError, OverflowError):
            pass

    def collection(self, endpoint, params=None):
        path = endpoint + ("?" + urllib.parse.urlencode(params) if params else "")
        seen = set()
        while path:
            if not isinstance(path, str) or path in seen or len(seen) >= 250:
                raise ApiError(0, "Invalid API pagination.")
            seen.add(path)
            result, _ = self.request(path)
            if not isinstance(result, dict) or not isinstance(result.get("data"), list):
                raise ApiError(0, "Unexpected collection response.")
            yield result["data"]
            pages = result.get("pages", {})
            if not isinstance(pages, dict):
                raise ApiError(0, "Invalid API pagination.")
            path = pages.get("next_url")
