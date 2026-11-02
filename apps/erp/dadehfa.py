"""
The Dadehfa connector. Copies the shop's catalog, prices, stock, coupons and gift cards out of
DadehfaOnlineShop (SELECT only, apps/legacy/db.py) on the sync's schedule, and writes paid invoices there
(apps/erp/dadehfa_write.py). The site itself never reads it. The .NET service's jobs carry those invoices
to the ERP and keep that database fresh, so the service must stay running while the site is on this connector.

The rules below were worked out against the shop's own API, row by row:

- on sale: active, saleable and priced. Which of those the site shows is the site's setting (categories,
  only_has_media_products).
- stock: all warehouses together (SiteSetting.min_qty is kept back by the storefront)
- price after discount: rounded to 10,000 rials
"""
from __future__ import annotations

import re
from decimal import Decimal

from django.utils import timezone

from apps.legacy.db import fetch_all
from apps.storefront.catalog import norm
from apps.website import slugs
from apps.website.models import Invoice

from . import dadehfa_write, store, vouchers
from .connector import Connector, Coupon, GiftCard, Held, Log, Refused
from .models import ErpCoupon, ErpGiftCard

PRICE_STEP = 10_000

ON_SALE = """
    FROM Products p
    WHERE p.IsDeleted = 0 AND p.IsActive = 1 AND p.IsSaleable = 1 AND p.Price > 0
"""


# What the panel lists: a general coupon stands for its customers' copies, and counts as used once one of them is.
LISTED_COUPONS = """
    WITH taken AS (SELECT DISTINCT Serial FROM Coupons WHERE CustomerId IS NOT NULL AND IsUsed = 1 AND IsDeleted = 0),
    general AS (SELECT DISTINCT Serial FROM Coupons WHERE CustomerId IS NULL AND IsDeleted = 0),
    listed AS (
        SELECT c.Id, c.CustomerId, c.Serial, c.Reduction, c.ExpiredDate, c.UsedDate, c.MinPrice, c.MaxPrice, c.IsActive,
               c.BankPortalEndTime, c.Created, u.FirstName, u.LastName,
               CASE WHEN c.IsUsed = 1 OR (c.CustomerId IS NULL AND t.Serial IS NOT NULL) THEN 1 ELSE 0 END AS IsUsed
        FROM Coupons c LEFT JOIN Customers u ON u.Id = c.CustomerId LEFT JOIN taken t ON t.Serial = c.Serial
        WHERE c.IsDeleted = 0 AND (c.CustomerId IS NULL OR c.Serial NOT IN (SELECT Serial FROM general)))
"""


def _now():
    return timezone.localtime().replace(tzinfo=None)


def _like(search: str) -> str:
    """The software's names are spelled with Arabic ي and ك, the panel's keyboard types Persian ones."""
    return "%" + re.sub("[یي]", "[یي]", re.sub("[کك]", "[کك]", search)) + "%"


def _held(row: dict):
    """The old site's own hold: it switches the voucher off until the time written beside it."""
    until = row["BankPortalEndTime"]
    return until if until and not row["IsActive"] and until > timezone.now() else None


def after_discount(price: float, reduction: float) -> int:
    return int(round(price * (1 - reduction / 100) / PRICE_STEP)) * PRICE_STEP


def _moment(value):
    """SQL Server's empty dates are 0001-01-01 and 9999-12-31; naive values are Tehran time."""
    if value is None or value.year <= 1 or value.year >= 9999:
        return None
    return timezone.make_aware(value) if timezone.is_naive(value) else value


def _text(value) -> str:
    return str(value or "").strip()


def _brands() -> list[dict]:
    return [{"id": r["Id"], "title": _text(r["Title"])} for r in fetch_all("SELECT Id, Title FROM Brands WHERE IsDeleted = 0")]


def _categories() -> list[dict]:
    """What the shop calls them and how they nest. Whether one is on the site, its slug and its copy are the site's."""
    rows = fetch_all("SELECT Id, ParentId, Title, Slug, HasManualSlug, GroupLevel, Created FROM Categories1 WHERE IsDeleted = 0")
    ids = {r["Id"] for r in rows}
    return [{
        "id": r["Id"], "title": _text(r["Title"]), "parent_id": r["ParentId"] if r["ParentId"] in ids else None, "group_level": r["GroupLevel"],
        "new": {"slug": _text(r["Slug"]), "slug_key": slugs.slug_key(_text(r["Slug"])), "has_manual_slug": bool(r["HasManualSlug"]),
                "is_online_active": False, "created": _moment(r["Created"])},
    } for r in rows]


