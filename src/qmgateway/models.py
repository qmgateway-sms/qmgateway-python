from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Generic, TypeVar

Raw = dict[str, Any]
MALAWI = timezone(timedelta(hours=2), "Africa/Blantyre")
T = TypeVar("T")


def parse_time(v: Any) -> datetime | None:
    """Reads the dates QMGateway sends. "2026-11-19 10:29:41" is Malawi time (UTC+2); "2026-12-01T08:00:00+02:00" has its own offset."""
    if not isinstance(v, str) or not v:
        return None
    try:
        d = datetime.fromisoformat(v)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=MALAWI)


def to_malawi_time(d: datetime) -> str:
    """Malawi time as the API wants it when you schedule: "2026-12-01 08:00:00". A naive datetime is taken as Malawi time."""
    if d.tzinfo is not None:
        d = d.astimezone(MALAWI)
    return d.strftime("%Y-%m-%d %H:%M:%S")


def _s(v: Any) -> str: return "" if v is None else str(v)
def _i(v: Any, d: int = 0) -> int: return d if v is None else int(v)
def _n(v: Any) -> str | None: return None if v is None else str(v)


@dataclass(frozen=True, slots=True)
class Message:
    id: int
    phone_number: str
    status: str
    message_type: str
    sms_units: int
    scheduled_time: datetime | None
    created_at: datetime | None
    sent_at: datetime | None
    delivered_at: datetime | None
    failed_at: datetime | None
    failure_reason: str | None
    mode: str | None
    raw: Raw = field(repr=False, compare=False)

    @classmethod
    def from_dict(cls, d: Raw) -> Message:
        return cls(_i(d["id"]), _s(d["phone_number"]), _s(d["status"]), _s(d.get("message_type")), _i(d.get("sms_units"), 1), parse_time(d.get("scheduled_time")),
                   parse_time(d.get("created_at")), parse_time(d.get("sent_at")), parse_time(d.get("delivered_at")), parse_time(d.get("failed_at")),
                   _n(d.get("failure_reason")), _n(d.get("mode")), d)

    @property
    def is_delivered(self) -> bool: return self.status == "Delivered"
    @property
    def is_failed(self) -> bool: return self.status == "Failed"
    @property
    def is_finished(self) -> bool:
        """Delivered, failed or cancelled: nothing more will happen to it."""
        return self.status in ("Delivered", "Failed", "Cancelled")


@dataclass(frozen=True, slots=True)
class SendResult:
    message_ids: list[int]
    recipients: int
    sms_units: int
    status: str
    remaining_units: int
    idempotent_replay: bool
    numbers: list[str]
    raw: Raw = field(repr=False, compare=False)

    @classmethod
    def from_dict(cls, d: Raw) -> SendResult:
        return cls([int(x) for x in d.get("message_ids", [])], _i(d.get("recipients")), _i(d.get("sms_units")), _s(d.get("status")), _i(d.get("remaining_units")),
                   bool(d.get("idempotent_replay", False)), [str(x) for x in d.get("numbers", [])], d)

    @property
    def message_id(self) -> int:
        """The id of the message, when you sent to one number."""
        if not self.message_ids:
            raise LookupError("No message was queued.")
        return self.message_ids[0]


@dataclass(frozen=True, slots=True)
class InboxMessage:
    id: int
    sender: str  # the API calls it "from"
    message: str
    received_at: datetime | None
    raw: Raw = field(repr=False, compare=False)

    @classmethod
    def from_dict(cls, d: Raw) -> InboxMessage:
        return cls(_i(d["id"]), _s(d["from"]), _s(d["message"]), parse_time(d.get("received_at")), d)


@dataclass(frozen=True, slots=True)
class ScheduledMessage:
    id: int
    phone_number: str
    message: str
    sms_units: int
    scheduled_at: datetime | None
    created_at: datetime | None
    raw: Raw = field(repr=False, compare=False)

    @classmethod
    def from_dict(cls, d: Raw) -> ScheduledMessage:
        return cls(_i(d["id"]), _s(d["phone_number"]), _s(d.get("message")), _i(d.get("sms_units"), 1), parse_time(d.get("scheduled_at")), parse_time(d.get("created_at")), d)


@dataclass(frozen=True, slots=True)
class Device:
    id: int
    name: str
    status: str
    last_seen_at: datetime | None
    networks: list[str]
    capacity: int
    queued: int
    raw: Raw = field(repr=False, compare=False)

    @classmethod
    def from_dict(cls, d: Raw) -> Device:
        return cls(_i(d["id"]), _s(d["name"]), _s(d["status"]), parse_time(d.get("last_seen_at")), [str(x) for x in d.get("networks", [])], _i(d.get("capacity"), 1), _i(d.get("queued")), d)

    @property
    def is_online(self) -> bool: return self.status == "online"


