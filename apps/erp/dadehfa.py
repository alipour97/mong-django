"""
The Dadehfa connector. Reads what is on sale straight from DadehfaOnlineShop (SELECT only,
apps/legacy/db.py), and writes paid invoices there (apps/erp/dadehfa_write.py). The .NET
service's jobs carry those invoices to the ERP and keep this database fresh, so the service
must stay running while the site is on this connector; the site itself never calls it.

The rules below were worked out against the shop's own API, row by row:

- on sale: active, saleable, online category, priced, with variants and LEBAZAI photos
- stock: all warehouses together (SiteSetting.min_qty is kept back by the storefront)
- price after discount: rounded to 10,000 rials
"""
from __future__ import annotations

import re
from decimal import Decimal

from django.core.management import call_command
from django.utils import timezone

from apps.legacy.db import fetch_all
from apps.website.models import Invoice

from . import dadehfa_write, store, vouchers
from .connector import Connector, Coupon, GiftCard, Held, Log, Refused
from .models import ErpImage, ErpProduct, ErpStock, ErpVariant, LebazaiImage

PRICE_STEP = 10_000

ON_SALE = """
    FROM Products p JOIN Categories1 c ON c.Id = p.CategoryId
    WHERE p.IsDeleted = 0 AND p.IsActive = 1 AND p.IsSaleable = 1 AND c.IsOnlineActive = 1 AND p.Price > 0
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


def _on_sale(ids: list[int]) -> str:
    return f"{ON_SALE} AND p.Id IN ({','.join(str(int(i)) for i in ids)})"


def read() -> store.Read:
    photos = list(LebazaiImage.objects.all())
    ids = sorted({image.product_id for image in photos})
    if not ids:
        return store.Read()
    on_sale = _on_sale(ids)
    products = fetch_all(f"""
        SELECT p.Id, p.Barcode, p.Price, p.Reduction, p.SalesCount {on_sale}""")
    values = {r["Id"]: r for r in fetch_all("SELECT Id, Name, Value, DisplayPriority FROM FeatureValues")}
    variants: dict[int, dict] = {}
    for row in fetch_all(f"""
            SELECT v.ProductId AS pid, v.Id AS vid, f.Id AS ref, v.Barcode AS barcode,
                   d.ParentFeatureValueId AS color, d.ChildFeatureValueId AS size
            FROM ProductVariants v
            JOIN VariantFeatureValues f ON f.ProductVariantId = v.Id AND f.IsDeleted = 0
            JOIN FeatureValueDependencies d ON d.Id = f.FeatureValueDependencyId AND d.IsDeleted = 0
            WHERE v.IsDeleted = 0 AND v.ProductId IN (SELECT p.Id {on_sale}) ORDER BY f.Id"""):
        variants[row["vid"]] = row  # a variant's newest link is the one invoices use

    out = store.Read()
    with_variants = {v["pid"] for v in variants.values()}
    listed = with_variants & {p["Id"] for p in products}
    out.images = [
        ErpImage(product_id=i.product_id, color_id=i.color_id, source_id=i.pk, key=i.key, source=i.source_url, position=position)
        for position, i in enumerate(i for i in photos if i.product_id in listed)
    ]
    now = timezone.now()
    for p in products:
        pid, price = p["Id"], float(p["Price"])
        if pid not in with_variants:
            continue
        reduction = float(p["Reduction"] or 0)
        out.products.append(ErpProduct(
            product_id=pid, erp_id=pid, base_price=int(price), reduction=Decimal(str(reduction)).quantize(Decimal("0.001")),
            sale_price=after_discount(price, reduction), subcode=p["Barcode"] or "", sold=float(p["SalesCount"] or 0), synced_at=now,
        ))
    for v in variants.values():
        color, size = values.get(v["color"]), values.get(v["size"])
        row = ErpVariant(id=v["vid"], product_id=v["pid"], erp_ref=v["ref"], barcode=(v["barcode"] or "").strip())
        if color:
            row.color_id, row.color_name, row.color_value = color["Id"], color["Name"] or "", color["Value"] or ""
            row.color_priority, row.color_family = color["DisplayPriority"] or 0, color["Name"] or ""
        if size:
            row.size_id, row.size_name, row.size_value = size["Id"], size["Name"] or "", size["Value"] or ""
            row.size_priority = size["DisplayPriority"] or 0
        out.variants.append(row)
    for r in fetch_all(f"""
            SELECT w.ProductVariantId AS vid, w.WarehouseId AS warehouse, h.WarehouseTitle AS title, SUM(w.Qty) AS qty
            FROM VariantWarehouses w
            JOIN ProductVariants v ON v.Id = w.ProductVariantId
            LEFT JOIN Warehouses h ON h.Id = w.WarehouseId
            WHERE w.IsDeleted = 0 AND v.IsDeleted = 0 AND v.ProductId IN (SELECT p.Id {on_sale})
            GROUP BY w.ProductVariantId, w.WarehouseId, h.WarehouseTitle"""):
        if r["vid"] in variants:
            out.stock.append(ErpStock(variant_id=r["vid"], warehouse_id=r["warehouse"], warehouse_title=r["title"] or "", qty=r["qty"] or 0))
    return out


class DadehfaConnector(Connector):
    name = "dadehfa"
    all_warehouses = True
    holds_stock = True

    def sync(self, *, full: bool, log: Log) -> dict:
        if full:
            call_command("import_dadehfa", only=["catalog"], upsert=True, verbosity=0)
        result = store.replace(read())
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
