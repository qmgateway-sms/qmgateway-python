import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qmgateway import (ApiError, AuthenticationError, InvalidRequestError, NotFoundError, Options, PermissionDeniedError, QMConnectionError,  # noqa: E402
                       QMGateway, RateLimitError, ServerError, SignatureError, sign_webhook, verify_webhook)
from qmgateway.testing import FakeTransport  # noqa: E402

_here = Path(__file__).resolve().parent
CONTRACT = Path(os.environ.get("QMGATEWAY_CONTRACT_DIR") or (_here.parent.parent / "sdk-contract" if (_here.parent.parent / "sdk-contract").is_dir() else _here / "contract"))
contract = lambda f: json.loads((CONTRACT / f).read_text("utf-8"))  # noqa: E731

SENT = {"success": True, "data": {"message_ids": [7], "recipients": 1, "sms_units": 1, "status": "Queued", "remaining_units": 99, "idempotent_replay": False, "numbers": ["+265999123456"]}}


def make(fake, retries=4):
    sleeps = []
    return QMGateway("qm_test_abc", Options(transport=fake, max_retries=retries, sleep=sleeps.append)), sleeps


class Requests(unittest.TestCase):
    def test_send_builds_request_and_result(self):
        fake = FakeTransport().queue_json(SENT, 202)
        r = make(fake)[0].messages.send("+265999123456", "Hi", scheduled_at="2026-12-01 08:00:00")
        self.assertEqual((r.message_id, r.remaining_units), (7, 99))
        q = fake.last
        self.assertEqual((q.method, q.url), ("POST", "https://qmgateway.com/api/v1/messages"))
        self.assertEqual(q.headers["x-api-key"], "qm_test_abc")
        self.assertEqual(json.loads(q.body), {"phone": "+265999123456", "message": "Hi", "scheduled_at": "2026-12-01 08:00:00"})
        self.assertEqual(len(q.headers["idempotency-key"]), 32)

    def test_datetime_is_sent_as_malawi_time(self):
        fake = FakeTransport().queue_json(SENT, 202)
        make(fake)[0].messages.send("+265999123456", "Hi", scheduled_at=datetime(2026, 12, 1, 6, 0, tzinfo=timezone.utc))
        self.assertEqual(json.loads(fake.last.body)["scheduled_at"], "2026-12-01 08:00:00")

    def test_many_recipients_and_query_encoding(self):
        fake = FakeTransport().queue_json(SENT, 202).queue_json({"success": True, "data": [], "next_before_id": None})
        qm, _ = make(fake)
        qm.messages.send(["+265999123456", "+265888123456"], "Hi")
        self.assertEqual(json.loads(fake.last.body)["recipients"], ["+265999123456", "+265888123456"])
        qm.messages.list(status="Failed", phone="+265999123456")
        self.assertEqual(fake.last.url, "https://qmgateway.com/api/v1/messages?status=Failed&phone=%2B265999123456")

    def test_unknown_fields_ignored_and_kept(self):
        d = {**SENT, "data": {**SENT["data"], "brand_new": "x"}}
        self.assertEqual(make(FakeTransport().queue_json(d, 202))[0].messages.send("+265999123456", "Hi").raw["brand_new"], "x")

    def test_options_checked(self):
        for bad in (dict(base_url="http://qmgateway.com"), dict(timeout=0), dict(max_retries=11)):
            with self.assertRaises(ValueError):
                Options(**bad)
        with self.assertRaises(ValueError):
            QMGateway("bad key")
        Options(base_url="http://127.0.0.1:8120")


class Safety(unittest.TestCase):
    def test_idempotency_key_with_line_break_refused(self):
        with self.assertRaises(ValueError):
            make(FakeTransport())[0].messages.send("+265999123456", "x", idempotency_key="a\r\nX-Evil: 1")


class Errors(unittest.TestCase):
    def test_status_mapping(self):
        for status, cls in [(401, AuthenticationError), (403, PermissionDeniedError), (404, NotFoundError), (422, InvalidRequestError), (400, InvalidRequestError)]:
            fake = FakeTransport().queue_error(status, "SOME_CODE", "Bad thing")
            with self.assertRaises(cls) as c:
                make(fake)[0].account.get()
            e = c.exception
            self.assertEqual((e.code, e.request_id, e.status, e.message), ("SOME_CODE", "req_fake", status, "Bad thing"))
            self.assertEqual(len(fake.requests), 1, f"no retry on {status}")

    def test_details_and_unreadable(self):
        with self.assertRaises(ApiError) as c:
            make(FakeTransport().queue_error(402, "INSUFFICIENT_BALANCE", "No units", details={"remaining_units": 0}))[0].messages.send("+265999123456", "x")
        self.assertEqual(c.exception.details["remaining_units"], 0)
        with self.assertRaises(ApiError) as c:
            make(FakeTransport().queue_raw(200, "<html>oops</html>"))[0].account.get()
        self.assertEqual(c.exception.code, "INVALID_RESPONSE")


