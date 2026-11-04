"""
Checks that the addresses Google knows still lead somewhere: every page in a
Search Console export is requested on a running site, and redirects are
followed one hop at a time.

  python manage.py check_redirects mong.ir-Performance-on-Search.xlsx
  python manage.py check_redirects pages.csv --base https://new.mong.ir

The export is Search Console > Performance > Pages > Export (the .xlsx, or the
Pages.csv from the zip). Only the path is taken from each address, so a test
domain answers for mong.ir; addresses on other hosts (erp.mong.ir) are skipped.
With --base on mong.ir itself, http:// and www. are checked too.

A good address answers 200, or one permanent redirect to a page that answers
200. Reported: addresses that end in 4xx/5xx (most clicks first), chains of
more than one redirect, and temporary redirects. Exits 1 when a broken address
had at least --min-clicks clicks (default 1), so it can gate the switch to
mong.ir; pages that are gone on purpose (an old survey) can be let through.
"""
from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

SITE_HOSTS = {"mong.ir", "www.mong.ir"}
MAX_HOPS = 5
PERMANENT = {301, 308}


def read_export(path: Path) -> list[tuple[str, int]]:
    """(address, clicks) rows of a Search Console Pages export."""
    if path.suffix.lower() == ".xlsx":
        import warnings

        import openpyxl

        with warnings.catch_warnings():  # Search Console's files have no default style
            warnings.simplefilter("ignore")
            book = openpyxl.load_workbook(path, read_only=True)
        sheet = book["Pages"] if "Pages" in book.sheetnames else book.worksheets[0]
        rows = list(sheet.iter_rows(values_only=True))
    else:
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
    out = []
    for row in rows[1:]:  # first row: "Top pages, Clicks, …"
        if not row or not row[0] or not str(row[0]).startswith("http"):
            continue
        try:
            clicks = int(float(row[1] or 0))
        except (IndexError, ValueError):
            clicks = 0
        out.append((str(row[0]), clicks))
    return out


def follow(session: requests.Session, url: str) -> list[tuple[int, str]]:
    """[(status, url)] for each hop, the last one the final answer."""
    hops = []
    for _ in range(MAX_HOPS + 1):
        try:
            r = session.get(url, allow_redirects=False, timeout=30)
        except requests.RequestException as e:
            hops.append((0, f"{url} ({type(e).__name__})"))
            return hops
        hops.append((r.status_code, url))
        location = r.headers.get("Location")
        if r.status_code not in (301, 302, 303, 307, 308) or not location:
            return hops
        url = urljoin(url, location)
    return hops


def path_of(address: str) -> str:
    """The address's path and query, encoded once however Search Console wrote it."""
    parts = urlsplit(address)
    path = quote(unquote(parts.path), safe="/") or "/"
    return path + (f"?{parts.query}" if parts.query else "")


class Command(BaseCommand):
    help = "آدرس‌های خروجی سرچ کنسول را روی سایت می‌زند و ۴۰۴، زنجیره‌ی ریدایرکت و ریدایرکت موقت را گزارش می‌کند."

    def add_arguments(self, parser):
        parser.add_argument("export", help="خروجی Pages سرچ کنسول (.xlsx یا .csv)")
        parser.add_argument("--base", default=settings.SITE_URL, help="سایتی که آزمایش می‌شود (پیش‌فرض SITE_URL)")
        parser.add_argument("--workers", type=int, default=6)
        parser.add_argument("--min-clicks", type=int, default=1, help="۴۰۴ با کمتر از این تعداد کلیک خطا حساب نمی‌شود")

    def handle(self, *args, export, base, workers, min_clicks, **options):
        path = Path(export)
        if not path.exists():
            raise CommandError(f"{path} not found")
        base = base.rstrip("/")
        rows = read_export(path)

        clicks: dict[str, int] = {}
        skipped = []
        for address, n in rows:
            if (urlsplit(address).hostname or "") not in SITE_HOSTS:
                skipped.append(address)
                continue
            p = path_of(address)
            clicks[p] = clicks.get(p, 0) + n

        session = requests.Session()
        session.headers["User-Agent"] = "mong-check-redirects"
        urls = {p: base + p for p in clicks}
        if urlsplit(base).hostname == "mong.ir":  # the live domain: its other spellings too
            for variant in ("http://mong.ir", "http://www.mong.ir", "https://www.mong.ir"):
                urls[f"{variant}/"] = f"{variant}/"
                clicks.setdefault(f"{variant}/", 0)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = dict(zip(urls, pool.map(lambda u: follow(session, u), urls.values())))

        broken, chains, temporary, ok = [], [], [], 0
        for p, hops in results.items():
            final_status = hops[-1][0]
            redirects = [s for s, _ in hops[:-1]]
            if final_status != 200:
                broken.append((clicks[p], p, hops))
            elif len(redirects) > 1:
                chains.append((clicks[p], p, hops))
            elif redirects and redirects[0] not in PERMANENT:
                temporary.append((clicks[p], p, hops))
            else:
                ok += 1

        def show(title, items):
            if not items:
                return
            self.stdout.write(self.style.WARNING(f"\n{title} ({len(items)})"))
            for n, p, hops in sorted(items, key=lambda x: -x[0]):
                trail = " -> ".join(f"{s} {unquote(u.replace(base, ''))}" for s, u in hops)
                self.stdout.write(f"  {n:>6} clicks  {trail}")

        show("Broken (not 200 at the end)", broken)
        show("More than one redirect", chains)
        show("Temporary redirect (302/307)", temporary)
        if skipped:
            self.stdout.write(f"\nSkipped {len(skipped)} on other hosts: " + ", ".join(sorted(set(skipped))[:5]))

        lost = sum(n for n, _, _ in broken)
        self.stdout.write(
            f"\n{len(results)} addresses on {base}: {ok} fine, {len(broken)} broken "
            f"({lost} clicks), {len(chains)} chains, {len(temporary)} temporary."
        )
        if any(n >= min_clicks for n, _, _ in broken):
            raise SystemExit(1)