def _products(brand_ids: set[int], category_ids: set[int]) -> list[dict]:
    rows = fetch_all(f"""
        SELECT p.Id, p.Title, p.Slug, p.HasManualSlug, p.CategoryId, p.BrandId, p.Barcode, p.Price, p.Reduction, p.VAT, p.SalesCount, p.Created
        {ON_SALE}""")
    products = []
    for p in rows:
        price, reduction = float(p["Price"]), float(p["Reduction"] or 0)
        slug = _text(p["Slug"])
        products.append({
            "id": p["Id"], "erp_id": p["Id"], "on_sale": True, "is_active": True, "is_saleable": True, "title": _text(p["Title"]),
            "barcode": _text(p["Barcode"])[:64], "category_id": p["CategoryId"] if p["CategoryId"] in category_ids else None,
            "brand_id": p["BrandId"] if p["BrandId"] in brand_ids else None, "price": Decimal(int(price)),
            "reduction": Decimal(str(reduction)).quantize(Decimal("0.001")), "sale_price": after_discount(price, reduction),
            "vat": Decimal(str(p["VAT"] or 0)).quantize(Decimal("0.001")), "sold": float(p["SalesCount"] or 0),
            "new": {"slug": slug, "slug_key": slugs.slug_key(slug), "has_manual_slug": bool(p["HasManualSlug"]), "created": _moment(p["Created"])},
        })
    return products


def _variants() -> list[store.VariantRow]:
    values = {r["Id"]: r for r in fetch_all("SELECT Id, Name, Value, DisplayPriority FROM FeatureValues")}
    latest: dict[int, dict] = {}
    for row in fetch_all(f"""
            SELECT v.ProductId AS pid, v.Id AS vid, f.Id AS ref, v.Barcode AS barcode,
                   d.ParentFeatureValueId AS color, d.ChildFeatureValueId AS size
            FROM ProductVariants v
            JOIN VariantFeatureValues f ON f.ProductVariantId = v.Id AND f.IsDeleted = 0
            JOIN FeatureValueDependencies d ON d.Id = f.FeatureValueDependencyId AND d.IsDeleted = 0
            WHERE v.IsDeleted = 0 AND v.ProductId IN (SELECT p.Id {ON_SALE}) ORDER BY f.Id"""):
        latest[row["vid"]] = row  # a variant's newest link is the one invoices use
    rows = []
    for v in latest.values():
        color, size = values.get(v["color"]), values.get(v["size"])
        rows.append(store.VariantRow(
            id=v["vid"], product_id=v["pid"], erp_ref=v["ref"], barcode=_text(v["barcode"]),
            color_id=color["Id"] if color else None, color_name=(color["Name"] or "") if color else "",
            color_value=(color["Value"] or "") if color else "", color_priority=(color["DisplayPriority"] or 0) if color else 0,
            color_family=(color["Name"] or "") if color else "",
            size_id=size["Id"] if size else None, size_name=(size["Name"] or "") if size else "",
            size_value=(size["Value"] or "") if size else "", size_priority=(size["DisplayPriority"] or 0) if size else 0,
        ))
    return rows


def _stock(variant_ids: set[int]) -> list[store.StockRow]:
    return [store.StockRow(r["vid"], r["warehouse"], r["title"] or "", r["qty"]) for r in fetch_all(f"""
        SELECT w.ProductVariantId AS vid, w.WarehouseId AS warehouse, h.WarehouseTitle AS title, SUM(w.Qty) AS qty
        FROM VariantWarehouses w
        JOIN ProductVariants v ON v.Id = w.ProductVariantId
        LEFT JOIN Warehouses h ON h.Id = w.WarehouseId
        WHERE w.IsDeleted = 0 AND v.IsDeleted = 0 AND v.ProductId IN (SELECT p.Id {ON_SALE})
        GROUP BY w.ProductVariantId, w.WarehouseId, h.WarehouseTitle
        HAVING SUM(w.Qty) > 0""") if r["vid"] in variant_ids]