class Retries(unittest.TestCase):
    def test_429_503_then_ok_same_key(self):
        fake = FakeTransport().queue_error(429, "RATE_LIMITED", headers={"Retry-After": "1"}).queue_error(503, "SERVICE_UNAVAILABLE").queue_json(SENT, 202)
        qm, sleeps = make(fake)
        qm.messages.send("+265999123456", "Hi")
        self.assertEqual(len(fake.requests), 3)
        self.assertEqual(sleeps[0], 1.0)
        self.assertTrue(2.0 <= sleeps[1] <= 2.4)
        self.assertEqual(len({r.headers["idempotency-key"] for r in fake.requests}), 1)

    def test_always_unavailable(self):
        fake = FakeTransport()
        for _ in range(5): fake.queue_error(503, "SERVICE_UNAVAILABLE")
        with self.assertRaises(ServerError) as c:
            make(fake)[0].messages.send("+265999123456", "Hi")
        self.assertEqual((len(fake.requests), c.exception.status), (5, 503))

    def test_retry_after_capped(self):
        fake = FakeTransport().queue_error(429, "RATE_LIMITED", headers={"Retry-After": "3600"}).queue_json(SENT, 202)
        qm, sleeps = make(fake)
        qm.messages.send("+265999123456", "Hi")
        self.assertEqual(sleeps, [60.0])

    def test_network_errors_and_zero_retries(self):
        fake = FakeTransport()
        for _ in range(3): fake.queue_network_error()
        with self.assertRaises(QMConnectionError):
            make(fake, 2)[0].messages.send("+265999123456", "Hi")
        self.assertEqual(len(fake.requests), 3)
        f2 = FakeTransport().queue_error(503, "X")
        with self.assertRaises(ServerError):
            make(f2, 0)[0].account.get()
        self.assertEqual(len(f2.requests), 1)

    def test_codes_not_repeated_except_429(self):
        f = FakeTransport().queue_error(503, "X")
        with self.assertRaises(ServerError): make(f)[0].otp.send(phone="+265999123456")
        self.assertEqual(len(f.requests), 1)
        f = FakeTransport().queue_network_error()
        with self.assertRaises(QMConnectionError): make(f)[0].otp.send(phone="+265999123456")
        self.assertEqual(len(f.requests), 1)
        f = FakeTransport().queue_error(429, "R", headers={"Retry-After": "1"}).queue_json({"success": True, "data": {"request_reference": "r1", "expires_in": 300, "status": "sent", "channel": "sms"}})
        self.assertEqual(make(f)[0].otp.send(phone="+265999123456").request_reference, "r1")

    def test_final_rate_limit_has_retry_after(self):
        fake = FakeTransport()
        for _ in range(5): fake.queue_error(429, "R", headers={"Retry-After": "7"})
        with self.assertRaises(RateLimitError) as c:
            make(fake)[0].account.get()
        self.assertEqual(c.exception.retry_after, 7)


class Pagination(unittest.TestCase):
    def test_cases(self):
        for c in contract("pagination-cases.json")["cases"]:
            with self.subTest(c["name"]):
                fake, inbox = FakeTransport(), c["operationId"] == "get_inbox"
                for i, ids in enumerate(c["pages"]):
                    items = [{"id": n, "from": "+265999", "message": "m", "received_at": "2026-11-19 10:29:41"} if inbox else
                             {"id": n, "phone_number": "+265999", "status": "Sent", "message_type": "sms", "sms_units": 1} for n in ids]
                    fake.queue_json({"success": True, "data": items, c["next_field"]: ids[-1] if i + 1 < len(c["pages"]) else None})
                qm, _ = make(fake)
                got = [m.id for m in (qm.inbox.each() if inbox else qm.messages.each())]
                self.assertEqual(got, c["expect_ids"])
                self.assertEqual(len(fake.requests), len(c["pages"]))
                if len(c["pages"]) > 1:
                    self.assertIn(c["param"] + "=", fake.requests[1].url)


class Webhooks(unittest.TestCase):
    def test_shared_cases(self):
        wc = contract("webhook-cases.json")
        for c in wc["cases"]:
            with self.subTest(c["id"]):
                run = lambda: verify_webhook(c["body"], c["headers"], wc["secret"], tolerance=wc["tolerance_seconds"], now=wc["now"])  # noqa: E731
                if c["expect_verified"]:
                    e = run()
                    self.assertEqual((e.type, e.message_id), (c["headers"]["X-QMGateway-Event"], 1052))
                else:
                    with self.assertRaises(SignatureError) as x:
                        run()
                    self.assertEqual(x.exception.reason, c["reason"])

    def test_sign_roundtrip_with_bytes(self):
        body, headers = sign_webhook('{"message_id":5,"status":"Failed"}', "whsec_x", event="sms.failed")
        e = verify_webhook(body.encode(), headers, "whsec_x")
        self.assertEqual((e.type, e.status), ("sms.failed", "Failed"))


class Models(unittest.TestCase):
    def test_parse(self):
        a = make(FakeTransport().queue_json({"success": True, "data": {"organisation": {"id": 3, "name": "Acme"}, "key": {"mode": "test", "scopes": ["messages:send"]}, "services": [{"key": "sms", "name": "SMS", "status": "active", "details": {"ready_to_send": True}}]}}))[0].account.get()
        self.assertTrue(a.is_test_key and a.service("sms").ready_to_send)
        d = make(FakeTransport().queue_json({"success": True, "data": [{"id": 1, "name": "Phone", "status": "online", "last_seen_at": "2026-11-19 10:29:41", "networks": ["Airtel"], "capacity": 2, "queued": 0}]}))[0].devices.list()
        self.assertTrue(d[0].is_online)
        self.assertEqual(d[0].last_seen_at.astimezone(timezone.utc).hour, 8)
        m = make(FakeTransport().queue_json({"success": True, "data": {"id": 9, "phone_number": "+265999123456", "status": "Delivered", "message_type": "sms", "sms_units": 1}}))[0].messages.get(9)
        self.assertTrue(m.is_delivered and m.is_finished)


if __name__ == "__main__":
    unittest.main()
