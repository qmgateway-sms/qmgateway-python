from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlsplit

from .errors import (ApiError, AuthenticationError, ConflictError, InvalidRequestError, NotFoundError, PermissionDeniedError,
                     QMConnectionError, RateLimitError, ServerError)

VERSION = "0.1.0"
MAX_WAIT = 60.0


@dataclass(frozen=True)
class TransportRequest:
    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes | None
    timeout: float
    retryable: bool = True


@dataclass(frozen=True)
class TransportResponse:
    status: int
    headers: Mapping[str, str]  # lower-case names
    body: bytes


class Transport(Protocol):
    def __call__(self, request: TransportRequest) -> TransportResponse:
        """Send one request. Raise QMConnectionError when no answer could be read."""


@dataclass(frozen=True)
class Options:
    """How a client behaves.

    base_url: where the API lives. https only; plain http is accepted for localhost (testing).
    timeout: seconds to wait for one request. A timeout counts as a network error.
    max_retries: extra tries after the first, for network errors, 429 and 5xx (0 turns retries off).
    transport: replaces the network (tests use qmgateway.testing.FakeTransport).
    sleep: replaces the real pause between retries (tests use it to run fast).
    """

    base_url: str = "https://qmgateway.com"
    timeout: float = 30.0
    max_retries: int = 4
    transport: Transport | None = None
    sleep: Callable[[float], None] | None = None
    user_agent: str | None = None

    def __post_init__(self) -> None:
        try:
            u = urlsplit(self.base_url)
            host = (u.hostname or "").lower()
        except ValueError:
            raise ValueError("base_url is not a valid web address.") from None
        local = host in ("localhost", "127.0.0.1", "::1")
        if not (u.scheme == "https" or (u.scheme == "http" and local)) or not host:
            raise ValueError("base_url must use https (plain http is only allowed for localhost).")
        if u.username or u.password:
            raise ValueError("base_url must not contain a user name or password.")
        if not (0 < self.timeout <= 300):
            raise ValueError("timeout must be between 0 and 300 seconds.")
        if not (isinstance(self.max_retries, int) and 0 <= self.max_retries <= 10):
            raise ValueError("max_retries must be a whole number from 0 to 10.")
        if self.user_agent and ("\n" in self.user_agent or "\r" in self.user_agent):
            raise ValueError("user_agent must be one line.")

    def root(self) -> str:
        return self.base_url.rstrip("/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a: Any, **k: Any) -> None:  # a redirect would resend the API key somewhere else
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def urllib_transport(r: TransportRequest) -> TransportResponse:
    """The built-in transport: standard library only, no redirects, certificates always checked."""
    req = urllib.request.Request(r.url, data=r.body, method=r.method, headers=dict(r.headers))
    try:
        with _opener.open(req, timeout=r.timeout) as res:
            return TransportResponse(res.status, {k.lower(): v for k, v in res.headers.items()}, res.read(8_000_001))
    except urllib.error.HTTPError as e:  # an answer with an error status is still an answer
        with e:
            return TransportResponse(e.code, {k.lower(): v for k, v in e.headers.items()}, e.read(8_000_001))
    except TimeoutError as e:
        raise QMConnectionError("The request timed out.") from e
    except (urllib.error.URLError, OSError) as e:
        raise QMConnectionError(f"Could not reach QMGateway ({getattr(e, 'reason', e)}).") from e


def _backoff(attempt: int) -> float:
    return min(2.0**attempt, MAX_WAIT) * (1 + random.SystemRandom().randint(0, 200) / 1000)


def _wait_for(res: TransportResponse, attempt: int) -> float:
    after = res.headers.get("retry-after")
    return min(float(after), MAX_WAIT) if after is not None and after.isdigit() else _backoff(attempt)


class HttpClient:
    """Sends requests and does what every call needs: the key, the retries, and turning an error answer into the right error.

    Retry rules (the shared SDK contract): network errors, 429 and 5xx are retried, other 4xx never; wait Retry-After (max 60 s)
    or 1, 2, 4, 8 s plus up to 20% jitter; same Idempotency-Key every try. A request that is not safe to repeat is retried only on 429.
    """

    def __init__(self, api_key: str, options: Options) -> None:
        if not api_key or any(c.isspace() for c in api_key):
            raise ValueError("The API key is missing or has spaces in it.")
        self._key = api_key
        self.options = options

    def request(self, method: str, path: str, *, query: Mapping[str, Any] | None = None, body: Mapping[str, Any] | None = None,
                headers: Mapping[str, str] | None = None, safe_to_repeat: bool = True) -> dict[str, Any]:
        q = {k: v for k, v in (query or {}).items() if v is not None}
        url = self.options.root() + path + ("?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote) if q else "")
        ua = f"qmgateway-python/{VERSION} python/{__import__('platform').python_version()}" + (f" {self.options.user_agent}" if self.options.user_agent else "")
        h = {"x-api-key": self._key, "accept": "application/json", "user-agent": ua, **(headers or {})}
        data = None
        if body is not None:
            h["content-type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        request = TransportRequest(method, url, h, data, self.options.timeout, safe_to_repeat)
        transport = self.options.transport or urllib_transport
        attempt = 0
        while True:
            last = attempt >= self.options.max_retries
            try:
                res = transport(request)
            except QMConnectionError:
                if last or not request.retryable:
                    raise
                self._pause(_backoff(attempt))
                attempt += 1
                continue
            if (res.status == 429 or (res.status >= 500 and request.retryable)) and not last:
                self._pause(_wait_for(res, attempt))
                attempt += 1
                continue
            return _decode(res)

    def _pause(self, seconds: float) -> None:
        (self.options.sleep or time.sleep)(seconds)


def _decode(res: TransportResponse) -> dict[str, Any]:
    try:
        data = json.loads(res.body.decode("utf-8", "replace"))
    except ValueError:
        data = None
    obj = data if isinstance(data, dict) else None
    if 200 <= res.status < 300 and obj is not None and obj.get("success") is True:
        return obj
    e = obj.get("error") if obj and isinstance(obj.get("error"), dict) else {}
    s = res.status
    code = e["code"] if isinstance(e.get("code"), str) else ("SERVER_ERROR" if s >= 500 else "INVALID_RESPONSE")
    message = e["message"] if isinstance(e.get("message"), str) else ("QMGateway had a problem. Please try again shortly." if s >= 500 else "QMGateway sent an answer this SDK cannot read.")
    rid = e["request_id"] if isinstance(e.get("request_id"), str) else res.headers.get("x-request-id")
    details = e["details"] if isinstance(e.get("details"), dict) else {}
    if s == 401: raise AuthenticationError(message, s, code, rid, details)
    if s == 403: raise PermissionDeniedError(message, s, code, rid, details)
    if s == 404: raise NotFoundError(message, s, code, rid, details)
    if s == 409: raise ConflictError(message, s, code, rid, details)
    if s == 429:
        ra = res.headers.get("retry-after")
        raise RateLimitError(message, s, code, rid, details, int(ra) if ra is not None and ra.isdigit() else None)
    if s >= 500: raise ServerError(message, s, code, rid, details)
    if s >= 400: raise InvalidRequestError(message, s, code, rid, details)
    raise ApiError(message, s, code, rid, details)
