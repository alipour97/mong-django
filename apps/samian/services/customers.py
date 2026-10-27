"""
Customers and their addresses, read from Samian.

Samian is shared with Lebaza, so instead of copying every Samian customer this
reads only the people who have an account on the site (website.Customer),
matched by mobile number, the one identifier both sides have:

    retail/poscustomer          -> SamianCustomer          filter mobilephone
    accounts/contactinfo        -> SamianCustomerAddress   filter poscustomer_id

Samian has no "in" filter, so each request asks for CHUNK ids joined with
"or". Every Samian customer with the site customer's mobile is kept (a person
can have several); website.Customer.samian_customer points at the oldest.
Their purchase history is the Mong sales of services/sales.py attached to
these customers.

Read only: nothing is written to Samian.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Iterator

from django.utils import timezone

from apps.samian.client import SamianClient, get_samian_client
from apps.samian.models import (
    SamianCustomer,
    SamianCustomerAddress,
    SamianSyncLog,
)
from apps.samian.services.erp_sync import (
    _chunks,
    _dec,
    _dt,
    _int,
    _log_finish,
    _log_start,
    _money,
    _s,
)

logger = logging.getLogger(__name__)

CHUNK = 25
PAGE = 1000
BATCH = 1000

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_mobile(value: Any) -> str:
    """09xxxxxxxxx from any spelling (Persian digits, +98, missing 0); other values as digits."""
    digits = "".join(ch for ch in _s(value).translate(_PERSIAN_DIGITS) if ch.isdigit())
    if digits.startswith("0098"):
        digits = "0" + digits[4:]
    elif digits.startswith("98") and len(digits) == 12:
        digits = "0" + digits[2:]
    elif digits.startswith("9") and len(digits) == 10:
        digits = "0" + digits
    return digits


def _date(value: Any):
    dt = _dt(value)
    return dt.date() if dt else None


def _any_of(field: str, values: Iterable[Any]) -> list:
    query: list = []
    for value in values:
        if query:
            query.append("or")
        query.append([field, "=", value])
    return query


def _iter_matching(client: SamianClient, endpoint: str, key: str, field: str, values: list) -> Iterator[dict]:
    """Every record of endpoint whose field equals one of values, CHUNK values per request."""
    for chunk in _chunks(values, CHUNK):
        yield from client.iter_keyset(endpoint, key=key, take_count=PAGE, filters=_any_of(field, chunk))


def _upsert(model, instances: list, update_fields: list[str]) -> None:
    for batch in _chunks(instances, BATCH):
        model.objects.bulk_create(batch, update_conflicts=True, unique_fields=["samian_id"], update_fields=update_fields)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
CUSTOMER_FIELDS = [
    "first_name", "last_name", "display_name", "mobile", "phone", "email",
    "gender_id", "gender", "club_level_id", "club_level",
    "customer_type_id", "customer_type", "customer_status_id", "customer_status",
    "subscription_code", "customer_card_num", "national_code", "birthdate", "subscription_date",
    "wallet_balance", "club_point_score", "club_price_score", "address", "postal_code",
    "is_active", "updated_at",
]


def _customer(item: dict) -> SamianCustomer:
    return SamianCustomer(
        samian_id=_int(item.get("poscustomer_id") or item.get("id")),
        first_name=_s(item.get("name"), 150),
        last_name=_s(item.get("family"), 150),
        display_name=_s(item.get("fullname"), 255),
        mobile=normalize_mobile(item.get("mobilephone"))[:50],
        phone=_s(item.get("telphone"), 50),
        email=_s(item.get("email"), 254),
        gender_id=_int(item.get("gender_id")),
        gender=_s(item.get("__gender_id_value"), 32),
        club_level_id=_int(item.get("posclublevel_id")),
        club_level=_s(item.get("__posclublevel_id_value"), 128),
        customer_type_id=_int(item.get("customertype_id")),
        customer_type=_s(item.get("__customertype_id_value"), 128),
        customer_status_id=_int(item.get("customerstatus_id")),
        customer_status=_s(item.get("__customerstatus_id_value"), 128),
        subscription_code=_s(item.get("subscriptioncode"), 128),
        customer_card_num=_s(item.get("customercardnum"), 128),
        national_code=_s(item.get("nationalcode") or item.get("nationalid"), 32),
        birthdate=_date(item.get("birthdate")),
        subscription_date=_dt(item.get("subscriptiondate")),
        wallet_balance=_money(item.get("walletbalance")),
        club_point_score=_dec(item.get("clubpointscore")),
        club_price_score=_money(item.get("clubpricescore")),
        address=_s(item.get("address")),
        postal_code=_s(item.get("postalcode"), 32),
        is_active=bool(item.get("isactive", True)),
    )


def sync_customers(client: SamianClient, mobiles: list[str]) -> int:
    """Store the Samian customers that have one of these mobiles. Returns how many."""
    wanted = set(mobiles)
    instances = {}
    # Samian stores the number as typed; ask for both 09.. and 9.. spellings.
    variants = sorted({v for m in mobiles for v in (m, m[1:])})
    for item in _iter_matching(client, "retail/poscustomer", "poscustomer_id", "mobilephone", variants):
        c = _customer(item)
        if c.samian_id and c.mobile in wanted:
            instances[c.samian_id] = c
    _upsert(SamianCustomer, list(instances.values()), CUSTOMER_FIELDS)
    return len(instances)


def link_site_customers(site_customers) -> int:
    """Point each site customer at the oldest Samian customer with the same mobile."""
    from apps.website.models import Customer

    oldest: dict[str, int] = {}
    mobiles = {normalize_mobile(c.cellphone) for c in site_customers}
    for pk, mobile in SamianCustomer.objects.filter(mobile__in=mobiles).order_by("samian_id").values_list("pk", "mobile"):
        oldest.setdefault(mobile, pk)
    now = timezone.now()
    for c in site_customers:
        c.samian_customer_id = oldest.get(normalize_mobile(c.cellphone))
        c.samian_checked_at = now
    Customer.objects.bulk_update(site_customers, ["samian_customer", "samian_checked_at"], batch_size=BATCH)
    return sum(1 for c in site_customers if c.samian_customer_id)


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
ADDRESS_FIELDS = [
    "customer", "customer_samian_id", "title", "address", "receiver_name", "mobile", "phone",
    "postal_code", "province_id", "province", "town_id", "town", "is_default", "updated_at",
]


def sync_addresses(client: SamianClient, customer_pks: dict[int, int]) -> int:
    """Addresses of these Samian customers (samian id -> pk); addresses removed in Samian are deleted."""
    instances = []
    for item in _iter_matching(client, "accounts/contactinfo", "contactinfo_id", "poscustomer_id", list(customer_pks)):
        owner = _int(item.get("poscustomer_id"))
        instances.append(SamianCustomerAddress(
            samian_id=_int(item.get("contactinfo_id") or item.get("id")),
            customer_id=customer_pks.get(owner),
            customer_samian_id=owner,
            title=_s(item.get("contacttitle"), 255),
            address=_s(item.get("address")),
            receiver_name=_s(item.get("receiverfullname"), 255),
            mobile=normalize_mobile(item.get("mobilephone"))[:50],
            phone=_s(item.get("telphone"), 50),
            postal_code=_s(item.get("postalcode"), 32),
            province_id=_int(item.get("provinces_id")),
            province=_s(item.get("__provinces_id_value"), 128),
            town_id=_int(item.get("towns_id")),
            town=_s(item.get("__towns_id_value"), 128),
            is_default=bool(item.get("isdefault")),
        ))
    _upsert(SamianCustomerAddress, instances, ADDRESS_FIELDS)
    SamianCustomerAddress.objects.filter(customer_samian_id__in=customer_pks).exclude(
        samian_id__in=[a.samian_id for a in instances]
    ).delete()
    return len(instances)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def sync_site_customers(client: SamianClient | None = None, *, customer_ids: list[int] | None = None) -> dict[str, Any]:
    """Read the Samian customer and addresses of site customers, and attach their invoices."""
    from apps.samian.services.sales import link_customers
    from apps.website.models import Customer

    client = client or get_samian_client()
    log = _log_start(SamianSyncLog.Action.SYNC_CUSTOMERS)
    try:
        site = Customer.objects.filter(is_deleted=False)
        if customer_ids:
            site = site.filter(id__in=customer_ids)
        site = list(site)
        mobiles = sorted({normalize_mobile(c.cellphone) for c in site} - {""})

        found = sync_customers(client, mobiles)
        linked = link_site_customers(site)
        customer_pks = dict(SamianCustomer.objects.filter(mobile__in=mobiles).values_list("samian_id", "pk"))
        addresses = sync_addresses(client, customer_pks)
        invoices = link_customers()
        return _log_finish(log, total=len(site), synced=linked, details={
            "samian_customers": found, "linked": linked, "addresses": addresses, "invoices_attached": invoices,
        })
    except Exception as exc:
        logger.exception("sync_site_customers failed")
        _log_finish(log, total=0, synced=0, error=exc)
        raise
