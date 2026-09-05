"""Bounded HTTPS transport. A mutation is never retried by this layer."""
import json
import http.client
import math
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import timezone
from email.utils import parsedate_to_datetime
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


def elapsed_clock():
    """Monotonic elapsed time including Linux suspend; conservative fallback."""
    if hasattr(time, "CLOCK_BOOTTIME"):
        try:
            return time.clock_gettime(time.CLOCK_BOOTTIME)
        except OSError:
            pass
    return time.monotonic()


class RequestBudget:
    """Conservative rolling quota, shared by this worker's API connections.

    WaniKani documents 60 requests/minute, not a one-second request interval:
    https://docs.api.wanikani.com/20170710/#rate-limit
    Allow small bursts, always retain the local rolling-minute ceiling, and use
    monotonic deadlines for server quota/reset/Retry-After information.
    """
    def __init__(self, clock=time.time, monotonic=elapsed_clock, sleep=time.sleep):
        self.clock, self.monotonic, self.sleep = clock, monotonic, sleep
        self.lock = threading.Lock()
        self.requests = deque()
        self.limit = 60
        self.remaining = None
        self.reset_at = None
        self.blocked_until = 0
        self.server_epoch = None
        self.server_observed_at = None

    @staticmethod
    def date(value):
        try:
            parsed = parsedate_to_datetime(value)
            return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()
        except (ValueError, TypeError, OverflowError, AttributeError):
            return None

    def acquire(self):
        deadline = self.monotonic() + 1.05
        for _ in range(3):
            with self.lock:
                now = self.monotonic()
                while self.requests and self.requests[0] <= now - 60:
                    self.requests.popleft()
                if self.reset_at is not None and now >= self.reset_at:
                    self.remaining, self.reset_at = None, None
                until = self.blocked_until
                if self.remaining is not None and self.remaining <= 0:
                    until = max(until, self.reset_at or now + 60)
                if len(self.requests) >= self.limit:
                    until = max(until, self.requests[-self.limit] + 60)
                if len(self.requests) >= 10:
                    until = max(until, self.requests[-10] + 1)
                wait = until - now
                if wait <= 0:
                    self.requests.append(now)
                    if self.remaining is not None:
                        self.remaining -= 1
                    return
            # Smooth brief bursts only. Longer backoff releases the worker job
            # instead of blocking account controls until the next quota window.
            if self.monotonic() + wait > deadline:
                break
            self.sleep(max(0, wait))
        raise ApiError(429, "WaniKani rate limit reached. Synchronization will resume when requests are available.")

    def observe(self, headers, status=None):
        headers = headers or {}
        now = self.monotonic()
        server_date = self.date(headers.get("Date"))
        with self.lock:
            if server_date is not None:
                self.server_epoch, self.server_observed_at = server_date, now
            reference = (self.server_epoch + now - self.server_observed_at
                if self.server_epoch is not None else self.clock())
            try:
                limit = int(headers.get("RateLimit-Limit", ""))
                if limit > 0:
                    self.limit = min(60, limit)
            except (ValueError, TypeError, OverflowError):
                pass
            reset = None
            try:
                epoch = float(headers.get("RateLimit-Reset", ""))
                if math.isfinite(epoch) and epoch > reference:
                    # HTTP Date has second precision. A small margin keeps us
                    # on the safe side of a server window boundary.
                    reset = now + epoch - reference + 0.05
            except (ValueError, TypeError, OverflowError):
                pass
            try:
                remaining = int(headers.get("RateLimit-Remaining", ""))
                if remaining >= 0:
                    self.remaining = min(self.limit, remaining)
                    self.reset_at = reset or (self.reset_at if self.reset_at and self.reset_at > now else now + 60)
            except (ValueError, TypeError, OverflowError):
                pass
            retry = None
            value = str(headers.get("Retry-After", "")).strip()
            if value.isascii() and value.isdigit():
                try:
                    retry = float(int(value))
                except (ValueError, OverflowError):
                    pass
            elif value:
                retry_date = self.date(value)
                if retry_date is not None:
                    retry = max(0, retry_date - reference) + 0.05
            if retry is not None and math.isfinite(retry):
                self.blocked_until = max(self.blocked_until, now + retry)
            if status == 429:
                self.remaining = 0
                self.reset_at = max(reset or 0, self.blocked_until,
                    self.reset_at if self.reset_at and self.reset_at > now else 0)
                if self.reset_at <= now:
                    self.reset_at = now + 60
                self.blocked_until = max(self.blocked_until, self.reset_at)


class Api:
    BASE = "https://api.wanikani.com/v2/"

    def __init__(self, token, clock=time.time, limiter=None):
        self.token = token
        self.clock = clock
        self.limiter = limiter or RequestBudget(clock=clock)
        self.server_offset = 0
        self.opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))

    def request(self, path, method="GET", data=None, etag=None):
        url = path if path.startswith("https://") else self.BASE + path.lstrip("/")
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "api.wanikani.com" or not parsed.path.startswith("/v2/"):
            raise ApiError(0, "Rejected an unexpected API address.")
        headers = {"Authorization": "Bearer " + self.token, "Wanikani-Revision": "20170710", "Accept": "application/json", "User-Agent": "Omarchy-WaniKani/0.1"}
        if etag:
            headers["If-None-Match"] = etag
        body = None
        if data is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
            body = json.dumps(data).encode()
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        self.limiter.acquire()
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
            self._headers(error.headers, error.code)
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

    def _headers(self, headers, status=None):
        headers = headers or {}
        self.limiter.observe(headers, status)
        server_date = RequestBudget.date(headers.get("Date"))
        if server_date is not None:
            self.server_offset = server_date - self.clock()

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
