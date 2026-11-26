"""Runs the SDK against a real server:
   QMGATEWAY_BASE=https://qmgateway.com QMGATEWAY_LIVE_KEY=qm_live_... QMGATEWAY_TEST_KEY=qm_test_... python tests/live.py
"""
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from qmgateway import AuthenticationError, InvalidRequestError, Options, QMGateway  # noqa: E402

base = os.environ.get("QMGATEWAY_BASE", "https://qmgateway.com")
live, test = os.environ.get("QMGATEWAY_LIVE_KEY"), os.environ.get("QMGATEWAY_TEST_KEY")
if not live or not test:
    sys.exit("Set QMGATEWAY_LIVE_KEY and QMGATEWAY_TEST_KEY.")
o = Options(base_url=base, timeout=20, max_retries=1)
qm, qt = QMGateway(live, o), QMGateway.for_test(test, o)
n = bad = 0


def step(name):
    def deco(fn):
        global n, bad
        n += 1
        try:
            fn(); print("  ok  " + name)
        except Exception as e:  # noqa: BLE001
            bad += 1; print(f"FAIL  {name}: {type(e).__name__}: {e}")
        return fn
    return deco


@step("account")
def _(): a = qm.account.get(); assert a.organisation_name and not a.is_test_key and a.service("sms")
@step("balance")
def _(): assert qm.account.balance().quota > 0
@step("devices")
def _(): assert qm.devices.list()
@step("statistics")
def _(): assert isinstance(qm.account.statistics().overview, dict)
@step("inbox pages")
def _(): assert sum(1 for _ in qm.inbox.each(page_size=1)) >= 1
@step("test-key send then read it back")
def _():
    r = qt.messages.send("+265991234567", "SDK live test"); m = qt.messages.get(r.message_id); assert m.phone_number and m.mode == "test"
@step("same Idempotency-Key does not send twice")
def _():
    k = f"sdk-live-{random.randrange(10**9)}"
    a = qt.messages.send("+265991234567", "Once", idempotency_key=k); b = qt.messages.send("+265991234567", "Once", idempotency_key=k)
    assert a.message_id == b.message_id and b.idempotent_replay
@step("list messages with auto-pagination")
def _():
    for i in range(3): qt.messages.send("+265991234567", f"Page test {i}")
    c = 0
    for _ in qt.messages.each(page_size=2):
        c += 1
        if c >= 5: break
    assert c >= 3
@step("schedule, list, reschedule, cancel (live key)")
def _():
    now = datetime.now(timezone.utc)
    r = qm.messages.send("+265991234567", "SDK scheduled", scheduled_at=now + timedelta(days=3)); i = r.message_id
    assert any(s.id == i for s in qm.messages.each_scheduled(page_size=5)), "not listed"
    assert qm.messages.reschedule(i, now + timedelta(days=4))["id"] == i
    assert qm.messages.cancel(i)["status"]
@step("errors are typed")
def _():
    try: QMGateway("qm_live_" + "0" * 48, o).account.get(); raise AssertionError("bad key accepted")
    except AuthenticationError as e: assert e.status == 401 and e.request_id
    try: qm.messages.send("not-a-number", "x"); raise AssertionError("bad number accepted")
    except InvalidRequestError as e: assert e.code
@step("test key is refused on account endpoints")
def _():
    try: qt.account.balance(); raise AssertionError("allowed")
    except AuthenticationError as e: assert e.code == "TEST_KEY_NOT_ALLOWED", e.code

print(f"\n{n - bad} passed, {bad} failed")
sys.exit(1 if bad else 0)