def _coupons() -> list[ErpCoupon]:
    rows = fetch_all("""
        SELECT c.Id, c.CustomerId, c.Serial, c.Reduction, c.ExpiredDate, c.IsUsed, c.UsedDate, c.MinPrice, c.MaxPrice, c.IsActive,
               c.BankPortalEndTime, c.Created, u.FirstName, u.LastName
        FROM Coupons c LEFT JOIN Customers u ON u.Id = c.CustomerId
        WHERE c.IsDeleted = 0""")
    general = {r["Serial"] for r in rows if r["CustomerId"] is None}
    taken = {r["Serial"] for r in rows if r["CustomerId"] is not None and r["IsUsed"]}
    return [ErpCoupon(
        id=r["Id"], customer_erp_id=r["CustomerId"], serial=r["Serial"], reduction=r["Reduction"] or 0, min_price=r["MinPrice"] or 0,
        max_price=r["MaxPrice"], expires=_moment(r["ExpiredDate"]), used_at=_moment(r["UsedDate"]), is_active=bool(r["IsActive"]),
        is_used=bool(r["IsUsed"] or (r["CustomerId"] is None and r["Serial"] in taken)), held_until=_moment(r["BankPortalEndTime"]),
        created=_moment(r["Created"]), first_name=_text(r["FirstName"]), last_name=_text(r["LastName"]),
        # A general coupon stands for its customers' copies in the panel, and counts as used once one of them is.
        listed=r["CustomerId"] is None or r["Serial"] not in general,
        search_text=norm(f"{r['Serial']} {r['FirstName'] or ''} {r['LastName'] or ''}"),
    ) for r in rows]


def _gift_cards() -> list[ErpGiftCard]:
    rows = fetch_all("""
        SELECT c.Id, c.GCNum, c.StartDate, c.ExpDate, c.GCBalance, c.IsActive, c.CustomerId, c.UseDepCode, c.MinFactorPrice, c.GiftGroupMapId,
               c.CustomerMapId, c.UseCompelete, c.BankPortalEndTime, c.Created, ISNULL(u.CellPhone, c.CustomerMobile) AS Mobile, u.FirstName, u.LastName,
               (SELECT COUNT(*) FROM Invoices i WHERE i.GiftCardId = c.Id AND i.InvoiceType = 3 AND i.IsDeleted = 0) AS InvoiceCount
        FROM GiftCards c LEFT JOIN Customers u ON u.Id = c.CustomerId
        WHERE c.IsDeleted = 0""")
    return [ErpGiftCard(
        id=r["Id"], number=r["GCNum"], customer_erp_id=r["CustomerId"], mobile=_text(r["Mobile"]), balance=r["GCBalance"] or 0,
        min_price=r["MinFactorPrice"] or 0, starts=_moment(r["StartDate"]), expires=_moment(r["ExpDate"]), is_active=bool(r["IsActive"]),
        use_whole=bool(r["UseCompelete"]), use_dep_code=bool(r["UseDepCode"]), held_until=_moment(r["BankPortalEndTime"]),
        created=_moment(r["Created"]), gift_group_map_id=_text(r["GiftGroupMapId"]), customer_map_id=_text(r["CustomerMapId"]),
        first_name=_text(r["FirstName"]), last_name=_text(r["LastName"]), invoice_count=r["InvoiceCount"] or 0,
        search_text=norm(f"{r['GCNum']} {r['CustomerId'] or ''} {r['FirstName'] or ''} {r['LastName'] or ''} {r['Mobile'] or ''}"),
    ) for r in rows]


def read() -> store.Read:
    out = store.Read(brands=_brands(), categories=_categories())
    out.products = _products({b["id"] for b in out.brands}, {c["id"] for c in out.categories})
    on_sale = {p["id"] for p in out.products}
    out.variants = [v for v in _variants() if v.product_id in on_sale]
    out.stock = _stock({v.id for v in out.variants})
    out.coupons, out.gift_cards = _coupons(), _gift_cards()
    return out