@dataclass(frozen=True, slots=True)
class EmailOtpBalance:
    included: bool
    quota: int
    used: int
    remaining: int
    period_start: str | None
    resets_at: str | None


@dataclass(frozen=True, slots=True)
class Balance:
    active: bool
    plan: str | None
    quota: int
    used: int
    reserved: int
    remaining: int
    percent_left: int
    level: str
    starts_at: str | None
    expires_at: str | None
    days_left: int | None
    email_otp: EmailOtpBalance | None
    raw: Raw = field(repr=False, compare=False)

    @classmethod
    def from_dict(cls, d: Raw) -> Balance:
        e = d.get("email_otp")
        eo = EmailOtpBalance(bool(e.get("included")), _i(e.get("quota")), _i(e.get("used")), _i(e.get("remaining")), _n(e.get("period_start")), _n(e.get("resets_at"))) if isinstance(e, dict) else None
        return cls(bool(d["active"]), _n(d.get("plan")), _i(d["quota"]), _i(d["used"]), _i(d["reserved"]), _i(d["remaining"]), _i(d["percent_left"]), _s(d["level"]),
                   _n(d.get("starts_at")), _n(d.get("expires_at")), None if d.get("days_left") is None else int(d["days_left"]), eo, d)

    @property
    def is_low(self) -> bool: return self.level in ("low", "critical", "empty")


@dataclass(frozen=True, slots=True)
class Service:
    key: str
    name: str
    status: str
    details: Raw

    @property
    def ready_to_send(self) -> bool:
        """True when a message could go out right now (plan active, SMS left, a phone online)."""
        return bool(self.details.get("ready_to_send", False))


@dataclass(frozen=True, slots=True)
class Account:
    organisation_id: int
    organisation_name: str
    key_mode: str
    scopes: list[str]
    services: list[Service]
    raw: Raw = field(repr=False, compare=False)

    @classmethod
    def from_dict(cls, d: Raw) -> Account:
        org, key = d.get("organisation") or {}, d.get("key") or {}
        return cls(_i(org.get("id")), _s(org.get("name")), _s(key.get("mode", "live")), [str(x) for x in key.get("scopes", [])],
                   [Service(_s(s["key"]), _s(s["name"]), _s(s["status"]), s.get("details") or {}) for s in d.get("services", [])], d)

    def service(self, key: str) -> Service | None:
        return next((s for s in self.services if s.key == key), None)

    @property
    def is_test_key(self) -> bool: return self.key_mode == "test"


@dataclass(frozen=True, slots=True)
class OtpRequest:
    request_reference: str
    expires_in: int
    status: str
    channel: str
    email_otp_remaining: int | None
    email_otp_resets_at: str | None
    raw: Raw = field(repr=False, compare=False)

    @classmethod
    def from_dict(cls, d: Raw) -> OtpRequest:
        return cls(_s(d["request_reference"]), _i(d["expires_in"]), _s(d["status"]), _s(d["channel"]), None if d.get("email_otp_remaining") is None else int(d["email_otp_remaining"]), _n(d.get("email_otp_resets_at")), d)


@dataclass(frozen=True, slots=True)
class OtpVerification:
    """The answer to a code check. A wrong code is a normal answer (verified False), not an error."""
    verified: bool
    status: str

    @classmethod
    def from_dict(cls, d: Raw) -> OtpVerification:
        return cls(bool(d["verified"]), _s(d["status"]))


@dataclass(frozen=True, slots=True)
class Statistics:
    overview: dict[str, int]
    quota: Raw
    recent_messages: list[Raw]
    daily: list[Raw]
    status_distribution: list[Raw]
    top_recipients: list[Raw]
    counts: dict[str, int]
    period: Raw
    raw: Raw = field(repr=False, compare=False)

    @classmethod
    def from_dict(cls, d: Raw) -> Statistics:
        s = d.get("statistics") or {}
        return cls(s.get("overview", {}), s.get("quota", {}), s.get("recent_messages", []), s.get("daily", []), s.get("status_distribution", []), s.get("top_recipients", []), s.get("counts", {}), d.get("period", {}), d)


@dataclass(frozen=True, slots=True)
class Page(Generic[T]):
    """One page of a list, and where the next one starts (None when there is no more)."""
    items: list[T]
    next_cursor: int | None

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.items)

    def __len__(self) -> int: return len(self.items)
    @property
    def has_more(self) -> bool: return self.next_cursor is not None
