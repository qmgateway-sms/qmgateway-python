# Changelog

## 0.1.0 (unreleased)
- First version: messages (send, send to many, status, list, scheduled, cancel, reschedule), inbox, devices, one-time passwords, account, balance and statistics.
- Python 3.10 or newer, standard library only (no dependencies), fully typed (`py.typed`).
- Typed results and typed errors (`AuthenticationError`, `PermissionDeniedError`, `InvalidRequestError`, `NotFoundError`, `RateLimitError`, `ServerError`, `QMConnectionError`).
- Safe retries with the same `Idempotency-Key`, `Retry-After` support, 30 second timeout.
- Auto-pagination (`messages.each()`, `inbox.each()`, `messages.each_scheduled()`).
- `verify_webhook` with typed events, `sign_webhook`, `qmgateway.testing.FakeTransport` and the `qmgateway` command-line tool.
- Security: a caller-supplied idempotency key must be 1 to 255 visible characters with no spaces, so it cannot be used to inject a header.
