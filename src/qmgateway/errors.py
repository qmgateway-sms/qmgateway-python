"""Everything this SDK raises is a QMGatewayError, so one ``except`` can handle it all."""
from __future__ import annotations

from typing import Any, Literal


class QMGatewayError(Exception):
    pass


class ApiError(QMGatewayError):
    """QMGateway answered with an error. Branch on ``code`` (stable); show ``message`` to people (it may be reworded)."""

    def __init__(self, message: str, status: int, code: str, request_id: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(f"{message} (request {request_id})" if request_id else message)
        self.message = message
        self.status = status
        self.code = code
        self.request_id = request_id
        #: Extra facts for some codes, for example remaining_units for INSUFFICIENT_BALANCE.
        self.details = details or {}


class AuthenticationError(ApiError): ...
class PermissionDeniedError(ApiError): ...
class InvalidRequestError(ApiError): ...
class NotFoundError(ApiError): ...
class ConflictError(ApiError): ...
class ServerError(ApiError): ...


class RateLimitError(ApiError):
    def __init__(self, message: str, status: int, code: str, request_id: str | None, details: dict[str, Any] | None, retry_after: int | None) -> None:
        super().__init__(message, status, code, request_id, details)
        #: Seconds the server asked you to wait, when it said.
        self.retry_after = retry_after


class QMConnectionError(QMGatewayError):
    """No answer could be read (DNS, connection, TLS or timeout), after the retries were used up."""


class SignatureError(QMGatewayError):
    """A webhook request is not genuine. ``reason`` is bad_signature, stale_timestamp or missing_header. Answer 401 and do nothing else."""

    def __init__(self, reason: Literal["bad_signature", "stale_timestamp", "missing_header"]) -> None:
        super().__init__(f"The webhook could not be verified: {reason}")
        self.reason = reason
