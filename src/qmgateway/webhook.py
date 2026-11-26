from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any, Mapping

from .errors import SignatureError
from .models import parse_time
from datetime import datetime

WEBHOOK_TOLERANCE = 300


@dataclass(frozen=True, slots=True)
class WebhookEvent:
    """A verified webhook delivery. Types: sms.incoming, sms.sent, sms.delivered, sms.failed, webhook.test."""
    type: str
    id: str
    attempt: int
    data: dict[str, Any] = field(repr=False)

    @property
    def message_id(self) -> int | None: return None if self.data.get("message_id") is None else int(self.data["message_id"])
    @property
    def phone_number(self) -> str | None: return None if self.data.get("phone_number") is None else str(self.data["phone_number"])
    @property
    def status(self) -> str | None: return None if self.data.get("status") is None else str(self.data["status"])
    @property
    def updated_at(self) -> datetime | None: return parse_time(self.data.get("updated_at"))
    @property
    def is_test(self) -> bool: return self.type == "webhook.test"


def verify_webhook(body: str | bytes, headers: Mapping[str, str], secret: str, *, tolerance: int = WEBHOOK_TOLERANCE, now: int | None = None) -> WebhookEvent:
    """Check that a webhook really came from QMGateway. Pass the RAW body exactly as received, not re-encoded JSON.

    Raises SignatureError when it is not genuine. ``now`` is unix seconds (tests pass a fixed one).
    """
    h = {k.lower(): v for k, v in headers.items()}
    signature, timestamp = h.get("x-qmgateway-signature", ""), h.get("x-qmgateway-timestamp", "")
    if not signature or not timestamp:
        raise SignatureError("missing_header")
    if not (timestamp.isascii() and timestamp.isdigit()) or abs((int(time.time()) if now is None else now) - int(timestamp)) > tolerance:
        raise SignatureError("stale_timestamp")
    raw = body if isinstance(body, bytes) else body.encode("utf-8")
    expected = "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected.encode(), signature.encode()):
        raise SignatureError("bad_signature")
    try:
        data = json.loads(raw)
    except ValueError:
        raise SignatureError("bad_signature") from None
    if not isinstance(data, dict):
        raise SignatureError("bad_signature")
    return WebhookEvent(h.get("x-qmgateway-event", ""), h.get("x-qmgateway-event-id", ""), int(h.get("x-qmgateway-attempt", "1") or 1), data)


def sign_webhook(body: str, secret: str, *, event: str = "sms.delivered", timestamp: int | None = None, event_id: str = "evt_test") -> tuple[str, dict[str, str]]:
    """Make a correctly signed request, for testing your own webhook handler. Returns (body, headers)."""
    t = str(int(time.time()) if timestamp is None else timestamp)
    sig = "sha256=" + hmac.new(secret.encode(), t.encode() + b"." + body.encode(), hashlib.sha256).hexdigest()
    return body, {"X-QMGateway-Timestamp": t, "X-QMGateway-Signature": sig, "X-QMGateway-Event": event, "X-QMGateway-Event-ID": event_id, "X-QMGateway-Attempt": "1"}
