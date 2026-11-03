"""
The scheduled syncs as one list, so the admin panel can show when each last ran and run one by hand.

Every run, from cron or from the panel, is a SyncRun row: when, how long, whether it worked and what it
changed (Persian lines the panel shows in a toast). The cron commands call run(); the panel calls start(),
which runs the job in a thread and returns at once, because a full read of the software takes longer than
a request may.

    erp       products, categories, prices, stock, coupons and gift cards from the sales software
    lebazai   approved photos and the AI copy of the products from LEBAZAI
    sales     every branch's sales for the best-seller sort, and the old site's new orders
    outbox    paid invoices to the sales software, and the payment hub's unclear payments when one is due

A job's state for the panel: "ok" when its last run worked and was on time, "late" when it has not run on
schedule (yellow), "error" when its last run failed (red). A run by hand counts like a scheduled one.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from django.db import close_old_connections
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


def _erp(log) -> list[str]:
    from apps.storefront import catalog

    from .connector import get_connector

    connector = get_connector()
    if connector.name == "samian":  # its tables come first from the API; the connector builds the site from them
        from django.core.management import call_command

        call_command("sync_samian_erp")
    r = connector.sync(log=log)
    catalog.clear_caches()
    return [
        f"قیمت {r.get('repriced', 0)} کالا تغییر کرد",
        f"موجودی {r.get('restocked', 0)} تنوع تغییر کرد",
        f"{r.get('came_on_sale', 0)} کالا به فروش آمد، {r.get('went_off_sale', 0)} کالا از فروش خارج شد",
        f"خوانده شد: {r.get('products', 0)} کالا، {r.get('variants', 0)} تنوع، "
        f"{r.get('coupons', 0)} کوپن، {r.get('gift_cards', 0)} کارت هدیه",
    ]


def _lebazai(log) -> list[str]:
    from apps.storefront import catalog

    from . import lebazai

    images = lebazai.sync_images(log)
    profiles = lebazai.sync_profiles(log)
    catalog.clear_caches()
    lines = [f"{images['added']} عکس تازه، {images['moved']} جابه‌جا، {images['removed']} حذف",
             f"{images['built']} عکس دانلود و ساخته شد"]
    if images["failed"]:
        lines.append(f"{images['failed']} عکس دانلود نشد")
    lines.append(f"اطلاعات {profiles['saved']} کالا به‌روز شد، {profiles['missing']} کالا در LEBAZAI اطلاعات ندارد")
    return lines


def _sales(log) -> list[str]:
    from io import StringIO

    from apps.storefront import catalog
    from apps.website.models import Product

    from .connector import get_connector

    connector = get_connector()
    lines = []
    sold = connector.sold()
    if sold is not None:
        changed = [Product(id=pid, sold=sold.get(pid, 0.0))
                   for pid, held in Product.objects.values_list("id", "sold") if held != sold.get(pid, 0.0)]
        Product.objects.bulk_update(changed, ["sold"], batch_size=2000)
        catalog.clear_caches()
        lines.append(f"فروش {len(changed)} کالا به‌روز شد ({sum(1 for n in sold.values() if n > 0)} کالا فروش دارند)")
        log(f"sales: {len(changed)} products changed")
    if connector.name == "dadehfa":  # the old site still sells; its new orders join the panel's numbers
        from .management.commands.import_dadehfa_orders import Command as ImportOrders

        importer = ImportOrders(stdout=StringIO())
        importer.handle(new=True)
        lines.append(f"{importer.new_invoices} سفارش تازه از سایت قدیم")
    return lines


def _outbox(log) -> list[str]:
    from apps.payhub import service as payhub

    from . import outbox

    looked = payhub.reconcile_if_due()
    r = outbox.run(log)
    lines = [f"{r['sent']} فاکتور به نرم‌افزار فروش رفت"]
    if r["failed"]:
        lines.append(f"{r['failed']} فاکتور نرفت (علت در صفحهٔ فاکتور)")
    if r["taken"]:
        lines.append(f"{r['taken']} فاکتور را نرم‌افزار فروش برداشت")
    if looked:
        lines.append(f"{looked} پرداخت نامعلوم بررسی شد")
    return lines


JOBS = {job.key: job for job in (
    Job("erp", "کالا، قیمت، موجودی، کوپن و کارت هدیه", "in", "هر ۵ دقیقه", timedelta(minutes=5), _erp),
    Job("lebazai", "عکس و اطلاعات محصولات از LEBAZAI", "in", "هر شب", timedelta(days=1), _lebazai),
    Job("sales", "داده‌های فروش", "in", "هر ساعت", timedelta(hours=1), _sales),
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


def last_finished(key: str) -> SyncRun | None:
    return SyncRun.objects.filter(job=key, ok__isnull=False).order_by("-id").first()


def state(job: Job, finished: SyncRun | None) -> str:
    if finished is not None and not finished.ok:
        return "error"
    if finished is None or finished.started_at < timezone.now() - 2 * job.every - timedelta(minutes=5):
        return "late"
    return "ok"


def worst(states) -> str:
    states = set(states)
    return "error" if "error" in states else "late" if "late" in states else "ok"
