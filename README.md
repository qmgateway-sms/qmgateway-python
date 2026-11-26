# QMGateway for Python

Send SMS and one-time passwords from Python. Needs **Python 3.10 or newer**. It uses only the standard library, so installing it brings nothing else with it. Fully typed.

```
pip install qmgateway
```

## Send a message

```python
import os
from qmgateway import QMGateway

qm = QMGateway(os.environ["QMGATEWAY_API_KEY"])

sent = qm.messages.send("+265999123456", "Your order is ready.")
print(f"Queued message {sent.message_id}, {sent.remaining_units} SMS left")

print(qm.messages.get(sent.message_id).status)
```

Use a test key (it starts with `qm_test_`; create one on the API keys page of your account) while you build: nothing reaches a phone and no SMS are used. Keep keys out of your code: read them from the environment.
Calls wait for the answer (they are not `async`). In an async program, run them with `asyncio.to_thread(...)`.

## What you can do

| | |
|---|---|
| `qm.messages.send(to, text, scheduled_at="2026-12-01 08:00:00")` | one number, or a list for several |
| `qm.messages.get(id)` / `list(status="Failed")` / `each(status="Failed")` | track delivery; `each()` fetches more pages for you |
| `qm.messages.scheduled()` / `cancel(id)` / `reschedule(id, time)` | scheduled messages |
| `qm.inbox.list()` / `each()` | replies received (`message.sender` is the number it came from) |
| `qm.otp.send(phone="+265999123456")` / `verify(ref, code)` | one-time passwords |
| `qm.devices.list()` | your gateway phones |
| `qm.account.get()` / `balance()` / `statistics()` | account and usage |

```python
for m in qm.messages.each(status="Failed"):
    print(f"{m.id} to {m.phone_number} failed: {m.failure_reason}")
```

## Errors

Everything the SDK raises is a `QMGatewayError`. API errors are `ApiError`s with a stable `code`, the HTTP `status` and a `request_id` to quote to support.

```python
from qmgateway import ApiError, RateLimitError, QMConnectionError

try:
    qm.messages.send(phone, text)
except RateLimitError as e:
    print("rate limited, try again in", e.retry_after, "seconds")
except ApiError as e:
    print(e.code, e.status, e.request_id)
except QMConnectionError:
    print("no answer; resend with the same idempotency_key to be safe")
```

## Retries and duplicates

Network errors, rate limits (429) and server errors (5xx) are retried up to 4 times, waiting for `Retry-After` when given, otherwise 1, 2, 4, 8 seconds. Other errors are never retried. Every send carries an `Idempotency-Key` (made for you), kept the same across retries, so a retry can never send twice. For jobs that may run again, pass your own: `send(to, text, idempotency_key=f"order-{order_id}")`. Sending a one-time password is retried only after a 429.

```python
from qmgateway import Options
qm = QMGateway(key, Options(timeout=10, max_retries=2))
```

## Webhooks

```python
from qmgateway import verify_webhook, SignatureError

# Flask: request.get_data() is the untouched body.
@app.post("/webhooks/qmgateway")
def hook():
    try:
        event = verify_webhook(request.get_data(), request.headers, os.environ["QMGATEWAY_WEBHOOK_SECRET"])
    except SignatureError:
        return "", 401
    if event.type == "sms.delivered":
        print("delivered", event.message_id)
    return "", 200
```

Use the raw body exactly as received. Requests older than 5 minutes are refused.

## Testing your own code

```python
from qmgateway import Options, QMGateway
from qmgateway.testing import FakeTransport

fake = FakeTransport().queue_json({"success": True, "data": {"message_ids": [7], "recipients": 1, "sms_units": 1, "status": "Queued", "remaining_units": 99, "idempotent_replay": False, "numbers": ["+265999123456"]}}, 202)
qm = QMGateway("qm_test_x", Options(transport=fake))

sent = qm.messages.send("+265999123456", "Hello")
print(sent.message_id)                    # 7
print(fake.last.headers["x-api-key"])    # qm_test_x
```

`queue_error()` and `queue_network_error()` play failures; `fake.requests` shows what was sent. `sign_webhook()` builds a correctly signed request for testing your handler.

## Command line

```
# paste a test key from the API keys page of your QMGateway account (it starts with qm_test_)
export QMGATEWAY_API_KEY="<your test key>"      # Windows PowerShell: $env:QMGATEWAY_API_KEY = "<your test key>"
qmgateway send +265999123456 "Hello"
qmgateway help
```

## Developing this SDK

`python -m unittest discover -s tests` runs the tests (they use the shared contract files in `tests/contract`, or `QMGATEWAY_CONTRACT_DIR`). `python tests/live.py` checks it against a real server: set `QMGATEWAY_BASE`, `QMGATEWAY_LIVE_KEY` and `QMGATEWAY_TEST_KEY` first. Use the keys of a test organisation, because the live checks queue real messages.

Security problems: see [SECURITY.md](SECURITY.md). Licence: MIT.
