"""Command-line tool.  QMGATEWAY_API_KEY=qm_live_... qmgateway account

The key is read from the environment on purpose: a key typed as an argument stays in your shell history.
"""
from __future__ import annotations

import json
import os
import sys

from . import ApiError, Options, QMGateway, QMGatewayError, SignatureError, verify_webhook

HELP = """qmgateway command-line tool

Set QMGATEWAY_API_KEY (and QMGATEWAY_BASE_URL for a non-default server), then:
  account                       who the key belongs to and which services are ready
  balance                       what is left of your plan
  devices                       your gateway phones
  send <phone> <message>        queue a message (add --at="2026-12-01 08:00:00" to schedule it)
  status <id>                   where a message is now
  messages [--status=Failed]    the latest messages
  verify-webhook --secret=...   check a webhook: raw body on standard input, --header="Name: value" for each header
Add --json for machine-readable output."""


def _out(v: object, as_json: bool) -> None:
    if as_json:
        print(json.dumps(v, indent=2, ensure_ascii=False, default=str))
    elif isinstance(v, str):
        print(v)
    else:
        for k, x in v.items():  # type: ignore[union-attr]
            print(str(k).ljust(18) + (json.dumps(x) if isinstance(x, (dict, list)) else str(x)))


def _opt(args: list[str], name: str) -> str | None:
    return next((a[len(name) + 3:] for a in args if a.startswith(f"--{name}=")), None)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv.pop(0) if argv else "help"
    as_json = "--json" in argv
    args = [a for a in argv if a != "--json"]
    if cmd in ("help", "--help", "-h"):
        print(HELP); return 0
    if cmd == "verify-webhook":
        secret = _opt(args, "secret") or os.environ.get("QMGATEWAY_WEBHOOK_SECRET")
        if not secret:
            print("Give --secret=... or set QMGATEWAY_WEBHOOK_SECRET.", file=sys.stderr); return 2
        headers = {n.strip(): v.strip() for a in args if a.startswith("--header=") and ":" in a for n, v in [a[9:].split(":", 1)]}
        try:
            e = verify_webhook(sys.stdin.buffer.read(), headers, secret)
            _out({"verified": True, "event": e.type, "event_id": e.id, "message_id": e.message_id}, as_json); return 0
        except SignatureError as e:
            _out({"verified": False, "reason": e.reason}, as_json); return 3
    key = os.environ.get("QMGATEWAY_API_KEY")
    if not key:
        print("Set the QMGATEWAY_API_KEY environment variable.", file=sys.stderr); return 2
    try:
        qm = QMGateway(key, Options(base_url=os.environ["QMGATEWAY_BASE_URL"]) if os.environ.get("QMGATEWAY_BASE_URL") else None)
        if cmd == "account":
            a = qm.account.get(); sms = a.service("sms")
            _out(a.raw if as_json else {"organisation": a.organisation_name, "key": a.key_mode, "sms_ready": bool(sms and sms.ready_to_send)}, as_json)
        elif cmd == "balance":
            b = qm.account.balance()
            _out(b.raw if as_json else {"plan": b.plan, "remaining": f"{b.remaining} of {b.quota}", "level": b.level, "expires_at": b.expires_at}, as_json)
        elif cmd == "devices":
            for d in qm.devices.list(): _out(d.raw if as_json else f"#{d.id} {d.name} ({d.status}, {d.queued} queued)", as_json)
        elif cmd == "send":
            at = _opt(args, "at"); p = [a for a in args if not a.startswith("--at=")]
            if len(p) < 2:
                print('Usage: qmgateway send <phone> <message> [--at="YYYY-MM-DD HH:MM:SS"]', file=sys.stderr); return 2
            r = qm.messages.send(p[0], " ".join(p[1:]), scheduled_at=at)
            _out(r.raw if as_json else f"Queued message {r.message_id} ({r.remaining_units} units left)", as_json)
        elif cmd == "status":
            m = qm.messages.get(int(args[0]) if args else 0)
            _out(m.raw if as_json else f"#{m.id} {m.phone_number}: {m.status}" + (f" ({m.failure_reason})" if m.failure_reason else ""), as_json)
        elif cmd == "messages":
            for m in qm.messages.list(status=_opt(args, "status"), limit=20).items: _out(m.raw if as_json else f"#{m.id} {m.phone_number} {m.status}", as_json)
        else:
            print(f'Unknown command "{cmd}". Run qmgateway help.', file=sys.stderr); return 2
    except QMGatewayError as e:
        print(f"Error: {e}" + (f" [{e.code}]" if isinstance(e, ApiError) else ""), file=sys.stderr); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
