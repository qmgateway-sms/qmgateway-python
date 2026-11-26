from __future__ import annotations

import re
import secrets
from datetime import datetime
from typing import Any, Iterator, Literal

from . import models as M
from ._http import HttpClient, Options

Raw = dict[str, Any]


def _data(a: Raw) -> Raw:
    return a["data"] if isinstance(a.get("data"), dict) else {}


def _list(a: Raw) -> list[Raw]:
    return a["data"] if isinstance(a.get("data"), list) else []


def _cursor(v: Any) -> int | None:
    return None if v is None else int(v)


def _at(v: str | datetime) -> str:
    return M.to_malawi_time(v) if isinstance(v, datetime) else v


class Messages:
    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def send(self, to: str | list[str], message: str, *, type: str | None = None, device_id: int | None = None,
             scheduled_at: str | datetime | None = None, idempotency_key: str | None = None) -> M.SendResult:
        """Queue a message for one number or a list of numbers.

        An Idempotency-Key is added for you, so a retry after a timeout can never send twice. For jobs that may run again, pass your own.
        ``scheduled_at`` is Malawi time as text ("2026-12-01 08:00:00") or a datetime.
        """
        body: Raw = ({"recipients": list(to)} if isinstance(to, (list, tuple)) else {"phone": to}) | {"message": message}
        if type is not None: body["type"] = type
        if device_id is not None: body["device_id"] = device_id
        if scheduled_at is not None: body["scheduled_at"] = _at(scheduled_at)
        if idempotency_key is not None and not re.fullmatch(r"[!-~]{1,255}", idempotency_key):
            raise ValueError("idempotency_key must be 1 to 255 visible characters with no spaces.")
        key = idempotency_key or secrets.token_hex(16)
        return M.SendResult.from_dict(_data(self._http.request("POST", "/api/v1/messages", body=body, headers={"idempotency-key": key})))

    def get(self, id: int) -> M.Message:
        """One message and where it is now."""
        return M.Message.from_dict(_data(self._http.request("GET", "/api/v1/message_status", query={"id": id})))

    def list(self, *, status: str | None = None, phone: str | None = None, since: str | None = None, limit: int | None = None, before_id: int | None = None) -> M.Page[M.Message]:
        """One page of messages, newest first. Pass ``next_cursor`` as ``before_id`` for the next page."""
        a = self._http.request("GET", "/api/v1/messages", query={"status": status, "phone": phone, "since": since, "limit": limit, "before_id": before_id})
        return M.Page([M.Message.from_dict(x) for x in _list(a)], _cursor(a.get("next_before_id")))

    def each(self, *, status: str | None = None, phone: str | None = None, since: str | None = None, page_size: int = 100) -> Iterator[M.Message]:
        """Every matching message, newest first. Fetches the next page when you reach the end of the one before."""
        cursor: int | None = None
        while True:
            page = self.list(status=status, phone=phone, since=since, limit=page_size, before_id=cursor)
            yield from page.items
            cursor = page.next_cursor
            if cursor is None:
                return

    def scheduled(self, *, limit: int | None = None, after_id: int | None = None) -> M.Page[M.ScheduledMessage]:
        a = self._http.request("GET", "/api/v1/scheduled", query={"limit": limit, "after_id": after_id})
        return M.Page([M.ScheduledMessage.from_dict(x) for x in _list(a)], _cursor(a.get("next_after_id")))

    def each_scheduled(self, *, page_size: int = 100) -> Iterator[M.ScheduledMessage]:
        cursor: int | None = None
        while True:
            page = self.scheduled(limit=page_size, after_id=cursor)
            yield from page.items
            cursor = page.next_cursor
            if cursor is None:
                return

    def cancel(self, id: int) -> Raw:
        """Cancel a scheduled message. Its SMS units go back to your balance. Returns id, status, remaining_units."""
        return _data(self._http.request("POST", "/api/v1/message_cancel", body={"id": id}))

    def reschedule(self, id: int, scheduled_at: str | datetime) -> Raw:
        """Move a scheduled message to a new time. Returns id, status, scheduled_at."""
        return _data(self._http.request("POST", "/api/v1/message_reschedule", body={"id": id, "scheduled_at": _at(scheduled_at)}))


class Inbox:
    """Replies received on your gateway phones, oldest first."""

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def list(self, *, after_id: int | None = None, sender: str | None = None, limit: int | None = None) -> M.Page[M.InboxMessage]:
        a = self._http.request("GET", "/api/v1/inbox", query={"after_id": after_id, "from": sender, "limit": limit})
        return M.Page([M.InboxMessage.from_dict(x) for x in _list(a)], _cursor(a.get("next_after_id")))

    def each(self, *, sender: str | None = None, after_id: int | None = None, page_size: int = 100) -> Iterator[M.InboxMessage]:
        cursor = after_id
        while True:
            page = self.list(after_id=cursor, sender=sender, limit=page_size)
            yield from page.items
            cursor = page.next_cursor
            if cursor is None:
                return


class Devices:
    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def list(self) -> list[M.Device]:
        return [M.Device.from_dict(x) for x in _list(self._http.request("GET", "/api/v1/devices"))]


class Otp:
    """One-time passwords by SMS or email."""

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def send(self, *, channel: Literal["sms", "email"] = "sms", phone: str | None = None, email: str | None = None, purpose: str | None = None, expiry_seconds: int | None = None) -> M.OtpRequest:
        """Send a code. Retried only after a 429, so a code is never sent twice by accident."""
        body = {k: v for k, v in {"channel": channel, "phone": phone, "email": email, "purpose": purpose, "expiry_seconds": expiry_seconds}.items() if v is not None}
        return M.OtpRequest.from_dict(_data(self._http.request("POST", "/api/v1/otp/send", body=body, safe_to_repeat=False)))

    def verify(self, request_reference: str, code: str) -> M.OtpVerification:
        """A wrong or expired code gives verified = False. It is only an error when the request itself is wrong."""
        return M.OtpVerification.from_dict(_data(self._http.request("POST", "/api/v1/otp/verify", body={"request_reference": request_reference, "code": code}, safe_to_repeat=False)))


class Account:
    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def get(self) -> M.Account:
        return M.Account.from_dict(_data(self._http.request("GET", "/api/v1/account")))

    def balance(self) -> M.Balance:
        return M.Balance.from_dict(_data(self._http.request("GET", "/api/v1/balance")))

    def statistics(self, *, period: str | None = None, start_date: str | None = None, end_date: str | None = None) -> M.Statistics:
        return M.Statistics.from_dict(self._http.request("GET", "/api/v1/statistics", query={"period": period, "start_date": start_date, "end_date": end_date}))


class QMGateway:
    """The entry point.

        qm = QMGateway(os.environ["QMGATEWAY_API_KEY"])
        sent = qm.messages.send("+265999123456", "Your order is ready.")
    """

    def __init__(self, api_key: str, options: Options | None = None) -> None:
        http = HttpClient(api_key, options or Options())
        self.options = http.options
        self.messages = Messages(http)
        self.inbox = Inbox(http)
        self.devices = Devices(http)
        self.otp = Otp(http)
        self.account = Account(http)

    @classmethod
    def for_test(cls, api_key: str, options: Options | None = None) -> QMGateway:
        """Same as the constructor; reads better with a test key (qm_test_...): nothing reaches a phone and no units are used."""
        return cls(api_key, options)
