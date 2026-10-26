"""
Management command: compare storefront responses with the legacy API.

Every file in contract_fixtures/ holds a request and the real response
api.mong.ir / adminapi.mong.ir gave for it. The same request is replayed
against this Django app and the response *structure* (keys and value types)
is compared. Values are not compared since data changes over time.

    python manage.py check_contract            # all fixtures
    python manage.py check_contract product    # names containing "product"
"""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.test import Client

FIXTURES = Path(__file__).resolve().parents[2] / "contract_fixtures"
NUMERIC = {"int", "float"}


def shape(value, path="$", depth=0, out=None) -> dict[str, str]:
    out = {} if out is None else out
    if isinstance(value, dict):
        out[path] = "object"
        if depth < 6:
            for k, v in value.items():
                shape(v, f"{path}.{k}", depth + 1, out)
    elif isinstance(value, list):
        out[path] = "array"
        if value and depth < 6:
            shape(value[0], f"{path}[]", depth + 1, out)
    elif value is None:
        out[path] = "null"
    else:
        out[path] = "number" if type(value).__name__ in NUMERIC else type(value).__name__
    return out


class Command(BaseCommand):
    help = "مقایسه ساختار پاسخ‌های API با پاسخ‌های واقعی سایت قبلی"

    def add_arguments(self, parser):
        parser.add_argument("filter", nargs="?", default="")
        parser.add_argument("--verbose", action="store_true", help="نمایش کلیدهای اضافه هم")

    def handle(self, *args, **opts):
        client = Client(HTTP_COMPANYID="1")
        failures = 0
        for path in sorted(FIXTURES.glob("*.json")):
            if opts["filter"] not in path.stem:
                continue
            fx = json.loads(path.read_text())
            req = fx["request"]
            url = "/api/v1/" + req["path"]
            if req["method"] == "GET":
                resp = client.get(url)
            else:
                resp = client.post(url, data=json.dumps(req["body"] or {}), content_type="application/json")
            try:
                got = resp.json()
            except ValueError:
                got = resp.content[:80].decode(errors="replace")

            problems = []
            if resp.status_code != fx["status"]:
                problems.append(f"HTTP {resp.status_code} (expected {fx['status']})")
            if isinstance(fx["response"], dict) and isinstance(got, dict):
                body_live, body_got = fx["response"].get("statusCode"), got.get("statusCode")
                if body_live is not None and body_live != body_got:
                    problems.append(f"statusCode {body_got} (expected {body_live})")
            want, have = shape(fx["response"]), shape(got)
            missing = [k for k in want if k not in have]
            typed = [
                f"{k}: {have[k]} (expected {want[k]})"
                for k in want if k in have and want[k] != have[k] and "null" not in (want[k], have[k])
            ]
            extra = [k for k in have if k not in want]
            if missing:
                problems.append("missing " + ", ".join(missing[:10]) + (" ..." if len(missing) > 10 else ""))
            if typed:
                problems.append("type " + "; ".join(typed[:6]))
            if opts["verbose"] and extra:
                problems.append("extra " + ", ".join(extra[:10]))

            if problems:
                failures += 1
                self.stdout.write(self.style.ERROR(f"✗ {path.stem}"))
                for p in problems:
                    self.stdout.write(f"    {p}")
            else:
                self.stdout.write(self.style.SUCCESS(f"✓ {path.stem}"))
        self.stdout.write(f"\n{failures} fixture(s) differ")
