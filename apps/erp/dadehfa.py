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

from decimal import Decimal

from django.core.management import call_command
from django.utils import timezone

from apps.legacy.db import fetch_all
from apps.website.models import Invoice

from . import dadehfa_write, store
from .connector import Connector, Coupon, GiftCard, Log, Refused
from .models import ErpImage, ErpProduct, ErpStock, ErpVariant, LebazaiImage

PRICE_STEP = 10_000

ON_SALE = """
    FROM Products p JOIN Categories1 c ON c.Id = p.CategoryId
    WHERE p.IsDeleted = 0 AND p.IsActive = 1 AND p.IsSaleable = 1 AND c.IsOnlineActive = 1 AND p.Price > 0
"""


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

    def coupon(self, serial: str, customer) -> Coupon:
        """The customer's own coupon, else a general one (the customer's copy is made when it is used)."""
        columns = "Id, Serial, Reduction, MinPrice, MaxPrice, ExpiredDate, IsUsed, IsActive"
        own = fetch_all(f"SELECT TOP 1 {columns} FROM Coupons WHERE Serial = :s AND CustomerId = :c AND IsDeleted = 0",
                        {"s": serial, "c": customer.erp_customer_id or customer.id})
        general = [] if own else fetch_all(
            f"SELECT TOP 1 {columns} FROM Coupons WHERE Serial = :s AND CustomerId IS NULL AND IsDeleted = 0 AND IsActive = 1",
            {"s": serial})
        row = (own or general or [None])[0]
        if row is None:
            raise Refused("کوپن وجود ندارد.")
        if own and row["IsUsed"]:
            raise Refused("کوپن استفاده شده است.")
        if not row["IsActive"]:
            raise Refused("کوپن غیر فعال است.")
        if row["ExpiredDate"] and row["ExpiredDate"] < timezone.localtime().replace(tzinfo=None):
            raise Refused("مهلت استفاده از این کوپن تمام شده است.")
        return Coupon(id=row["Id"] if own else None, serial=row["Serial"], reduction=row["Reduction"] or Decimal(0),
                      min_price=row["MinPrice"] or Decimal(0), max_price=row["MaxPrice"], expires=row["ExpiredDate"])

    def _gift_rows(self, customer, number: str | None = None) -> list[dict]:
        where = "AND GCNum = :n" if number else ""
        return fetch_all(f"""
            SELECT Id, GCNum, StartDate, ExpDate, GCBalance, IsActive, CustomerId, UseDepCode, MinFactorPrice, UseCompelete
            FROM GiftCards WHERE IsDeleted = 0 AND (CustomerId = :c OR CustomerMobile = :m) {where}
            ORDER BY Id DESC""", {"c": customer.erp_customer_id or customer.id, "m": customer.cellphone, "n": number})

    def gift_cards(self, customer) -> list[dict]:
        return self._gift_rows(customer)

    def gift_card(self, number: str, customer) -> GiftCard:
        rows = self._gift_rows(customer, number)
        if not rows:
            raise Refused("کارت هدیه پیدا نشد.")
        row = rows[0]
        if not row["IsActive"] or not row["GCBalance"]:
            raise Refused("این کارت هدیه قابل استفاده نیست.")
        if row["ExpDate"] and row["ExpDate"] < timezone.localtime().replace(tzinfo=None):
            raise Refused("مهلت استفاده از این کارت هدیه تمام شده است.")
        return GiftCard(id=row["Id"], number=row["GCNum"], balance=row["GCBalance"], min_price=row["MinFactorPrice"] or Decimal(0),
                        use_whole=bool(row["UseCompelete"]))