class DadehfaConnector(Connector):
    name = "dadehfa"
    all_warehouses = True
    holds_stock = True

    def sync(self, *, force: bool = False, log: Log) -> dict:
        result = store.apply(read(), force=force)
        log(f"erp: {result}")
        return result

    def barcodes(self) -> list[tuple[str, int, int]]:
        return [(r["barcode"].strip(), r["pid"], r["color"]) for r in fetch_all(f"""
            SELECT DISTINCT v.Barcode AS barcode, v.ProductId AS pid, d.ParentFeatureValueId AS color
            FROM ProductVariants v
            JOIN VariantFeatureValues f ON f.ProductVariantId = v.Id AND f.IsDeleted = 0
            JOIN FeatureValueDependencies d ON d.Id = f.FeatureValueDependencyId AND d.IsDeleted = 0
            WHERE v.IsDeleted = 0 AND v.Barcode IS NOT NULL AND v.ProductId IN (SELECT p.Id {ON_SALE})""")]

    def push(self, invoice) -> None:
        dadehfa_write.push(invoice)

    def follow(self, log: Log) -> None:
        sent = dict(Invoice.objects.filter(erp_invoice_id__isnull=False, erp_taken_at__isnull=True).values_list("erp_invoice_id", "pk"))
        if not sent:
            return
        ids = ",".join(str(int(i)) for i in sent)
        taken = [r["Id"] for r in fetch_all(f"SELECT Id FROM Invoices WHERE MapId IS NOT NULL AND Id IN ({ids})")]
        Invoice.objects.filter(pk__in=[sent[i] for i in taken]).update(erp_taken_at=timezone.now())
        log(f"{len(taken)} of {len(sent)} sent invoices are in the ERP")

    def coupon(self, serial: str, customer, invoice_id: int | None = None) -> Coupon:
        """The customer's own coupon, else a general one (the customer's copy is made when it is used)."""
        columns = "Id, Serial, Reduction, MinPrice, MaxPrice, ExpiredDate, IsUsed, IsActive, BankPortalEndTime"
        own = fetch_all(f"SELECT TOP 1 {columns} FROM Coupons WHERE Serial = :s AND CustomerId = :c AND IsDeleted = 0 ORDER BY IsUsed",
                        {"s": serial, "c": customer.erp_customer_id or customer.id})
        general = [] if own else fetch_all(
            f"SELECT TOP 1 {columns} FROM Coupons WHERE Serial = :s AND CustomerId IS NULL AND IsDeleted = 0 AND IsActive = 1",
            {"s": serial})
        row = (own or general or [None])[0]
        if row is None:
            raise Refused("کوپن وجود ندارد.")
        if (own and row["IsUsed"]) or vouchers.coupon_taken(serial, customer):
            raise Refused("کوپن استفاده شده است.")
        if row["ExpiredDate"] and row["ExpiredDate"] < _now():
            raise Refused("مهلت استفاده از این کوپن تمام شده است.")
        coupon = Coupon(id=row["Id"] if own else None, serial=row["Serial"], reduction=row["Reduction"] or Decimal(0),
                        min_price=row["MinPrice"] or Decimal(0), max_price=row["MaxPrice"], expires=row["ExpiredDate"])
        until = _held(row) or vouchers.held_until(invoice_id, coupon_serial=serial, customer=customer)
        if until:
            raise Held("این کوپن در حالت تعلیق قرار دارد.", until, coupon)
        if not row["IsActive"] and not row["BankPortalEndTime"]:
            raise Refused("کوپن غیر فعال است.")
        return coupon

    def _gift_rows(self, customer, where: str = "", **params) -> list[dict]:
        return fetch_all(f"""
            SELECT Id, GCNum, StartDate, ExpDate, GCBalance, IsActive, CustomerId, UseDepCode, MinFactorPrice, UseCompelete, BankPortalEndTime
            FROM GiftCards WHERE IsDeleted = 0 AND (CustomerId = :c OR CustomerMobile = :m) {where}
            ORDER BY Id DESC""", {"c": customer.erp_customer_id or customer.id, "m": customer.cellphone, **params})

    def _balance(self, row: dict) -> Decimal:
        spent = vouchers.spent_on_card(row["Id"])
        return Decimal(0) if spent and row["UseCompelete"] else max(row["GCBalance"] - spent, Decimal(0))

    def gift_cards(self, customer) -> list[dict]:
        """What the customer can spend now, as the old site listed it."""
        rows = self._gift_rows(customer, """AND IsActive = 1 AND GCBalance > 0 AND CAST(StartDate AS date) <= CAST(:now AS date)
                                            AND (ExpDate IS NULL OR CAST(ExpDate AS date) >= CAST(:now AS date))""", now=_now())
        cards = []
        for row in rows:
            until = _held(row) or vouchers.held_until(gift_card_id=row["Id"])
            cards.append({**row, "GCBalance": self._balance(row), "Left": vouchers.left(until) if until else None})
        return [c for c in cards if c["GCBalance"] > 0]

    def gift_card(self, number: str, customer, invoice_id: int | None = None) -> GiftCard:
        rows = self._gift_rows(customer, "AND GCNum = :n", n=number)
        if not rows:
            raise Refused("کارت هدیه پیدا نشد.")
        row = rows[0]
        balance = self._balance(row)
        if balance <= 0 or (not row["IsActive"] and not row["BankPortalEndTime"]):
            raise Refused("این کارت هدیه قابل استفاده نیست.")
        until = _held(row) or vouchers.held_until(invoice_id, gift_card_id=row["Id"])
        if until:
            raise Held("این کارت هدیه در حالت تعلیق قرار دارد.", until)
        if row["StartDate"] and row["StartDate"].date() > _now().date():
            raise Refused("زمان استفاده از این کارت هدیه هنوز نرسیده است.")
        if row["ExpDate"] and row["ExpDate"] < _now():
            raise Refused("مهلت استفاده از این کارت هدیه تمام شده است.")
        return GiftCard(id=row["Id"], number=row["GCNum"], balance=balance, min_price=row["MinFactorPrice"] or Decimal(0),
                        use_whole=bool(row["UseCompelete"]))

    def coupon_page(self, *, search: str, created_from, expires_to, page: int, size: int) -> tuple[int, list[dict]]:
        where, params = ["1 = 1"], {}
        if search:
            where.append("(Serial LIKE :q OR FirstName LIKE :q OR LastName LIKE :q)")
            params["q"] = _like(search)
        if created_from:
            where.append("Created >= :start")
            params["start"] = created_from
        if expires_to:
            where.append("ExpiredDate <= :end")
            params["end"] = expires_to
        where = " AND ".join(where)
        total = fetch_all(f"{LISTED_COUPONS} SELECT COUNT(*) AS n FROM listed WHERE {where}", params)[0]["n"]
        rows = fetch_all(f"""{LISTED_COUPONS} SELECT * FROM listed WHERE {where}
                             ORDER BY Id DESC OFFSET {(page - 1) * size} ROWS FETCH NEXT {size} ROWS ONLY""", params)
        return total, rows

    def coupon_labels(self) -> dict:
        row = fetch_all(f"""{LISTED_COUPONS} SELECT COUNT(*) AS total, ISNULL(SUM(CAST(IsActive AS int)), 0) AS active,
                            ISNULL(SUM(IsUsed), 0) AS used FROM listed""")[0]
        return dict(row)

    def coupon_info(self, coupon_id: int) -> dict | None:
        """Who took a general coupon."""
        source = fetch_all("SELECT Serial FROM Coupons WHERE Id = :id", {"id": coupon_id})
        if not source:
            return None
        rows = fetch_all("""SELECT c.Id, c.CustomerId, c.IsActive, c.IsUsed, u.FirstName, u.LastName
                            FROM Coupons c LEFT JOIN Customers u ON u.Id = c.CustomerId
                            WHERE c.Serial = :s AND c.CustomerId IS NOT NULL AND c.IsDeleted = 0 ORDER BY c.Id DESC""", {"s": source[0]["Serial"]})
        return {"rows": rows, "active": sum(bool(r["IsActive"]) for r in rows), "used": sum(bool(r["IsUsed"]) for r in rows)}

    def gift_card_page(self, filters: dict, page: int, size: int) -> tuple[int, list[dict]]:
        where, params = ["c.IsDeleted = 0"], {}
        if filters.get("search"):
            where.append("(CAST(c.CustomerId AS varchar(20)) LIKE :q OR u.LastName LIKE :q OR u.FirstName LIKE :q OR c.CustomerMobile LIKE :q OR c.GCNum LIKE :q)")
            params["q"] = _like(filters["search"])
        for key, column, operator in (("start_from", "c.StartDate", ">="), ("start_to", "c.StartDate", "<="), ("exp_from", "c.ExpDate", ">="),
                                      ("exp_to", "c.ExpDate", "<="), ("balance_from", "c.GCBalance", ">="), ("balance_to", "c.GCBalance", "<=")):
            if filters.get(key) is not None:
                where.append(f"{column} {operator} :{key}")
                params[key] = filters[key]
        source = f"FROM GiftCards c LEFT JOIN Customers u ON u.Id = c.CustomerId WHERE {' AND '.join(where)}"
        total = fetch_all(f"SELECT COUNT(*) AS n {source}", params)[0]["n"]
        rows = fetch_all(f"""SELECT c.Id, c.GCNum, c.StartDate, c.ExpDate, c.GCBalance, c.IsActive, c.CustomerId, c.UseDepCode, c.MinFactorPrice,
                                    c.GiftGroupMapId, c.CustomerMapId, c.UseCompelete, ISNULL(u.CellPhone, c.CustomerMobile) AS Mobile,
                                    u.FirstName, u.LastName,
                                    (SELECT COUNT(*) FROM Invoices i WHERE i.GiftCardId = c.Id AND i.InvoiceType = 3 AND i.IsDeleted = 0) AS InvoiceCount
                             {source} ORDER BY c.Created DESC, c.Id DESC OFFSET {(page - 1) * size} ROWS FETCH NEXT {size} ROWS ONLY""", params)
        return total, rows

    def gift_card_labels(self) -> dict:
        row = fetch_all("""SELECT COUNT(*) AS total, ISNULL(SUM(CAST(IsActive AS int)), 0) AS active,
                                  ISNULL(SUM(CASE WHEN GCBalance = 0 THEN 1 ELSE 0 END), 0) AS used
                           FROM GiftCards WHERE IsDeleted = 0""")[0]
        return dict(row)
