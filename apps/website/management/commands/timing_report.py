"""Management command: what REQUEST_TIMING measured, the slowest paths first."""
import json
import re
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

IDS = re.compile(r"/\d+(?=/|$)")


class Command(BaseCommand):
    help = "گزارش زمان درخواست‌ها و کوئری‌ها"

    def add_arguments(self, parser):
        parser.add_argument("--top", type=int, default=20)
        parser.add_argument("--clear", action="store_true", help="پاک کردن فایل بعد از گزارش")

    def handle(self, *args, **opts):
        source = Path(settings.REQUEST_TIMING_FILE)
        if not source.exists():
            raise CommandError(f"nothing measured yet: {source}")
        paths = defaultdict(list)
        for line in source.read_text(encoding="utf8").splitlines():
            row = json.loads(line)
            paths[f"{row['method']} {IDS.sub('/N', row['path'])}"].append(row)
        ranked = sorted(paths.items(), key=lambda item: -sum(r["total"] for r in item[1]))[:opts["top"]]
        self.stdout.write(f"{'n':>5} {'avg ms':>8} {'max ms':>8} {'conn':>6} {'db ms':>7} {'queries':>7} {'repeat':>6}  path")
        for path, rows in ranked:
            n = len(rows)
            average = lambda key: sum(r[key] for r in rows) / n
            self.stdout.write(f"{n:>5} {average('total'):>8.0f} {max(r['total'] for r in rows):>8.0f} {average('connect'):>6.0f} "
                              f"{average('db'):>7.0f} {average('queries'):>7.1f} {average('repeated'):>6.1f}  {path}")
        slow = sorted((q for rows in paths.values() for r in rows for q in r["slow"]), key=lambda q: -q["ms"])[:5]
        self.stdout.write("\nslowest statements:")
        for query in slow:
            self.stdout.write(f"{query['ms']:>8.1f} ms  {query['sql'][:160]}")
        if opts["clear"]:
            source.unlink()
