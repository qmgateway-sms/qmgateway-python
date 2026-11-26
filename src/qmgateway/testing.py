"""A pretend network for your own tests.

    fake = FakeTransport().queue_json({"success": True, "data": {}}, 202)
    qm = QMGateway("qm_test_x", Options(transport=fake))
"""
from __future__ import annotations

import json
from typing import Any

from ._http import TransportRequest, TransportResponse
from .errors import QMConnectionError


class FakeTransport:
    def __init__(self) -> None:
        self.requests: list[TransportRequest] = []
        self._answers: list[TransportResponse | QMConnectionError] = []

    def queue_raw(self, status: int, body: str, headers: dict[str, str] | None = None) -> FakeTransport:
        self._answers.append(TransportResponse(status, {k.lower(): v for k, v in (headers or {}).items()}, body.encode()))
        return self

    def queue_json(self, data: Any, status: int = 200, headers: dict[str, str] | None = None) -> FakeTransport:
        return self.queue_raw(status, json.dumps(data), headers)

    def queue_error(self, status: int, code: str, message: str = "Error", *, headers: dict[str, str] | None = None, details: dict[str, Any] | None = None) -> FakeTransport:
        return self.queue_json({"success": False, "error": {"code": code, "message": message, "request_id": "req_fake", "details": details or {}}}, status, headers)

    def queue_network_error(self, message: str = "Could not connect") -> FakeTransport:
        self._answers.append(QMConnectionError(message))
        return self

    def __call__(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        if not self._answers:
            raise AssertionError(f"FakeTransport has no answer queued for {request.method} {request.url}")
        nxt = self._answers.pop(0)
        if isinstance(nxt, QMConnectionError):
            raise nxt
        return nxt

    @property
    def last(self) -> TransportRequest:
        if not self.requests:
            raise AssertionError("Nothing was sent yet.")
        return self.requests[-1]
