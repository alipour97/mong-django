"""
The scheduled syncs as one list, so the admin panel can show when each last ran and run one by hand.

Every run, from cron or from the panel, is a SyncRun row: when, how long, whether it worked and what it
changed (Persian lines the panel shows in a toast). The cron commands call run(); the panel calls start(),
which runs the job in a thread and returns at once, because a full read of the software takes longer than
a request may.

    erp       products, categories, prices, stock, coupons and gift cards from the sales software
    images    approved photos from LEBAZAI
    profiles  AI copy of the products from LEBAZAI
    outbox    paid invoices to the sales software
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from django.db import close_old_connections
from django.db.models import Sum
from django.utils import timezone

from .models import SyncRun

logger = logging.getLogger(__name__)

KEEP = timedelta(days=7)  # outbox alone runs 1440 times a day
STUCK = timedelta(minutes=30)  # a run not finished after this has died with its process


@dataclass(frozen=True)
class Job:
    key: str
    title: str
    direction: str  # "in": into the site, "out": from the site
    period: str  # how often cron runs it, for the panel
    every: timedelta  # a last automatic run older than twice this is late
    work: Callable[[Callable[[str], None]], list[str]]  # returns what changed, in Persian


def _snapshot() -> tuple[dict, dict]:
    from apps.website.models import Product, VariantStock

    products = {pid: (on_sale, price, sale_price)
                for pid, on_sale, price, sale_price in Product.objects.values_list("id", "on_sale", "price", "sale_price")}
    stock = dict(VariantStock.objects.values("variant_id").annotate(q=Sum("qty")).values_list("variant_id", "q"))
    return products, stock


def _erp(log) -> list[str]:
    from apps.storefront import catalog

    from .connector import get_connector

    connector = get_connector()
    if connector.name == "samian":  # its tables come first from the API; the connector builds the site from them
        from django.core.management import call_command

        call_command("sync_samian_erp")
    products, stock = _snapshot()
    read = connector.sync(log=log)
    catalog.clear_caches()
    products_after, stock_after = _snapshot()

    def selling(p):
        return p is not None and p[0]

    added = sum(1 for pid, p in products_after.items() if selling(p) and not selling(products.get(pid)))
    removed = sum(1 for pid, p in products.items() if selling(p) and not selling(products_after.get(pid)))
    priced = sum(1 for pid, p in products_after.items()
                 if selling(p) and selling(products.get(pid)) and p[1:] != products[pid][1:])
    stocked = sum(1 for vid in stock.keys() | stock_after.keys() if (stock.get(vid) or 0) != (stock_after.get(vid) or 0))
    return [
        f"قیمت {priced} کالا تغییر کرد",
        f"موجودی {stocked} تنوع تغییر کرد",
        f"{added} کالا به فروش آمد، {removed} کالا از فروش خارج شد",
        f"خوانده شد: {read.get('products', 0)} کالا، {read.get('variants', 0)} تنوع، "
        f"{read.get('coupons', 0)} کوپن، {read.get('gift_cards', 0)} کارت هدیه",
    ]


def _images(log) -> list[str]:
    from apps.storefront import catalog

    from . import lebazai

    r = lebazai.sync_images(log)
    catalog.clear_caches()
    lines = [f"{r['added']} عکس تازه، {r['moved']} جابه‌جا، {r['removed']} حذف", f"{r['built']} عکس دانلود و ساخته شد"]
    if r["failed"]:
        lines.append(f"{r['failed']} عکس دانلود نشد")
    return lines


def _profiles(log) -> list[str]:
    from apps.storefront import catalog

    from . import lebazai

    r = lebazai.sync_profiles(log)
    catalog.clear_caches()
    return [f"اطلاعات {r['saved']} کالا ذخیره شد", f"{r['missing']} کالا در LEBAZAI اطلاعات ندارد"]


def _outbox(log) -> list[str]:
    from . import outbox

    r = outbox.run(log)
    lines = [f"{r['sent']} فاکتور به نرم‌افزار فروش رفت"]
    if r["failed"]:
        lines.append(f"{r['failed']} فاکتور نرفت (علت در صفحهٔ فاکتور)")
    if r["taken"]:
        lines.append(f"{r['taken']} فاکتور را نرم‌افزار فروش برداشت")
    return lines


JOBS = {job.key: job for job in (
    Job("erp", "کالا، قیمت، موجودی، کوپن و کارت هدیه", "in", "هر ۵ دقیقه", timedelta(minutes=5), _erp),
    Job("images", "عکس محصولات از LEBAZAI", "in", "هر شب", timedelta(days=1), _images),
    Job("profiles", "اطلاعات و متن محصولات از LEBAZAI", "in", "هر شب", timedelta(days=1), _profiles),
    Job("outbox", "ارسال فاکتورهای پرداخت‌شده", "out", "هر دقیقه", timedelta(minutes=1), _outbox),
)}


def _work(run: SyncRun, log=None) -> SyncRun:
    job = JOBS[run.job]

    def note(text: str) -> None:
        logger.info("%s: %s", run.job, text)
        if log:
            log(text)

    began = time.monotonic()
    try:
        run.changes = job.work(note)
        run.ok = True
    except Exception as exc:
        logger.exception("sync %s failed", run.job)
        run.ok, run.error = False, str(exc)[:4000]
    run.finished_at = timezone.now()
    logger.info("sync %s (%s) %s in %.1fs: %s", run.job, run.trigger, "ok" if run.ok else "failed",
                time.monotonic() - began, "; ".join(run.changes) or run.error)
    run.save()
    SyncRun.objects.filter(job=run.job, started_at__lt=timezone.now() - KEEP).delete()
    return run


def run(key: str, *, trigger: str = SyncRun.Trigger.AUTO, log=None, by: str = "") -> SyncRun:
    """Runs a job here and now (cron). Never raises: a failure is in the row it returns."""
    return _work(SyncRun.objects.create(job=key, trigger=trigger, by=by), log)


def running(key: str) -> SyncRun | None:
    return (SyncRun.objects.filter(job=key, ok__isnull=True, started_at__gte=timezone.now() - STUCK)
            .order_by("-id").first())


def start(key: str, *, by: str = "", background: bool = True) -> SyncRun:
    """Starts a job by hand; one already on its way is returned instead of a second one."""
    current = running(key)
    if current:
        return current
    row = SyncRun.objects.create(job=key, trigger=SyncRun.Trigger.MANUAL, by=by)
    if not background:
        return _work(row)

    def go():
        close_old_connections()
        try:
            _work(row)
        finally:
            close_old_connections()

    threading.Thread(target=go, daemon=True).start()
    return row


def seconds(run: SyncRun) -> float | None:
    return round((run.finished_at - run.started_at).total_seconds(), 1) if run.finished_at else None


def last(key: str, trigger: str | None = None) -> SyncRun | None:
    rows = SyncRun.objects.filter(job=key)
    if trigger:
        rows = rows.filter(trigger=trigger)
    return rows.order_by("-id").first()
