import io
import tempfile
import zipfile
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.adminapi import products as admin_products
from apps.adminapi.models import AdminUser
from apps.samian.models import SamianBarcode, SamianColor, SamianProduct
from apps.storefront import catalog, payments, warm
from apps.website.models import (
    BankGateway, BankInfo, CacheStamp, Category, Customer, CustomerAddress, Feature, FeatureValue, Invoice,
    InvoiceLine, InvoicePayment, Product, ProductAIProfile, ProductSamianLink, ProductTag, ProductVariant,
    SiteSetting, VariantStock,
)

from apps.website import images

from . import dadehfa, dadehfa_write as write, lebazai, outbox, store, vouchers
from .connector import Connector, Held, Refused, SourceError
from .dadehfa import DadehfaConnector
from .samian import SamianConnector
from .management.commands.import_dadehfa_orders import Command as ImportOrders
from .models import ErpCoupon, ErpGiftCard, ErpWriteLog, LebazaiImage, ManualPhoto, SiteCoupon, SiteGiftCard, SyncRun, SyncState


def use_dadehfa(case: TestCase) -> None:
    patcher = mock.patch("apps.erp.store.get_connector", return_value=DadehfaConnector())
    patcher.start()
    case.addCleanup(patcher.stop)


def goods(pid=1, vid=11, qty=5, ref=901) -> ProductVariant:
    Product.objects.update_or_create(id=pid, defaults={"on_sale": True, "erp_id": pid, "price": 1000000, "sale_price": 1000000})
    variant = ProductVariant.objects.create(id=vid, product_id=pid, erp_ref=ref, barcode="b1", color_id=6, color_name="مشکی", size_id=7, size_name="38")
    VariantStock.objects.create(variant=variant, warehouse_id=1, qty=qty)
    return variant


def variant_row(vid=11, pid=1, **fields) -> store.VariantRow:
    return store.VariantRow(**{**dict(id=vid, product_id=pid, erp_ref=None, barcode="", color_id=None, color_name="", color_value="", color_priority=0,
                                      color_family="", size_id=None, size_name="", size_value="", size_priority=0), **fields})


def order(customer, *, state=Invoice.State.SUCCESSFUL, qty=2, **fields) -> Invoice:
    invoice = Invoice.objects.create(customer=customer, state=state, amount=2000000, reduction_amount=200000, delivery_amount=100000,
                                     payable_amount=1900000, **fields)
    InvoiceLine.objects.create(invoice=invoice, product_id=1, variant_id=11, erp_ref=901, name="پیراهن", qty=qty, price=1000000,
                               reduction=Decimal("10"), price_after_reduction=900000)
    return invoice


class StoreTests(TestCase):
    def setUp(self):
        use_dadehfa(self)

    def test_an_empty_read_keeps_what_the_site_has(self):
        goods()
        with self.assertRaises(SourceError):
            store.apply(store.Read())
        self.assertEqual(Product.objects.filter(on_sale=True).count(), 1)

    def test_a_read_much_smaller_than_what_is_on_sale_changes_nothing(self):
        for pid in range(1, 5):
            goods(pid=pid, vid=pid * 10)
        with self.assertRaises(SourceError):
            store.apply(self.fresh_read())
        self.assertEqual(Product.objects.filter(on_sale=True).count(), 4)
        store.apply(self.fresh_read(), force=True)
        self.assertEqual(Product.objects.filter(on_sale=True).count(), 1)

    def test_a_sync_touches_only_what_the_software_owns(self):
        Product.objects.create(id=1, title="قدیم", slug="my-slug", has_manual_slug=True, description="متن سایت", show_torob=True)
        store.apply(store.Read(products=[{"id": 1, "on_sale": True, "title": "جدید", "price": Decimal(5), "new": {"slug": "x"}}]))
        p = Product.objects.get(pk=1)
        self.assertEqual((p.title, p.price, p.slug, p.description, p.show_torob), ("جدید", 5, "my-slug", "متن سایت", True))

    def test_a_new_product_comes_with_what_the_site_needs(self):
        store.apply(store.Read(products=[{"id": 2, "on_sale": True, "title": "ن", "new": {"slug": "n", "slug_key": "n"}}]))
        self.assertEqual(Product.objects.get(pk=2).slug, "n")

    def test_what_left_the_software_leaves_the_sale_and_keeps_its_page(self):
        goods(pid=1, vid=11)
        goods(pid=2, vid=22)
        store.apply(store.Read(products=[{"id": 1, "on_sale": True}], variants=[variant_row()]), force=True)
        self.assertFalse(Product.objects.get(pk=2).on_sale)
        self.assertEqual(list(ProductVariant.objects.values_list("id", flat=True)), [11])

    def test_a_sync_keeps_the_vouchers_of_the_read_only(self):
        ErpCoupon.objects.create(id=1, serial="OLD")
        ErpGiftCard.objects.create(id=1, number="OLD")
        read = self.fresh_read()
        read.coupons, read.gift_cards = [ErpCoupon(id=2, serial="NEW")], []
        store.apply(read)
        self.assertEqual(list(ErpCoupon.objects.values_list("serial", flat=True)), ["NEW"])
        self.assertFalse(ErpGiftCard.objects.exists())

    def fresh_read(self, qty=5) -> store.Read:
        return store.Read(products=[{"id": 1, "on_sale": True}], variants=[variant_row()], stock=[store.StockRow(11, 1, "", qty)])

    def test_a_paid_order_stays_held_until_the_software_has_it(self):
        customer = Customer.objects.create(cellphone="09121111111")
        order(customer)
        store.apply(self.fresh_read())
        self.assertEqual(VariantStock.objects.get().qty, 3)

    def test_a_settled_order_is_no_longer_held(self):
        customer = Customer.objects.create(cellphone="09121111111")
        order(customer, erp_taken_at=timezone.now() - timedelta(hours=1))
        store.apply(self.fresh_read())
        self.assertEqual(VariantStock.objects.get().qty, 5)

    def test_a_just_taken_order_is_held_a_little_longer(self):
        customer = Customer.objects.create(cellphone="09121111111")
        order(customer, erp_taken_at=timezone.now())
        store.apply(self.fresh_read())
        self.assertEqual(VariantStock.objects.get().qty, 3)

    def test_a_cart_holds_nothing(self):
        customer = Customer.objects.create(cellphone="09121111111")
        order(customer, state=Invoice.State.PRE_INVOICE)
        store.apply(self.fresh_read())
        self.assertEqual(VariantStock.objects.get().qty, 5)


class ReadTests(TestCase):
    def rows(self, sql, params=None):
        if "VariantWarehouses" in sql:
            return [{"vid": 50, "warehouse": 2, "title": "انبار", "qty": Decimal("4")}]
        if "FROM Brands" in sql:
            return [{"Id": 15, "Title": "مانگ"}]
        if "Categories1" in sql:
            return [{"Id": 3, "ParentId": None, "Title": "جوراب", "Slug": "c", "HasManualSlug": False, "GroupLevel": 1, "Created": None}]
        if "Products p" in sql and "p.Barcode" in sql:
            return [{"Id": 5, "Barcode": "00500", "Price": Decimal("26800000"), "Reduction": Decimal("62.724"), "SalesCount": 3, "VAT": 0,
                     "Title": " جوراب ", "Slug": "s", "HasManualSlug": False, "CategoryId": 3, "BrandId": 15, "Created": None,
                     "ShortDesc": "%23گروه%0a%20basic", "ProductSeasonTitle": "4051", "ProductStyleTitle": None}]
        if "FROM Coupons" in sql:
            return [{"Id": 1, "CustomerId": None, "Serial": "S", "Reduction": 10, "ExpiredDate": None, "IsUsed": False, "UsedDate": None, "MinPrice": 0,
                     "MaxPrice": None, "IsActive": True, "BankPortalEndTime": None, "Created": None, "FirstName": None, "LastName": None},
                    {"Id": 2, "CustomerId": 8, "Serial": "S", "Reduction": 10, "ExpiredDate": None, "IsUsed": True, "UsedDate": None, "MinPrice": 0,
                     "MaxPrice": None, "IsActive": True, "BankPortalEndTime": None, "Created": None, "FirstName": "ع", "LastName": None}]
        if "FROM GiftCards" in sql:
            return [{"Id": 4, "GCNum": "G", "StartDate": None, "ExpDate": None, "GCBalance": 5, "IsActive": True, "CustomerId": 8, "UseDepCode": False,
                     "MinFactorPrice": 0, "GiftGroupMapId": None, "CustomerMapId": None, "UseCompelete": False, "BankPortalEndTime": None,
                     "Created": None, "Mobile": "0912", "FirstName": "ع", "LastName": None, "InvoiceCount": 2}]
        if "FROM FeatureValues" in sql:
            return [{"Id": 6, "Name": "مشکی", "Value": "000000", "DisplayPriority": 1}, {"Id": 7, "Name": "38", "Value": "38", "DisplayPriority": 2}]
        if "FROM ProductVariants v" in sql:
            base = {"pid": 5, "vid": 50, "barcode": " b ", "color": 6, "size": 7}
            return [{**base, "ref": 900}, {**base, "ref": 901}]
        raise AssertionError(sql)

    def read(self) -> store.Read:
        with mock.patch("apps.erp.dadehfa.fetch_all", side_effect=self.rows):
            return dadehfa.read()

    def test_a_product_as_the_shop_shows_it(self):
        read = self.read()
        product = read.products[0]
        self.assertEqual((product["price"], product["sale_price"], product["reduction"]), (26800000, 9990000, Decimal("62.724")))
        self.assertEqual((product["title"], product["category_id"], product["brand_id"]), ("جوراب", 3, 15))
        self.assertEqual(product["attributes"], {"فصل کالا": "بهار و تابستان", "سبک": "بیسیک"})
        variant = read.variants[0]
        self.assertEqual((variant.erp_ref, variant.barcode, variant.color_family, variant.size_name), (901, "b", "مشکی", "38"))
        self.assertEqual(read.stock[0].qty, 4)

    def test_a_product_without_a_photo_comes_too(self):
        self.assertFalse(LebazaiImage.objects.exists())
        self.assertEqual([p["id"] for p in self.read().products], [5])

    def test_a_category_arrives_off_and_is_the_sites_to_turn_on(self):
        with mock.patch("apps.erp.store.get_connector", return_value=DadehfaConnector()):
            read = self.read()
            store.apply(read)
            self.assertFalse(Category.objects.get(pk=3).is_online_active)
            Category.objects.filter(pk=3).update(is_online_active=True)
            store.apply(read)
        self.assertTrue(Category.objects.get(pk=3).is_online_active)

    def test_a_general_coupon_stands_for_its_copies(self):
        general, copy = sorted(self.read().coupons, key=lambda c: c.id)
        self.assertEqual((general.listed, general.is_used, copy.listed), (True, True, False))

    def test_the_cards_come_with_who_holds_them(self):
        card = self.read().gift_cards[0]
        self.assertEqual((card.number, card.mobile, card.invoice_count), ("G", "0912", 2))

    def test_after_discount_rounds_to_ten_thousand(self):
        self.assertEqual(dadehfa.after_discount(26800000, 62.724), 9990000)


class CatalogTests(TestCase):
    def setUp(self):
        Category.objects.create(id=1, title="ک", slug="k", is_online_active=True)
        Product.objects.create(id=1, title="پ", slug="p", category_id=1, is_active=True)
        Product.objects.create(id=2, title="ن", slug="n", category_id=1, is_active=True)
        SiteSetting.objects.create(min_qty=1, only_has_media_products=True)
        goods(qty=3)
        catalog.clear_caches()
        self.addCleanup(catalog.clear_caches)
        LebazaiImage.objects.create(product_id=1, color_id=6, key="g", source_url="https://cdn.mong.ir/9/g.webp", position=0)

    def test_only_what_the_software_has_is_on_the_site(self):
        bundle = catalog.ProductBundle.load([1, 2])
        self.assertEqual(list(bundle.products), [1])

    def test_stock_less_what_is_kept_back(self):
        bundle = catalog.ProductBundle.load([1])
        self.assertEqual(bundle.variant_stock(1, bundle.variants[1][0]), 2)

    def test_the_main_gallery_is_the_colors_together(self):
        bundle = catalog.ProductBundle.load([1])
        self.assertTrue(bundle.main_images(1)[0]["mediaUrl"].endswith("g.webp"))
        self.assertTrue(bundle.color_images(1, bundle.variants[1][0])[0]["mediaUrl"].endswith("g.webp"))


class FakeResult:
    def __init__(self, value=None, row=None):
        self.value, self.row = value, row

    def scalar(self):
        return self.value

    def mappings(self):
        return self

    def first(self):
        return self.row


class WriteLogTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(first_name="ع", cellphone="09121234567")
        self.address = CustomerAddress.objects.create(customer=self.customer, address="تهران", province_id=8, city_id=301)
        ErpCoupon.objects.create(id=5, serial="S", customer_erp_id=self.customer.id)
        self.invoice = order(self.customer, address=self.address, gift_card_id=4, coupon_id=5, coupon_serial="S", deduction_amount=1000)
        InvoicePayment.objects.create(invoice=self.invoice, gateway="zarinpal", amount=1900000, authority="A", reference="R", is_success=True)
        self.engine = mock.Mock()

    def push(self, db):
        self.engine.begin.return_value = db
        with override_settings(ERP_WRITES_ENABLED=True), mock.patch("apps.erp.dadehfa_write.get_engine", return_value=self.engine):
            write.push(self.invoice)

    def test_every_write_is_logged_and_the_vouchers_are_settled(self):
        self.push(FakeDb())
        log = ErpWriteLog.objects.order_by("id")
        self.assertTrue(all(row.ok and row.software == "dadehfa" and row.invoice_id == self.invoice.pk for row in log))
        actions = [row.action for row in log]
        for action in ("INSERT Customers", "INSERT Invoices", "INSERT InvoiceDetails", "UPDATE Coupons", "UPDATE GiftCards"):
            self.assertIn(action, actions)
        self.assertFalse(any(action.startswith("SELECT") for action in actions))
        self.assertTrue(log.filter(action="INSERT Invoices").first().result)

    def test_a_failed_transaction_is_logged_as_failed(self):
        db = FakeDb()
        real = db.execute

        def fails(statement, params=None):
            if "InvoiceDetails" in str(statement):
                raise RuntimeError("down")
            return real(statement, params)

        db.execute = fails
        with self.assertRaises(RuntimeError):
            self.push(db)
        self.assertTrue(ErpWriteLog.objects.exists())
        self.assertFalse(ErpWriteLog.objects.filter(ok=True).exists())
        self.assertEqual(ErpWriteLog.objects.first().error, "down")

    def test_a_server_out_of_reach_is_logged_too(self):
        self.engine.begin.side_effect = RuntimeError("no server")
        with self.assertRaises(RuntimeError), override_settings(ERP_WRITES_ENABLED=True), \
                mock.patch("apps.erp.dadehfa_write.get_engine", return_value=self.engine):
            write.push(self.invoice)
        self.assertEqual((ErpWriteLog.objects.get().ok, ErpWriteLog.objects.get().error), (False, "no server"))

    def test_nothing_written_nothing_logged(self):
        self.push(FakeDb({"FROM Invoices": 555}))
        self.assertFalse(ErpWriteLog.objects.exists())


class FakeDb:
    """Stands in for SQL Server: checks each statement as the engine does and hands out ids."""

    def __init__(self, found=None):
        self.statements, self.found, self.next_id = [], found or {}, 100

    def execute(self, statement, params=None):
        sql = str(statement)
        write.check(sql)
        self.statements.append((sql, params or {}))
        if sql.startswith("INSERT"):
            self.next_id += 1
            return FakeResult(self.next_id)
        for needle, value in self.found.items():
            if needle in sql:
                return FakeResult(value, value if isinstance(value, dict) else None)
        return FakeResult(None)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def tables(self) -> list[str]:
        return [s.split()[2] for s, _ in self.statements if s.startswith("INSERT")]

    def row(self, table: str) -> dict:
        return next(p for s, p in self.statements if s.startswith(f"INSERT INTO {table} "))


@override_settings(ERP_WRITES_ENABLED=True)
class WriteTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(first_name="علی", last_name="پ", cellphone="09121234567")
        self.address = CustomerAddress.objects.create(customer=self.customer, address="تهران", province_id=8, city_id=301)
        self.invoice = order(self.customer, address=self.address, shipping_method=None, description="سریع")
        InvoicePayment.objects.create(invoice=self.invoice, gateway="zarinpal", amount=1900000, authority="A", reference="R", is_success=True)
        self.db = FakeDb()

    def push(self):
        engine = mock.Mock()
        engine.begin.return_value = self.db
        with mock.patch("apps.erp.dadehfa_write.get_engine", return_value=engine):
            write.push(self.invoice)
        self.invoice.refresh_from_db()

    def test_rows_like_the_shops_own(self):
        self.push()
        self.assertEqual(self.db.tables(), ["Customers", "CustomerAddresses", "Invoices", "InvoiceDetails", "InvoicePayments"])
        head = self.db.row("Invoices")
        self.assertEqual(
            (head["InvoiceType"], head["Amount"], head["Discount"], head["ReductionAmount"], head["AmountAfterReduction"], head["DeliveryAmount"],
             head["FixedAmount"], head["PayableAmount"], head["TsCodeId"]),
            (3, 2000000, 200000, 200000, 1800000, 100000, 100000, 1900000, 0))
        self.assertNotIn("MapId", head)
        line = self.db.row("InvoiceDetails")
        self.assertEqual((line["VariantFeatureValueId"], line["Discount"], line["Reduction"]), (901, 200000, Decimal("10.000")))
        self.assertEqual((self.db.row("InvoicePayments")["BankId"], self.invoice.erp_invoice_id is not None, self.invoice.erp_error), (1, True, ""))
        self.assertIsNotNone(self.invoice.erp_sent_at)
        self.assertEqual((head["CreatedBy"], head["LastModified"], head["Description"]), (f"site:{self.invoice.pk}", head["Created"], "سریع"))

    def test_payment_codes_like_the_shops_own(self):
        """Zarinpal in the shop's rows: TraceNumber = Authority = the tracking code, TransactionId = Zarinpal's authority."""
        self.invoice.payments.update(authority="A" + "0" * 40, reference="7" * 70)
        self.push()
        pay = self.db.row("InvoicePayments")
        self.assertEqual((pay["TraceNumber"], pay["Authority"], pay["TransactionId"]), ("7" * 64, "7" * 64, "A" + "0" * 40))
        self.assertEqual((pay["FullName"], pay["CellPhone"], pay["IsSuccess"]), ("علی پ", "09121234567", 1))

    def test_the_shops_quantity_goes_down(self):
        self.push()
        taken = [p for s, p in self.db.statements if s.startswith("UPDATE ProductVariants")]
        self.assertEqual(taken, [{"q": Decimal(2), "ref": 901}])
        self.assertFalse(any(s.startswith("UPDATE Products ") for s, _ in self.db.statements))

    def test_a_known_customer_is_not_added_again(self):
        self.db = FakeDb({"FROM Customers": 7, "FROM CustomerAddresses": 8})
        self.push()
        self.assertEqual(self.db.tables(), ["Invoices", "InvoiceDetails", "InvoicePayments"])
        self.assertEqual((self.db.row("Invoices")["CustomerId"], self.db.row("Invoices")["CustomerAddressId"]), (7, 8))

    def test_a_retry_after_a_lost_answer_writes_nothing(self):
        self.db = FakeDb({"FROM Invoices": 555})
        self.push()
        self.assertEqual(self.db.tables(), [])
        self.assertEqual(self.invoice.erp_invoice_id, 555)

    def test_sent_once(self):
        self.push()
        first = len(self.db.statements)
        self.push()
        self.assertEqual(len(self.db.statements), first)

    @override_settings(ERP_WRITES_ENABLED=False)
    def test_off_by_default_nothing_is_touched(self):
        with mock.patch("apps.erp.dadehfa_write.get_engine", side_effect=AssertionError):
            write.push(self.invoice)
        self.assertIsNone(Invoice.objects.get(pk=self.invoice.pk).erp_sent_at)

    def test_gift_card_row_and_balance(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(gift_card_number="G1", gift_card_id=44, deduction_amount=500000, payable_amount=1400000)
        self.invoice.refresh_from_db()
        self.push()
        rows = [p for s, p in self.db.statements if s.startswith("INSERT INTO InvoicePayments")]
        self.assertEqual([p["BankId"] for p in rows], [write.GIFT_CARD_BANK, 1])
        card, gateway = rows
        invoice_id = gateway["InvoiceId"]
        self.assertEqual((card["TraceNumber"], card["TransactionId"], card["Authority"], card["PaymentAmount"]),
                         (f"{invoice_id}#G#44", None, gateway["Authority"], 500000))
        self.assertTrue(any(s.startswith("UPDATE GiftCards") and p["d"] == 500000 and p["free"] == 0 for s, p in self.db.statements))
        self.assertEqual(self.db.row("Invoices")["GiftCardId"], 44)

    def test_a_card_that_paid_it_all(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(gift_card_number="G1", gift_card_id=44, deduction_amount=1900000, payable_amount=0)
        self.invoice.payments.all().delete()
        self.invoice.refresh_from_db()
        self.push()
        card = self.db.row("InvoicePayments")
        invoice_id = card["InvoiceId"]
        self.assertEqual((card["TraceNumber"], card["TransactionId"], card["Authority"], card["BankId"]),
                         (f"{invoice_id}#G#G1", str(invoice_id), None, write.GIFT_CARD_BANK))
        self.assertEqual(self.db.row("Invoices")["Description"], "سریع\r\nپرداخت با کارت هدیه")
        self.assertTrue(any(s.startswith("UPDATE GiftCards") and p["free"] == 1 for s, p in self.db.statements))
        self.assertTrue(any(s.startswith("UPDATE Products ") and p == {"q": 2, "ref": 901} for s, p in self.db.statements))

    def test_a_general_coupon_gets_the_customers_own_copy(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(coupon_serial="S1")
        self.invoice.refresh_from_db()
        self.db = FakeDb({"CustomerId IS NULL": {"ExpiredDate": None, "MinPrice": 0, "MaxPrice": None, "Reduction": 10, "MapId": "9"}})
        self.push()
        self.assertEqual((self.db.row("Coupons")["IsUsed"], self.db.row("Coupons")["IsActive"]), (1, 1))
        self.assertEqual(self.db.row("Invoices")["CouponId"], self.db.next_id - 3)

    def test_an_own_coupon_is_marked_used(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(coupon_serial="S1", coupon_id=77)
        self.invoice.refresh_from_db()
        self.push()
        self.assertTrue(any(s.startswith("UPDATE Coupons SET IsActive = 1, BankPortalEndTime = NULL, IsUsed = 1") and p["id"] == 77
                            for s, p in self.db.statements))

    def test_the_customers_own_copy_in_the_software_is_used_first(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(coupon_serial="S1")
        self.invoice.refresh_from_db()
        self.db = FakeDb({"CustomerId = :c": 66})
        self.push()
        self.assertNotIn("Coupons", self.db.tables())
        self.assertEqual(self.db.row("Invoices")["CouponId"], 66)

    def test_a_new_default_address_is_the_only_default(self):
        CustomerAddress.objects.filter(pk=self.address.pk).update(is_default=True)
        self.invoice.refresh_from_db()
        self.push()
        self.assertTrue(any(s.startswith("UPDATE CustomerAddresses SET IsDefault = 0") for s, _ in self.db.statements))

    def test_a_line_without_reference_stays_for_someone_to_look_at(self):
        self.invoice.lines.update(erp_ref=None)
        with self.assertRaises(write.CannotSend):
            self.push()

    def test_only_the_listed_statements_pass(self):
        for good in ("INSERT INTO Invoices (Amount) OUTPUT INSERTED.Id VALUES (:Amount)", "UPDATE Coupons SET IsUsed = 1 WHERE Id = :id",
                     "SELECT TOP 1 Id FROM Customers", "UPDATE ProductVariants SET Qty = Qty - :q WHERE Id = :id"):
            write.check(good)
        for bad in ("DELETE FROM Invoices", "UPDATE Invoices SET MapId = 1", "UPDATE Customers SET Password = ''", "INSERT INTO Products (Id) VALUES (1)",
                    "SELECT 1; DROP TABLE Invoices", "EXEC sp_who", "UPDATE GiftCards SET x = 1; DELETE FROM Coupons"):
            with self.assertRaises(write.NotAllowed):
                write.check(bad)

    def test_a_sysadmin_login_is_refused(self):
        write.get_engine.cache_clear()
        self.addCleanup(write.get_engine.cache_clear)
        conn = mock.MagicMock()
        conn.__enter__.return_value.execute.return_value.scalar.return_value = 1
        with override_settings(DADEHFA_WRITE_DB_USER="u", DADEHFA_WRITE_DB_PASSWORD="p"), \
                mock.patch("apps.erp.dadehfa_write.create_engine") as engine, mock.patch("apps.erp.dadehfa_write.event"):
            engine.return_value.connect.return_value = conn
            with self.assertRaisesRegex(write.CannotSend, "sysadmin"):
                write.get_engine()

    def test_a_sysadmin_login_only_where_it_is_allowed(self):
        write.get_engine.cache_clear()
        self.addCleanup(write.get_engine.cache_clear)
        conn = mock.MagicMock()
        conn.__enter__.return_value.execute.return_value.scalar.return_value = 1
        with override_settings(DADEHFA_WRITE_DB_USER="u", DADEHFA_WRITE_DB_PASSWORD="p", DADEHFA_ALLOW_SYSADMIN=True), \
                mock.patch("apps.erp.dadehfa_write.create_engine") as engine, mock.patch("apps.erp.dadehfa_write.event"):
            engine.return_value.connect.return_value = conn
            self.assertIs(write.get_engine(), engine.return_value)

    def test_no_writing_login_no_writing(self):
        write.get_engine.cache_clear()
        self.addCleanup(write.get_engine.cache_clear)
        no_login = {**settings.DADEHFA_DB, "USER": "", "PASSWORD": ""}
        with override_settings(DADEHFA_WRITE_DB_USER="", DADEHFA_DB=no_login), self.assertRaises(write.CannotSend):
            write.get_engine()


class OutboxTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(cellphone="09121234567")

    def test_a_failure_keeps_the_order_and_says_why(self):
        invoice = order(self.customer)
        connector = mock.Mock(spec=Connector)
        connector.push.side_effect = RuntimeError("down")
        with mock.patch("apps.erp.outbox.get_connector", return_value=connector):
            outbox.run(lambda line: None)
        invoice.refresh_from_db()
        self.assertEqual(invoice.erp_error, "down")
        self.assertIn(invoice, outbox.waiting())

    def test_carts_never_go(self):
        order(self.customer, state=Invoice.State.PRE_INVOICE)
        self.assertFalse(outbox.waiting().exists())

    def test_taken_invoices_are_noted(self):
        invoice = order(self.customer, erp_invoice_id=720, erp_sent_at=timezone.now())
        with mock.patch("apps.erp.dadehfa.fetch_all", return_value=[{"Id": 720}]):
            DadehfaConnector().follow(lambda line: None)
        invoice.refresh_from_db()
        self.assertIsNotNone(invoice.erp_taken_at)


def software_vouchers(customer) -> None:
    """The software's coupon and gift card of the customer, as a sync left them."""
    ErpCoupon.objects.create(id=9, customer_erp_id=customer.id, serial="OK", reduction=Decimal(10), min_price=Decimal(1000))
    ErpGiftCard.objects.create(id=4, number="G1", customer_erp_id=customer.id, balance=Decimal(5000000), starts=timezone.now())


class VoucherTests(TestCase):
    def setUp(self):
        SiteSetting.objects.create(min_qty=0, only_has_media_products=False, coupon_calculation_type=2, gift_card_use_type=1)
        Category.objects.create(id=1, title="ک", slug="k", is_online_active=True)
        Product.objects.create(id=1, title="پ", slug="p", category_id=1, is_active=True)
        goods()
        Product.objects.filter(pk=1).update(reduction=10, sale_price=900000)
        catalog.clear_caches()
        self.addCleanup(catalog.clear_caches)
        self.customer = Customer.objects.create(first_name="ع", cellphone="09121234567")
        self.client = APIClient()
        self.client.force_authenticate(self.customer)
        software_vouchers(self.customer)
        patcher = mock.patch("apps.storefront.catalog.listing_rows", return_value=[SimpleNamespace(id=1)])
        patcher.start()
        self.addCleanup(patcher.stop)

    def add(self, **extra):
        cart = [{"productVariantId": 11, "qty": 2, "name": "پ"}]
        return self.client.post("/api/v1/Invoice/Add", {"productVariants": cart, **extra}, format="json").json()

    def test_a_coupon_comes_off_the_discounted_price(self):
        self.assertEqual(self.add(serial="OK")["statusCode"], 200)
        invoice = Invoice.objects.get()
        self.assertEqual((invoice.deduction_amount, invoice.payable_amount, invoice.coupon_id), (180000, 1620000, 9))

    def test_a_gift_card_comes_off_up_to_the_total(self):
        self.add(gcNum="G1")
        invoice = Invoice.objects.get()
        self.assertEqual((invoice.deduction_amount, invoice.payable_amount, invoice.gift_card_id), (1800000, 0, 4))

    def test_only_one_at_a_time(self):
        self.assertEqual(self.add(serial="OK", gcNum="G1")["statusCode"], 400)

    def test_a_refused_coupon_says_why(self):
        reply = self.add(serial="NO")
        self.assertEqual((reply["statusCode"], reply["statusMessage"]), (400, "کوپن وجود ندارد."))

    def test_validation_and_card_list(self):
        self.assertTrue(self.client.get("/api/v1/Coupon/Validation?serial=OK").json()["result"]["data"]["valid"])
        self.assertFalse(self.client.get("/api/v1/Coupon/Validation?serial=NO").json()["result"]["data"]["valid"])
        self.assertEqual(self.client.get("/api/v1/GiftCard/GetAll").json()["result"]["data"][0]["gcNum"], "G1")


class SoftwareVoucherTests(TestCase):
    """The old API's rules, on what the last sync read."""

    def setUp(self):
        self.customer = Customer.objects.create(first_name="ع", cellphone="09121234567")

    def coupon(self, **row):
        return {"id": 5, "serial": "S", "reduction": Decimal(10), **row}

    def card(self, **row):
        return {"id": 7, "number": "G", "starts": timezone.now() - timedelta(days=1), "balance": Decimal(1000000),
                "customer_erp_id": self.customer.id, **row}

    def read_coupon(self, own=None, general=None, invoice_id=None):
        ErpCoupon.objects.all().delete()
        if own:
            ErpCoupon.objects.create(customer_erp_id=self.customer.id, **own)
        if general:
            ErpCoupon.objects.create(**general)
        return vouchers.find_coupon("S", self.customer, invoice_id)

    def read_card(self, invoice_id=None, **row):
        ErpGiftCard.objects.all().delete()
        ErpGiftCard.objects.create(**self.card(**row))
        return vouchers.find_gift_card("G", self.customer, invoice_id)

    def invoice(self, **fields):
        return Invoice.objects.create(customer=self.customer, **fields)

    def test_a_general_coupon_stays_general(self):
        self.assertIsNone(self.read_coupon(general=self.coupon()).id)

    def test_an_own_coupon_is_used_once(self):
        self.assertEqual(self.read_coupon(own=self.coupon()).id, 5)
        with self.assertRaises(Refused):
            self.read_coupon(own=self.coupon(is_used=True))

    def test_a_coupon_in_a_payment_page_counts_down(self):
        until = timezone.now() + timedelta(minutes=5)
        with self.assertRaises(Held) as caught:
            self.read_coupon(own=self.coupon(is_active=False, held_until=until))
        self.assertEqual(caught.exception.until, until)

    def test_a_hold_that_ran_out_lets_go(self):
        self.assertEqual(self.read_coupon(own=self.coupon(is_active=False, held_until=timezone.now() - timedelta(minutes=1))).id, 5)

    def test_a_switched_off_coupon_is_refused(self):
        with self.assertRaises(Refused):
            self.read_coupon(own=self.coupon(is_active=False))

    def test_a_paid_order_uses_the_coupon_before_the_software_knows(self):
        self.invoice(coupon_serial="S", paid_at=timezone.now(), state=Invoice.State.SUCCESSFUL)
        with self.assertRaises(Refused):
            self.read_coupon(general=self.coupon())

    def test_a_test_payment_uses_it_too(self):
        """A test order is written to the software like any other, so it spends the coupon there."""
        self.invoice(coupon_serial="S", paid_at=timezone.now(), state=Invoice.State.SUCCESSFUL, is_test=True)
        with self.assertRaises(Refused):
            self.read_coupon(general=self.coupon())

    def test_what_a_paid_order_took_comes_off_the_card(self):
        self.invoice(gift_card_id=7, deduction_amount=300000, paid_at=timezone.now(), state=Invoice.State.SUCCESSFUL)
        self.assertEqual(self.read_card().balance, 700000)

    def test_a_sent_order_is_in_the_softwares_balance_already(self):
        self.invoice(gift_card_id=7, deduction_amount=300000, paid_at=timezone.now(), state=Invoice.State.SUCCESSFUL, erp_sent_at=timezone.now())
        SyncState.objects.create(name=store.SYNC_NAME, at=timezone.now())
        self.assertEqual(self.read_card().balance, 1000000)

    def test_a_sent_order_counts_until_a_sync_has_seen_it(self):
        SyncState.objects.create(name=store.SYNC_NAME, at=timezone.now() - timedelta(minutes=1))
        self.invoice(gift_card_id=7, deduction_amount=300000, paid_at=timezone.now(), state=Invoice.State.SUCCESSFUL, erp_sent_at=timezone.now())
        self.assertEqual(self.read_card().balance, 700000)

    def test_a_whole_use_card_ends_with_its_first_order(self):
        self.invoice(gift_card_id=7, deduction_amount=300000, paid_at=timezone.now(), state=Invoice.State.SUCCESSFUL)
        with self.assertRaises(Refused):
            self.read_card(use_whole=True)

    def test_another_invoice_in_a_payment_page_holds_the_card(self):
        other = self.invoice(gift_card_id=7, voucher_held_until=timezone.now() + vouchers.hold())
        with self.assertRaises(Held):
            self.read_card()
        self.assertEqual(self.read_card(other.id).balance, 1000000)

    def test_a_card_not_started_or_expired_is_refused(self):
        now = timezone.now()
        for row in ({"starts": now + timedelta(days=2)}, {"expires": now - timedelta(days=2)}, {"balance": Decimal(0)}):
            with self.assertRaises(Refused):
                self.read_card(**row)

    def test_the_card_list_shows_a_hold_and_drops_a_spent_card(self):
        self.invoice(gift_card_id=7, voucher_held_until=timezone.now() + vouchers.hold())
        self.invoice(gift_card_id=8, deduction_amount=1000000, paid_at=timezone.now(), state=Invoice.State.SUCCESSFUL)
        ErpGiftCard.objects.create(**self.card())
        ErpGiftCard.objects.create(**self.card(id=8))
        cards = vouchers.gift_cards(self.customer)
        self.assertEqual([c["Id"] for c in cards], [7])
        self.assertEqual(cards[0]["Left"][:2], "10")


class VoucherPaymentTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(first_name="ع", cellphone="09121234567")
        self.client = APIClient()
        self.client.force_authenticate(self.customer)
        self.gateways = {key: BankGateway.objects.create(bank=BankInfo.objects.create(id=number, name=key, key=key))
                         for number, key in ((1, "zarinpal"), (14, "snapppay"))}
        software_vouchers(self.customer)
        patcher = mock.patch("apps.storefront.payments._enabled", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def invoice(self, **fields):
        return Invoice.objects.create(customer=self.customer, state=Invoice.State.PRE_INVOICE, amount=1000000, payable_amount=500000,
                                      deduction_amount=500000, gift_card_number="G1", gift_card_id=4, **fields)

    def pay(self, invoice, key="zarinpal"):
        return self.client.get(f"/api/v1/Bank/PayInvoiceById?InvoiceId={invoice.id}&GateWayId={self.gateways[key].id}")

    def test_the_payment_page_holds_the_voucher(self):
        invoice = self.invoice()
        with mock.patch("apps.storefront.payments._start_payment", return_value="https://bank"):
            self.assertEqual(self.pay(invoice).json()["statusCode"], 200)
        invoice.refresh_from_db()
        self.assertGreater(invoice.voucher_held_until, timezone.now() + timedelta(minutes=10))

    def test_a_gateway_that_fails_lets_it_go(self):
        invoice = self.invoice()
        with mock.patch("apps.storefront.payments._start_payment", side_effect=OSError):
            self.pay(invoice)
        invoice.refresh_from_db()
        self.assertIsNone(invoice.voucher_held_until)

    def test_a_failed_payment_lets_it_go(self):
        invoice = self.invoice(voucher_held_until=timezone.now() + vouchers.hold())
        payment = InvoicePayment.objects.create(invoice=invoice, gateway="zarinpal", amount=500000)
        payments._finish(payment, False)
        invoice.refresh_from_db()
        self.assertIsNone(invoice.voucher_held_until)

    def test_a_card_that_no_longer_covers_the_invoice_is_refused(self):
        invoice = self.invoice()
        Invoice.objects.filter(pk=invoice.pk).update(deduction_amount=9000000)
        reply = self.pay(Invoice.objects.get(pk=invoice.pk))
        self.assertEqual(reply.status_code, 409)

    def test_no_gift_card_with_snapppay(self):
        with mock.patch("apps.storefront.payments._start_payment", side_effect=AssertionError):
            self.assertEqual(self.pay(self.invoice(), "snapppay").status_code, 409)


class CouponPanelTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(AdminUser.objects.create(username="a", cellphone="09120000000"))

    def get(self, url):
        with mock.patch("apps.adminapi.views.auth.AdminView.authentication_classes", []):
            return self.client.get(f"/api/admin/v1/{url}")

    def test_the_page_comes_from_the_last_sync(self):
        for i in range(1, 26):
            ErpCoupon.objects.create(id=i, serial=f"S{i}", search_text=f"s{i} علی", is_used=True)
        ErpCoupon.objects.create(id=99, serial="OTHER", search_text="other")
        ErpCoupon.objects.create(id=100, serial="S1", customer_erp_id=4, listed=False, search_text="s1 علی")
        result = self.get("Coupon/GetAll?pageNumber=2&pageSize=10&search=%D8%B9%D9%84%DB%8C").json()["data"]["result"]
        self.assertEqual((result["totalCount"], result["totalPages"], result["pageNumber"]), (25, 3, 2))
        self.assertEqual((result["items"][0]["serial"], result["items"][0]["isUsed"]), ("S15", True))

    def test_labels(self):
        ErpCoupon.objects.create(id=1, serial="A", is_used=True)
        ErpCoupon.objects.create(id=2, serial="B", is_active=False)
        self.assertEqual(self.get("Coupon/GetLable").json()["data"]["result"],
                         {"totalCount": 2, "totalActive": 1, "totalUnActice": 1, "totalUsed": 1})

    def test_a_missing_coupon(self):
        self.assertEqual(self.get("Coupon/GetGeneralCouponInfo?id=1").status_code, 404)

    def test_who_took_a_general_coupon(self):
        ErpCoupon.objects.create(id=1, serial="A")
        ErpCoupon.objects.create(id=2, serial="A", customer_erp_id=8, is_used=True, first_name="ع")
        info = self.get("Coupon/GetGeneralCouponInfo?id=1").json()["data"]["result"]
        self.assertEqual((info["totalCustomerCount"], info["totalUsed"], info["customers"][0]["firstName"]), (1, 1, "ع"))

    def test_gift_card_list(self):
        ErpGiftCard.objects.create(id=1, number="G", search_text="g علی", balance=5, invoice_count=2)
        ErpGiftCard.objects.create(id=2, number="H", search_text="h", balance=0)
        with mock.patch("apps.adminapi.views.auth.AdminView.authentication_classes", []):
            reply = self.client.post("/api/admin/v1/Customer/GetAllGiftCard?pageNumber=1&pageSize=10", {"search": "علي"}, format="json")
        items = reply.json()["data"]["result"]["items"]
        self.assertEqual([(c["gcNum"], c["invoiceCount"]) for c in items], [("G", 2)])
        self.assertEqual(self.get("Customer/GetGiftCardLable").json()["data"]["result"]["totalUsed"], 1)


class SoftwareAwayTests(TestCase):
    """The red line: with both sales programs out of reach, the site does everything a customer and the panel do."""

    def setUp(self):
        SiteSetting.objects.create(min_qty=0, only_has_media_products=False)
        Category.objects.create(id=1, title="ک", slug="k", is_online_active=True)
        Product.objects.create(id=1, title="پیراهن", slug="p", category_id=1, is_active=True)
        goods()
        catalog.clear_caches()
        self.addCleanup(catalog.clear_caches)
        self.customer = Customer.objects.create(first_name="ع", cellphone="09121234567")
        self.address = CustomerAddress.objects.create(customer=self.customer, address="تهران", province_id=8, city_id=301)
        software_vouchers(self.customer)
        self.client = APIClient()
        self.client.force_authenticate(self.customer)
        away = AssertionError("the site reached a sales program")
        for target in ("apps.legacy.db.get_engine", "apps.erp.dadehfa.fetch_all", "apps.erp.dadehfa_write.get_engine", "apps.samian.client.get_samian_client"):
            patcher = mock.patch(target, side_effect=away)
            patcher.start()
            self.addCleanup(patcher.stop)

    def get(self, url):
        reply = self.client.get(f"/api/v1/{url}")
        self.assertEqual(reply.status_code, 200, url)
        return reply

    def post(self, url, body):
        reply = self.client.post(f"/api/v1/{url}", body, format="json")
        self.assertEqual(reply.status_code, 200, url)
        return reply

    def test_browsing(self):
        for url in ("Category/GetAll", "Category/GetBreadCrumbs/1", "Product/GetById/1", "SearchEngine/product/p/breadcrumbs",
                    "Product/GetFilterByCategoryId?id=1"):
            self.get(url)
        self.post("Product/SuggestProduct", {"categoryId": 1, "productId": 2})
        self.post("Product/Search", {"query": "پیراهن", "size": 10})

    def test_the_snapppay_box_needs_no_snapppay_call(self):
        with mock.patch("apps.payhub.snapppay._send", side_effect=AssertionError("called SnappPay")):
            with mock.patch("apps.storefront.payments._enabled", return_value=True):
                box = self.get("Product/GetById/1").json()["result"]["data"]["snappPay"]
            self.assertEqual(box["installments"], 4)
            self.assertIn("{amount}", box["title"])
            self.assertIn("اسنپ\u200cپی", box["title"])
            with mock.patch("apps.storefront.payments._enabled", return_value=False):
                self.assertIsNone(self.get("Product/GetById/1").json()["result"]["data"]["snappPay"])

    def test_vouchers(self):
        self.assertTrue(self.get("Coupon/Validation?serial=OK").json()["result"]["data"]["valid"])
        self.assertEqual(self.get("GiftCard/GetAll").json()["result"]["data"][0]["gcNum"], "G1")

    def test_panel_vouchers(self):
        self.client.force_authenticate(AdminUser.objects.create(username="a", cellphone="09120000000"))
        with mock.patch("apps.adminapi.views.auth.AdminView.authentication_classes", []):
            for url in ("Coupon/GetAll", "Coupon/GetLable", "Customer/GetGiftCardLable", "Products/GetProductLables", "Products/GetAllProduct"):
                self.assertEqual(self.client.get(f"/api/admin/v1/{url}").status_code, 200, url)

    def test_an_order_is_placed_and_paid_and_waits_for_the_software(self):
        cart = [{"productVariantId": 11, "qty": 1, "name": "پیراهن"}]
        reply = self.client.post("/api/v1/Invoice/Add", {"productVariants": cart, "gcNum": "G1"}, format="json").json()
        self.assertEqual(reply["statusCode"], 200, reply)
        invoice = Invoice.objects.get()
        self.assertEqual(invoice.gift_card_id, 4)
        with mock.patch("apps.storefront.payments._notify_admins"), mock.patch("apps.erp.outbox.send_soon"):
            payments._mark_paid(invoice)
        invoice.refresh_from_db()
        self.assertEqual(invoice.state, Invoice.State.SUCCESSFUL)
        self.assertIsNone(invoice.erp_sent_at)

    def test_a_failed_hand_over_loses_nothing(self):
        invoice = order(self.customer)
        self.assertFalse(outbox.send(invoice) and Invoice.objects.get(pk=invoice.pk).erp_sent_at)


class SiteVoucherTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(first_name="ع", cellphone="09121234567")
        self.coupon = SiteCoupon.objects.create(serial="SITE", reduction=Decimal(20))
        self.card = SiteGiftCard.objects.create(number="C1", mobile="+989121234567", amount=1000000)

    def paid(self, **fields):
        return Invoice.objects.create(customer=self.customer, paid_at=timezone.now(), state=Invoice.State.SUCCESSFUL, **fields)

    def test_a_site_coupon_comes_first(self):
        ErpCoupon.objects.create(id=9, serial="SITE", customer_erp_id=self.customer.id, reduction=Decimal(5))
        coupon = vouchers.find_coupon("SITE", self.customer)
        self.assertEqual((coupon.id, coupon.reduction), (None, Decimal(20)))

    def test_any_other_code_is_the_softwares(self):
        software_vouchers(self.customer)
        self.assertEqual(vouchers.find_coupon("OK", self.customer).id, 9)

    def test_once_per_customer_and_never_for_a_test_payment(self):
        self.paid(coupon_serial="SITE", is_test=True)
        vouchers.find_coupon("SITE", self.customer)
        self.paid(coupon_serial="SITE")
        with self.assertRaises(Refused):
            vouchers.find_coupon("SITE", self.customer)

    def test_a_coupon_for_someone_else(self):
        SiteCoupon.objects.filter(pk=self.coupon.pk).update(mobile="09120000000")
        with self.assertRaises(Refused):
            vouchers.find_coupon("SITE", self.customer)

    def test_the_card_keeps_what_is_left(self):
        self.paid(gift_card_number="C1", deduction_amount=300000)
        self.assertEqual(vouchers.find_gift_card("C1", self.customer).balance, 700000)

    def test_the_list_shows_the_sites_cards_first(self):
        software_vouchers(self.customer)
        self.assertEqual([c["GCNum"] for c in vouchers.gift_cards(self.customer)], ["C1", "G1"])

    def test_a_hold_stops_a_second_invoice(self):
        Invoice.objects.create(customer=self.customer, state=Invoice.State.PRE_INVOICE, gift_card_number="C1",
                               voucher_held_until=timezone.now() + timedelta(minutes=5))
        with self.assertRaises(Held):
            vouchers.find_gift_card("C1", self.customer)

    @override_settings(VOUCHER_HOLD_MINUTES=0)
    def test_no_hold_when_the_setting_is_zero(self):
        invoice = Invoice.objects.create(customer=self.customer, state=Invoice.State.PRE_INVOICE, gift_card_number="C1", deduction_amount=1000)
        payments._hold_voucher(invoice)
        invoice.refresh_from_db()
        self.assertIsNone(invoice.voucher_held_until)

    def test_a_site_coupon_is_no_row_in_the_software(self):
        invoice = Invoice(customer=self.customer, coupon_serial="SITE")
        self.assertIsNone(write._use_coupon(None, invoice, 1, timezone.now()))


class ManualPhotoTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser("root", password="x"))

    def test_the_nightly_sync_leaves_a_manual_photo_alone(self):
        ManualPhoto.objects.create(product_id=1, color_id=2, key="up/a", source_url="manual:x")
        LebazaiImage.objects.create(product_id=1, color_id=2, key="lz/old", source_url="http://x")
        with mock.patch("apps.erp.lebazai.lebazai_images", return_value={"B": []}), \
                mock.patch("apps.erp.lebazai.store.barcodes", return_value=[]):
            lebazai.sync_images(lambda line: None)
        self.assertEqual(list(LebazaiImage.objects.values_list("key", flat=True)), ["up/a"])

    def test_a_barcode_finds_its_product_and_color(self):
        picture = io.BytesIO()
        Image.new("RGB", (900, 900)).save(picture, "PNG")
        picture.name = "a.png"
        picture.seek(0)
        with tempfile.TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=folder), \
                mock.patch("apps.erp.admin.store.barcodes", return_value=[("B1", 5, 7)]):
            reply = self.client.post("/django-admin/erp/manualphoto/add/", {"barcode": "B1", "photo": picture, "position": 0})
            self.assertEqual(reply.status_code, 302)
            photo = ManualPhoto.objects.get()
            self.assertEqual((photo.product_id, photo.color_id, photo.key[:3]), (5, 7, "up/"))
            self.assertTrue(images.is_built(photo.key))

    def test_the_admin_pages_open(self):
        for page in ("sitecoupon", "sitegiftcard", "manualphoto"):
            self.assertEqual(self.client.get(f"/django-admin/erp/{page}/").status_code, 200)
            self.assertEqual(self.client.get(f"/django-admin/erp/{page}/add/").status_code, 200)


class TimingTests(TestCase):
    def test_a_measured_request(self):
        with tempfile.TemporaryDirectory() as folder, override_settings(REQUEST_TIMING=True, REQUEST_TIMING_FILE=f"{folder}/t.log", MIDDLEWARE=["config.timing.RequestTiming", *settings.MIDDLEWARE[1:]]):
            reply = self.client.get("/api/v1/Category/GetAll")
            self.assertIn("db;dur=", reply["Server-Timing"])
            out = io.StringIO()
            call_command("timing_report", stdout=out)
            self.assertIn("GET /api/v1/Category/GetAll", out.getvalue())

    def test_off_by_default(self):
        self.assertNotIn("Server-Timing", self.client.get("/api/health/"))


class ImportTests(TestCase):
    def customers(self, *rows):
        blank = dict.fromkeys(("FirstName", "LastName", "Email", "NationalCode", "BirthDate", "JobId", "BulletinSubscriptionDate", "MapId", "LastModified"))
        full = [{**blank, "IsActive": 1, "IsBulletinEnable": 0, "IsDeleted": 0, "Created": timezone.now(), **r} for r in rows]
        with mock.patch("apps.erp.management.commands.import_dadehfa_orders.iter_rows", return_value=full):
            command = ImportOrders()
            command.stdout = mock.Mock()
            return command.customers()

    def test_duplicate_mobiles_fall_on_one_account(self):
        owners = self.customers({"Id": 1, "CellPhone": "0912"}, {"Id": 2, "CellPhone": "0912 "})
        self.assertEqual(owners, {1: 1, 2: 1})

    def test_an_account_made_here_is_kept(self):
        mine = Customer.objects.create(id=1000001, cellphone="0912")
        self.assertEqual(self.customers({"Id": 3, "CellPhone": "0912"}), {3: mine.id})
        self.assertEqual(Customer.objects.count(), 1)

    def test_a_second_run_updates_in_place(self):
        self.customers({"Id": 1, "CellPhone": "0912", "FirstName": "الف"})
        self.customers({"Id": 1, "CellPhone": "0912", "FirstName": "ب"})
        self.assertEqual(Customer.objects.get().first_name, "ب")


@override_settings(ERP_WRITES_ENABLED=True)
class PaidOrderTests(TestCase):
    """From a paid order to the rows handed to the software, stock taken on the way."""

    def test_the_whole_way(self):
        from apps.storefront import payments

        use_dadehfa(self)
        customer = Customer.objects.create(first_name="ع", cellphone="09121234567")
        address = CustomerAddress.objects.create(customer=customer, address="تهران", province_id=8, city_id=301)
        variant = goods(qty=5)
        invoice = order(customer, state=Invoice.State.PRE_INVOICE, address=address)
        InvoicePayment.objects.create(invoice=invoice, gateway="zarinpal", amount=1900000, authority="A", reference="R", is_success=True)
        with mock.patch("apps.storefront.payments._notify_admins"):
            payments._mark_paid(invoice)
        self.assertEqual(VariantStock.objects.get(variant=variant).qty, 3)

        db, engine = FakeDb(), mock.Mock()
        engine.begin.return_value = db
        with mock.patch("apps.erp.dadehfa_write.get_engine", return_value=engine), \
                mock.patch("apps.erp.outbox.get_connector", return_value=DadehfaConnector()), \
                mock.patch.object(DadehfaConnector, "follow"):
            outbox.run(lambda line: None)
            outbox.run(lambda line: None)
        self.assertEqual(db.tables().count("Invoices"), 1)
        invoice.refresh_from_db()
        self.assertIsNotNone(invoice.erp_invoice_id)
        self.assertFalse(outbox.waiting().exists())


class WriterLoginTests(TestCase):
    """The writing login is a pair: never one login's user with the other's password."""

    def login(self, **env):
        write.get_engine.cache_clear()
        self.addCleanup(write.get_engine.cache_clear)
        reader = {**settings.DADEHFA_DB, "HOST": "h", "PORT": "1433", "NAME": "db", "USER": "sa", "PASSWORD": "p@ss word+1"}
        with override_settings(DADEHFA_DB=reader, DADEHFA_ALLOW_SYSADMIN=True, **env), \
                mock.patch("apps.erp.dadehfa_write.create_engine") as engine, mock.patch("apps.erp.dadehfa_write.event"):
            engine.return_value.connect.return_value = mock.MagicMock()
            write.get_engine()
        url = engine.call_args.args[0]
        return url.username, url.password

    def test_sa_for_both_takes_the_readers_password(self):
        self.assertEqual(self.login(DADEHFA_WRITE_DB_USER="sa", DADEHFA_WRITE_DB_PASSWORD="old-writer"), ("sa", "p@ss word+1"))

    def test_an_own_writer_keeps_its_password(self):
        self.assertEqual(self.login(DADEHFA_WRITE_DB_USER="mong_writer", DADEHFA_WRITE_DB_PASSWORD="w"), ("mong_writer", "w"))


class DeleteInvoiceTests(TestCase):
    def test_lines_payments_and_hub_records_go_the_softwares_copy_is_named(self):
        from apps.payhub.models import PayRecord
        from apps.website.admin import delete_invoices

        customer = Customer.objects.create(cellphone="09121234567")
        invoice = order(customer, erp_invoice_id=555)
        InvoicePayment.objects.create(invoice=invoice, gateway="zarinpal", amount=1, is_success=True)
        PayRecord.objects.create(source=PayRecord.Source.SITE, transaction_id=str(invoice.pk), token="t", gateway="zarinpal", amount=1)
        ErpWriteLog.objects.create(invoice_id=invoice.pk, software="dadehfa")
        self.assertEqual(delete_invoices([invoice]), [555])
        self.assertFalse(Invoice.objects.exists() or InvoiceLine.objects.exists() or InvoicePayment.objects.exists())
        self.assertFalse(PayRecord.objects.exists())
        self.assertTrue(ErpWriteLog.objects.exists())

    def test_the_admin_deletes(self):
        user = User.objects.create_superuser("a", "a@a.a", "p")
        client = self.client
        client.force_login(user)
        invoice = order(Customer.objects.create(cellphone="09121234567"))
        response = client.post(f"/django-admin/website/invoice/{invoice.pk}/delete/", {"post": "yes"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Invoice.objects.exists())


class TestPaymentTests(TestCase):
    """Sandbox money still makes an invoice in the software, so the whole way can be tried; its Description says it is a test."""

    def setUp(self):
        use_dadehfa(self)
        self.customer = Customer.objects.create(cellphone="09121234567")

    def test_sent_and_held_like_any_other(self):
        invoice = order(self.customer, is_test=True)
        self.assertEqual(list(outbox.waiting()), [invoice])
        self.assertEqual(list(store.open_orders()), [invoice])

    @override_settings(ERP_WRITES_ENABLED=True)
    def test_the_writer_writes_it_with_a_note(self):
        address = CustomerAddress.objects.create(customer=self.customer, address="تهران", province_id=8, city_id=301)
        invoice = order(self.customer, is_test=True, address=address, description="سریع")
        InvoicePayment.objects.create(invoice=invoice, gateway="zarinpal", amount=1900000, authority="A", reference="R", is_success=True)
        db, engine = FakeDb(), mock.Mock()
        engine.begin.return_value = db
        with mock.patch("apps.erp.dadehfa_write.get_engine", return_value=engine):
            write.push(invoice)
        self.assertEqual(db.row("Invoices")["Description"], f"{write.TEST_MARK}\r\nسریع")
        self.assertIsNotNone(Invoice.objects.get(pk=invoice.pk).erp_sent_at)

    def finish(self, gateway: str) -> Invoice:
        from apps.storefront import payments

        invoice = order(self.customer, state=Invoice.State.PRE_INVOICE)
        goods()
        payment = InvoicePayment.objects.create(invoice=invoice, gateway=gateway, amount=1900000)
        with mock.patch("apps.storefront.payments._notify_admins") as notify, self.captureOnCommitCallbacks(execute=True), \
                mock.patch("apps.erp.outbox.send_soon"), mock.patch("apps.storefront.catalog.clear_caches"):
            payments._finish(payment, True, "R")
        invoice.refresh_from_db()
        self.notified = notify.called
        return invoice

    @override_settings(ZARINPAL_SANDBOX=True)
    def test_a_sandbox_zarinpal_payment_is_a_test(self):
        self.assertTrue(self.finish("zarinpal").is_test)
        self.assertTrue(self.notified)  # admins are texted for test orders too

    @override_settings(ZARINPAL_SANDBOX=False)
    def test_a_live_zarinpal_payment_is_real(self):
        self.assertFalse(self.finish("zarinpal").is_test)
        self.assertTrue(self.notified)

    @override_settings(SNAPPAY_IS_STAGE=True)
    def test_a_stage_snapppay_payment_is_a_test(self):
        self.assertTrue(self.finish("snapppay").is_test)

    @override_settings(SNAPPAY_IS_STAGE=False)
    def test_a_live_snapppay_payment_is_real(self):
        self.assertFalse(self.finish("snapppay").is_test)


class OriginalImagesTests(TestCase):
    def rows(self):
        def sku(color, code, *urls):
            return {"color": color, "barcode": code, "all_barcodes": [code, code + "x"], "images": [{"url": u} for u in urls]}
        return [
            {"subcode": "111", "skus": [sku("مشکی", "b1", "http://l/a.jpg", "http://l/b.jpg")]},
            {"subcode": "222", "skus": [sku("سفید", "b2", "http://l/c.jpg")]},
            {"subcode": "333", "skus": [sku("سفید", "b3", "http://l/d.jpg")]},
            {"subcode": "444", "skus": [sku("سفید", "nope", "http://l/e.jpg")]},
        ]

    def run_add(self, **kwargs):
        barcodes = [("b1", 1, 10), ("b2x", 2, 20), ("b3", 3, 30)]
        with mock.patch("apps.erp.lebazai.store.barcodes", return_value=barcodes), \
                mock.patch("apps.erp.lebazai.lebazai_originals", side_effect=lambda **kw: [r for r in self.rows() if r["subcode"] in kw.get("subcodes", [r["subcode"]])]), \
                mock.patch("apps.erp.lebazai.images.build"), mock.patch("apps.erp.lebazai.images.is_built", return_value=False), \
                mock.patch("apps.erp.lebazai.requests.get", return_value=mock.Mock(content=b"x", raise_for_status=lambda: None)):
            return lebazai.add_originals(log=lambda line: None, **kwargs)

    def test_the_first_n_products_on_sale_get_their_originals(self):
        result = self.run_add(departments=["a/b/c"], count=2)
        self.assertEqual((result["products"], result["images"]), (2, 3))
        self.assertEqual(sorted(LebazaiImage.objects.values_list("product_id", "color_id")), [(1, 10), (1, 10), (2, 20)])
        self.assertTrue(all(k.startswith("lo/") for k in LebazaiImage.objects.values_list("key", flat=True)))

    def test_a_second_run_picks_the_same_products(self):
        self.run_add(departments=["a/b/c"], count=1)
        self.run_add(departments=["a/b/c"], count=1)
        self.assertEqual(set(LebazaiImage.objects.values_list("product_id", flat=True)), {1})
        self.assertEqual(LebazaiImage.objects.count(), 2)

    def test_a_product_with_approved_photos_is_left_alone(self):
        LebazaiImage.objects.create(product_id=1, color_id=10, key="lz/x", source_url="http://x")
        self.run_add(departments=["a/b/c"], count=1)
        self.assertEqual(set(LebazaiImage.objects.exclude(key="lz/x").values_list("product_id", flat=True)), {2})

    def test_the_given_subcode_is_among_the_n(self):
        result = self.run_add(departments=["a/b/c"], count=2, subcodes=["333"])
        self.assertEqual(set(LebazaiImage.objects.values_list("product_id", flat=True)), {1, 3})
        self.assertEqual(result["products"], 2)

    def test_dry_run_saves_nothing(self):
        self.assertEqual(self.run_add(departments=["a/b/c"], count=2, dry_run=True)["products"], 2)
        self.assertFalse(LebazaiImage.objects.exists())


class SamianSyncTests(TestCase):
    """A move to Samian changes the sync and nothing else."""

    def setUp(self):
        Feature.objects.create(id=1, name="رنگ")
        Feature.objects.create(id=2, name="سایز")
        FeatureValue.objects.create(id=6, feature_id=1, name="مشكي", value="000000")
        Product.objects.create(id=1, title="پ", slug="p", description="متن", on_sale=True)
        ProductVariant.objects.create(id=11, product_id=1, barcode="b1", color_id=6, color_name="مشكي")
        ProductAIProfile.objects.create(product_id=1, title="عنوان")
        LebazaiImage.objects.create(product_id=1, color_id=6, key="lz/a", source_url="https://l/a.jpg")
        sp = SamianProduct.objects.create(samian_id=70, subcode="1", name="پ", sale_price=1000000)
        ProductSamianLink.objects.create(product_id=1, samian_product_id=70, method="manual")
        SamianColor.objects.create(samian_id=500, title="مشکی", panel_title="مشکی", hex_code="000000")
        self.old = SamianBarcode.objects.create(samian_id=900, barcode="b1", samian_product=sp, colorinfo_id=500, is_active=True)
        self.new = SamianBarcode.objects.create(samian_id=901, barcode="b2", samian_product=sp, colorinfo_id=500, is_active=True)
        for patcher in (mock.patch("apps.erp.store.get_connector", return_value=SamianConnector()),
                        mock.patch("apps.erp.samian.sold_by_product", return_value={})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_sync(self):
        SamianConnector().sync(log=lambda line: None)

    def test_a_barcode_keeps_its_variant_and_a_color_its_id(self):
        self.run_sync()
        old, new = ProductVariant.objects.get(barcode="b1"), ProductVariant.objects.get(barcode="b2")
        self.assertEqual((old.id, old.erp_ref, old.color_id), (11, 900, 6))
        self.assertEqual((new.id, new.erp_ref, new.color_id), (12, 901, 6))

    def test_photos_and_ai_copy_stay(self):
        self.run_sync()
        product = Product.objects.get(pk=1)
        self.assertEqual((product.price, product.sale_price, product.description), (1000000, 1000000, "متن"))
        self.assertEqual(ProductAIProfile.objects.get().title, "عنوان")
        self.assertEqual(LebazaiImage.objects.get().key, "lz/a")

    def test_the_softwares_vouchers_do_not_outlive_it(self):
        ErpCoupon.objects.create(id=1, serial="S")
        self.run_sync()
        self.assertFalse(ErpCoupon.objects.exists())


class WarmAcrossProcessesTests(TestCase):
    """The web workers, the sync and the Django admin share no memory: an invalidation goes through the database."""

    key = "test:warm"

    def setUp(self):
        self.builds = []
        self.addCleanup(lambda: [store.pop(self.key, None) for store in (warm._values, warm._built_from, warm._seen)])
        self.addCleanup(cache.delete, self.key)

    def build(self):
        self.builds.append(1)
        return len(self.builds)

    def test_a_change_in_another_process_makes_the_value_stale(self):
        self.assertEqual(warm.get(self.key, 600, self.build), 1)
        CacheStamp.objects.create(key=self.key, stamp=5)
        warm._seen.pop(self.key)  # the check is due
        with mock.patch.object(warm.threading, "Thread") as rebuild:
            self.assertEqual(warm.get(self.key, 600, self.build), 1)  # answers at once
        rebuild.assert_called_once()

    def test_no_query_between_checks(self):
        warm.get(self.key, 600, self.build)
        with self.assertNumQueries(0):
            warm.get(self.key, 600, self.build)

    def test_invalidate_is_seen_here_at_once(self):
        warm.get(self.key, 600, self.build)
        warm.invalidate(self.key)
        warm.invalidate(self.key)
        self.assertEqual(CacheStamp.objects.get(key=self.key).stamp, 2)
        with mock.patch.object(warm.threading, "Thread") as rebuild:
            warm.get(self.key, 600, self.build)
        rebuild.assert_called_once()

    def test_clear_caches_marks_the_admin_rows_stale(self):
        catalog.clear_caches()
        self.assertTrue(CacheStamp.objects.filter(key=catalog.ADMIN_ROWS_CACHE_KEY).exists())


class AdminDescriptionTests(TestCase):
    """«عنوان هیبرید» and «توضیح تکمیلی» show LEBAZAI's copy until the site has its own."""

    def setUp(self):
        self.product = Product.objects.create(id=9, title="t", barcode="b", slug="t")
        self.client = APIClient()
        self.client.force_authenticate(AdminUser.objects.create(username="a", cellphone="09120000000"))
        patcher = mock.patch("apps.adminapi.views.auth.AdminView.authentication_classes", [])
        patcher.start()
        self.addCleanup(patcher.stop)

    def read(self):
        return self.client.get(f"/api/admin/v1/Products/{self.product.id}/descriptions").json()["data"]["result"]

    def test_nothing_to_show(self):
        self.assertEqual(self.read(), {"longDescriptionHtml": None, "shortDescriptionHtml": None})

    def test_ai_copy_until_the_site_has_its_own(self):
        ProductAIProfile.objects.create(product=self.product, title="عنوان", description="توضیح")
        self.assertEqual(self.read(), {"longDescriptionHtml": "توضیح", "shortDescriptionHtml": "عنوان"})
        Product.objects.filter(id=9).update(short_description_html="خود سایت")
        self.assertEqual(self.read(), {"longDescriptionHtml": "توضیح", "shortDescriptionHtml": "خود سایت"})

    def test_list_flags_count_the_ai_copy(self):
        Product.objects.filter(id=9).update(on_sale=True, is_active=True)
        ProductAIProfile.objects.create(product=self.product, title="عنوان")
        row = next(r for r in admin_products._build() if r.id == 9)
        self.assertTrue(row.has_short_description)
        self.assertFalse(row.has_long_description)


class MediaPackTests(TestCase):
    url_a, url_b = "http://x/front.png", "http://x/back.png"

    def picture(self):
        out = io.BytesIO()
        Image.new("RGB", (64, 64)).save(out, "PNG")
        return out.getvalue()

    def sync(self, urls):
        reply = mock.Mock(content=self.picture())
        with mock.patch("apps.erp.lebazai.lebazai_images", return_value={"B": urls}), \
                mock.patch("apps.erp.lebazai.store.barcodes", return_value=[("B", 5, 7)]), \
                mock.patch("apps.erp.lebazai.requests.get", return_value=reply) as download:
            result = lebazai.sync_images(lambda line: None)
        return result, download.call_count

    def order(self):
        return list(LebazaiImage.objects.filter(key__startswith="lz/").order_by("position").values_list("source_url", flat=True))

    def test_the_first_of_lebazai_is_the_preview_and_only_new_photos_are_downloaded(self):
        with tempfile.TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=folder):
            self.assertEqual(self.sync([self.url_a, self.url_b])[1], 2)
            self.assertEqual(self.order(), [self.url_a, self.url_b])
            result, downloads = self.sync([self.url_b, self.url_a])
            self.assertEqual((downloads, result["moved"]), (0, 2))
            self.assertEqual(self.order(), [self.url_b, self.url_a])
            self.assertEqual(self.sync([self.url_b, self.url_a, "http://x/new.png"])[1], 1)

    def test_a_color_with_only_a_back_photo_gets_no_photos(self):
        with tempfile.TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=folder):
            self.sync([self.url_a, self.url_b])
            key = LebazaiImage.objects.get(source_url=self.url_b).key
            result, downloads = self.sync([self.url_b])  # LEBAZAI dropped the front photo
            self.assertEqual((downloads, result["no_front"], result["removed"]), (0, 1, 2))
            self.assertEqual(self.order(), [])
            self.assertFalse((images.img_root() / key).exists())
            self.assertEqual(self.sync(["http://x/Mong/0310/back_temp1_1.png"])[1], 0)

    def test_a_pack_gives_a_new_server_everything_without_a_download(self):
        Product.objects.create(id=5, title="t", barcode="P5", slug="t")
        Product.objects.create(id=6, title="u", barcode="P6", slug="u")
        ProductAIProfile.objects.create(product_id=5, subcode="P5", title="عنوان", description="توضیح", search_keywords=["برچسب"])
        with tempfile.TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=f"{folder}/here"):
            self.sync([self.url_a, self.url_b])
            source = images.img_root()
            images.build("lo/sock", self.picture())
            (source.parent / "resumes").mkdir()
            (source.parent / "resumes" / "cv.pdf").write_bytes(b"private")
            LebazaiImage.objects.create(product_id=6, color_id=1, key="lo/sock", source_url="http://x/s.png", position=100)
            pack = f"{folder}/pack.zip"
            call_command("export_media", output=pack, stdout=io.StringIO())
            with zipfile.ZipFile(pack) as archive:
                self.assertFalse([n for n in archive.namelist() if "resumes" in n])

            manual = LebazaiImage.objects.create(product_id=6, color_id=1, key="up/mine", source_url="http://x/m.png")
            LebazaiImage.objects.exclude(pk=manual.pk).delete()
            ProductAIProfile.objects.all().delete()
            with override_settings(MEDIA_ROOT=f"{folder}/there"):
                call_command("install_media", pack, stdout=io.StringIO())
                self.assertEqual(LebazaiImage.objects.filter(key__startswith="lz/").order_by("position").first().source_url, self.url_a)
                self.assertEqual(sorted(LebazaiImage.objects.exclude(key__startswith="lz/").values_list("key", flat=True)), ["lo/sock", "up/mine"])
                profile = ProductAIProfile.objects.get(product_id=5)
                self.assertEqual((profile.subcode, profile.title), ("P5", "عنوان"))
                self.assertTrue(ProductTag.objects.filter(product_id=5, tag__title="برچسب").exists())
                self.assertEqual(self.sync([self.url_a, self.url_b])[1], 0)
                out = io.StringIO()
                call_command("install_media", pack, stdout=out)  # again: nothing to extract, no rows doubled
                self.assertIn("were already there", out.getvalue())
                self.assertEqual(LebazaiImage.objects.count(), 4)

    def test_a_pack_with_a_missing_photo_is_refused(self):
        LebazaiImage.objects.create(product_id=1, color_id=1, key="lz/none", source_url="http://x/n.png")
        with tempfile.TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=folder):
            with self.assertRaises(CommandError):
                call_command("export_media", output=f"{folder}/pack.zip", stdout=io.StringIO())



class SyncJobTests(TestCase):
    """The jobs the admin panel shows and runs: each run is recorded with what it changed."""

    def setUp(self):
        Product.objects.create(id=1, title="پ", slug="p", on_sale=True, price=100, sale_price=100)
        Product.objects.create(id=2, title="ن", slug="n", on_sale=True, price=50, sale_price=50)

    def fake(self, **kw):
        def sync(*, force=False, log):
            return store.apply(store.Read(products=[{"id": 1, "on_sale": True, "price": 120, "sale_price": 120}]), force=True)
        return mock.patch("apps.erp.connector.get_connector", return_value=SimpleNamespace(
            name="dadehfa", sync=sync, holds_stock=False, **kw))

    def test_the_cron_run_is_recorded_with_what_changed(self):
        from . import jobs
        with self.fake(), mock.patch("apps.erp.store.get_connector", return_value=SimpleNamespace(holds_stock=False)):
            call_command("sync_erp", stdout=io.StringIO())
        run = SyncRun.objects.get()
        self.assertEqual((run.job, run.trigger, run.ok), ("erp", "auto", True))
        self.assertIsNotNone(run.finished_at)
        self.assertIn("قیمت 1 کالا تغییر کرد", run.changes)
        self.assertIn("0 کالا به فروش آمد، 1 کالا از فروش خارج شد", run.changes)
        self.assertEqual(jobs.last("erp", "auto"), run)

    def test_a_failure_is_recorded_and_the_command_fails(self):
        def sync(*, force=False, log):
            raise SourceError("در دسترس نیست")
        with mock.patch("apps.erp.connector.get_connector", return_value=SimpleNamespace(name="dadehfa", sync=sync)):
            with self.assertRaises(CommandError):
                call_command("sync_erp", stdout=io.StringIO())
        run = SyncRun.objects.get()
        self.assertFalse(run.ok)
        self.assertEqual(run.error, "در دسترس نیست")

    def test_one_started_by_hand_is_not_started_twice(self):
        from . import jobs
        busy = SyncRun.objects.create(job="erp", trigger="manual")
        self.assertEqual(jobs.start("erp", background=False), busy)
        SyncRun.objects.filter(pk=busy.pk).update(started_at=timezone.now() - timedelta(hours=1))  # died with its process
        with self.fake(), mock.patch("apps.erp.store.get_connector", return_value=SimpleNamespace(holds_stock=False)):
            fresh = jobs.start("erp", by="a", background=False)
        self.assertNotEqual(fresh, busy)
        self.assertEqual((fresh.trigger, fresh.ok, fresh.by), ("manual", True, "a"))

    def test_the_outbox_job_counts_and_reconciles_only_when_due(self):
        with mock.patch("apps.erp.outbox.run", return_value={"sent": 2, "failed": 1, "taken": 0}), \
                mock.patch("apps.payhub.service.reconcile", side_effect=AssertionError("nothing is due")):
            call_command("erp_outbox", stdout=io.StringIO())
        self.assertEqual(SyncRun.objects.get().changes, ["2 فاکتور به نرم‌افزار فروش رفت", "1 فاکتور نرفت (علت در صفحهٔ فاکتور)"])

    def test_sales_set_the_best_seller_numbers(self):
        Product.objects.filter(id=2).update(sold=9)
        connector = SimpleNamespace(name="other", sold=lambda: {1: 5.0})
        with mock.patch("apps.erp.connector.get_connector", return_value=connector):
            call_command("sync_sales", stdout=io.StringIO())
        self.assertEqual(dict(Product.objects.values_list("id", "sold")), {1: 5.0, 2: 0.0})
        self.assertEqual(SyncRun.objects.get().changes, ["فروش 2 کالا به‌روز شد (1 کالا فروش دارند)"])

    def test_dadehfa_sales_add_up_every_barcode_of_a_product(self):
        ProductVariant.objects.create(id=10, product_id=1, barcode="A")
        ProductVariant.objects.create(id=11, product_id=1, barcode="B")
        ProductVariant.objects.create(id=12, product_id=2, barcode="C")
        rows = [{"barcode": "A", "qty": Decimal(3)}, {"barcode": "B", "qty": Decimal(-1)}, {"barcode": "Z", "qty": Decimal(7)}]
        with mock.patch("apps.erp.dadehfa.fetch_all", return_value=rows) as fetch:
            self.assertEqual(DadehfaConnector().sold(), {1: 2.0})
        self.assertIn("[PTCERPNew].dbo.tblPosTransactionsItems", fetch.call_args[0][0])

    def test_a_late_or_failed_job_is_yellow_or_red_and_a_manual_run_counts(self):
        from . import jobs
        job = jobs.JOBS["erp"]
        self.assertEqual(jobs.state(job, None), "late")
        run = SyncRun.objects.create(job="erp", trigger="manual", ok=True, finished_at=timezone.now())
        self.assertEqual(jobs.state(job, jobs.last_finished("erp")), "ok")
        SyncRun.objects.filter(pk=run.pk).update(started_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(jobs.state(job, jobs.last_finished("erp")), "late")
        SyncRun.objects.create(job="erp", ok=False, finished_at=timezone.now(), error="x")
        self.assertEqual(jobs.state(job, jobs.last_finished("erp")), "error")
        self.assertEqual(jobs.worst(["ok", "late", "error"]), "error")
        self.assertEqual(jobs.worst(["ok", "late"]), "late")


class SyncPanelTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(AdminUser.objects.create(username="a", cellphone="09120000000"))
        self.no_auth = mock.patch("apps.adminapi.views.auth.AdminView.authentication_classes", [])
        self.no_auth.start()
        self.addCleanup(self.no_auth.stop)

    def status(self):
        return self.client.get("/api/admin/v1/Dashboard/SynchronizationStatus").json()["data"]["result"]

    def test_status_shows_each_jobs_last_run_and_state(self):
        SyncRun.objects.create(job="erp", trigger="auto", ok=True, finished_at=timezone.now(), changes=["x"])
        SyncRun.objects.create(job="erp", trigger="manual", started_at=timezone.now())  # running now
        result = self.status()
        erp = next(i for i in result["incomingData"] if i["operationKey"] == "erp")
        self.assertEqual(erp["state"], "ok")
        self.assertEqual(erp["lastAuto"]["changes"], ["x"])
        self.assertTrue(erp["lastRun"]["running"])
        lebazai = next(i for i in result["incomingData"] if i["operationKey"] == "lebazai")
        self.assertEqual(lebazai["state"], "late")  # never ran
        self.assertEqual(result["incomingState"], "late")
        self.assertEqual([i["operationKey"] for i in result["outgoingData"]], ["outbox", "pending"])

    def test_pending_turns_yellow_with_an_order_waiting_and_red_with_one_that_failed(self):
        SyncRun.objects.create(job="outbox", ok=True, finished_at=timezone.now())
        self.assertEqual(self.status()["outgoingState"], "ok")
        customer = Customer.objects.create(cellphone="09120000001")
        Invoice.objects.create(customer=customer, state=Invoice.State.SUCCESSFUL, paid_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(self.status()["outgoingState"], "late")
        Invoice.objects.update(erp_error="refused")
        pending = self.status()["outgoingData"][-1]
        self.assertEqual(pending["state"], "error")
        self.assertIn("1 فاکتور با خطا مانده", pending["lines"])

    def test_running_one_by_hand(self):
        with mock.patch("apps.erp.jobs.threading.Thread") as thread:
            started = self.client.post("/api/admin/v1/Dashboard/SyncRun", {"job": "lebazai"}, format="json").json()
        thread.return_value.start.assert_called_once()
        run = started["data"]["result"]
        self.assertTrue(run["running"])
        self.assertEqual(run["by"], "a")
        SyncRun.objects.filter(pk=run["id"]).update(ok=True, finished_at=timezone.now(), changes=["y"])
        done = self.client.get(f"/api/admin/v1/Dashboard/SyncRun?id={run['id']}").json()["data"]["result"]
        self.assertEqual((done["running"], done["ok"], done["changes"]), (False, True, ["y"]))
        self.assertEqual(self.client.post("/api/admin/v1/Dashboard/SyncRun", {"job": "nope"}, format="json").status_code, 404)


class DashboardTests(TestCase):
    """The panel's numbers are the online shop's own orders, without test ones."""

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(AdminUser.objects.create(username="a", cellphone="09120000000"))
        patch = mock.patch("apps.adminapi.views.auth.AdminView.authentication_classes", [])
        patch.start()
        self.addCleanup(patch.stop)
        Product.objects.create(id=1, title="پرفروش", slug="p")
        Product.objects.create(id=2, title="کم‌فروش", slug="n")
        customer = Customer.objects.create(cellphone="09120000001")
        for qty, pid, test, state in ((3, 1, False, 3), (1, 2, False, 3), (9, 2, True, 3), (9, 2, False, 4)):
            invoice = Invoice.objects.create(customer=customer, state=state, is_test=test)
            InvoiceLine.objects.create(invoice=invoice, product_id=pid, variant_id=pid, qty=qty, price=1)

    def test_best_seller_and_counts(self):
        best = self.client.get("/api/admin/v1/Products/TopSelling").json()["data"]["result"]
        self.assertEqual((best["productId"], best["totalOrders"]), (1, 3))
        labels = self.client.get("/api/admin/v1/Report/GetDashboardLablesReports").json()["data"]["result"]
        self.assertEqual((labels["totalInvoices"], labels["totalCustomers"]), (2, 1))


class ImportNewOrdersTests(TestCase):
    def test_only_new_orders_are_added_and_the_sites_own_are_skipped(self):
        from .management.commands import import_dadehfa_orders as importer
        customer = Customer.objects.create(id=5, cellphone="09120000005", first_name="سایت")
        Invoice.objects.create(id=1, customer=customer, state=3, description="already here")
        statements = []

        def rows(sql, params=None, chunk=2000):
            statements.append(sql)
            if "FROM Customers" in sql:
                return iter([{"Id": 5, "CellPhone": "09120000005", "FirstName": "قدیمی", "LastName": "", "Email": None, "NationalCode": None,
                              "BirthDate": None, "JobId": None, "IsActive": True, "IsBulletinEnable": False,
                              "BulletinSubscriptionDate": None, "MapId": None, "IsDeleted": False, "Created": None, "LastModified": None,
                              "ErpCustomerId": None}])
            if "FROM Invoices" in sql:
                base = {"CustomerId": 5, "CustomerAddressId": None, "InvoiceType": 3, "ShippingMethodId": None, "Amount": 1,
                        "ReductionAmount": 0, "DeliveryAmount": 0, "DeductionAmount": 0, "PayableAmount": 1, "Description": "",
                        "GiftCardId": None, "CouponId": None, "Reduction": 0, "LastModified": None, "MapId": None,
                        "IsDeleted": False, "Created": timezone.now()}
                return iter([{**base, "Id": 1, "Description": "changed there"}, {**base, "Id": 2}])
            return iter([])

        command = importer.Command(stdout=io.StringIO())
        with mock.patch.object(importer, "iter_rows", side_effect=rows), mock.patch.object(importer, "fetch_all", return_value=[]):
            command.handle(new=True)
        self.assertEqual(command.new_invoices, 1)
        self.assertEqual(Invoice.objects.get(id=1).description, "already here")
        self.assertTrue(Invoice.objects.filter(id=2).exists())
        self.assertEqual(Customer.objects.get(id=5).first_name, "سایت")
        self.assertIn("'site:'", next(sql for sql in statements if "FROM Invoices" in sql))


class ListingFixTests(TestCase):
    """Bug list (Nov 2026): out-of-stock last, the size filter, related products, the card's photo."""

    def setUp(self):
        Category.objects.create(id=1, title="بالاتنه", slug="top", is_online_active=True)
        Category.objects.create(id=2, title="کراپ", slug="crop", parent_id=1, is_online_active=True)
        for pid, cat, qty in ((1, 2, 0), (2, 2, 3), (3, 1, 3), (4, 1, 3)):
            Product.objects.create(id=pid, title=f"p{pid}", slug=f"p{pid}", category_id=cat, is_active=True)
            goods(pid=pid, vid=10 + pid, qty=qty, ref=900 + pid)
        ProductVariant.objects.filter(id=14).update(size_id=8, size_name="40")
        # clear_caches only marks the listing stale (the next read still answers with the last one): drop it.
        for drop in (catalog.clear_caches, lambda: warm.drop(catalog.LISTING_CACHE_KEY)):
            drop()
            self.addCleanup(drop)
        self.client = APIClient()

    def ids(self, payload):
        return [r.id for r in catalog.filter_rows(payload)]

    def test_out_of_stock_comes_last_whatever_the_sort(self):
        for sort in (2, 4, 5):
            self.assertEqual(self.ids({"sortCriteriaId": sort})[-1], 1, sort)
        self.assertNotIn(1, self.ids({"isInStock": True}))

    def test_search_reads_the_name_the_ai_title_and_the_slug_word_by_word(self):
        from apps.website.models import ProductAIProfile

        Product.objects.filter(id=2).update(title="كتي عروسكي اوديسه")
        ProductAIProfile.objects.create(product_id=2, title="مانتو کتی زنانه مدل اودیسه با یقه انگلیسی")
        Product.objects.filter(id=3).update(slug="شلوار-فوتر-جناقی-زنانه")
        warm.drop(catalog.LISTING_CACHE_KEY)
        self.assertEqual(self.ids({"search": "کتی عروسکی"}), [2])  # the name, typed with Persian letters
        self.assertEqual(self.ids({"search": "مانتو  یقه انگلیسی"}), [2])  # the AI title, words apart
        self.assertEqual(self.ids({"search": "فوتر جناقی"}), [3])  # the slug
        self.assertEqual(self.ids({"search": "مانتو فوتر"}), [])

    def test_the_two_dropped_sorts_are_not_offered(self):
        offered = {s["id"] for s in catalog.SORT_CRITERIA}
        self.assertFalse(offered & {6, 7})
        self.assertIn(2, offered)

    def test_size_filter_offers_and_matches_sizes_in_stock(self):
        reply = self.client.get("/api/v1/Product/GetFilterByCategoryId?id=1").json()["result"]["data"]
        sizes = {v["name"]: v["id"] for v in reply["filteredValues"] if not v["hasColor"]}
        self.assertEqual(set(sizes), {"38", "40"})  # p1's 38 is out of stock, the others have it
        self.assertEqual(sorted(self.ids({"filteredFeatureId": [sizes["40"]]})), [4])
        self.assertEqual(sorted(self.ids({"filteredFeatureId": [sizes["38"], sizes["40"]]})), [2, 3, 4])
        # with a color too: both must match
        self.assertEqual(sorted(self.ids({"filteredFeatureId": [sizes["40"], 6]})), [4])

    def suggest(self, body):
        reply = self.client.post("/api/v1/Product/SuggestProduct", body, format="json")
        return [p["id"] for p in reply.json()["result"]["data"]]

    def test_related_leaves_out_the_basket_and_tops_up_from_the_parent(self):
        # Category 2 has only p1 (out of stock) and p2: the rest comes from category 1.
        self.assertEqual(self.suggest({"categoryId": 2, "productId": 2}), [3, 4])
        self.assertEqual(self.suggest({"categoryId": 2, "excludeIds": [4], "excludeVariantIds": [13]}), [2])


class CardPhotoTests(TestCase):
    def setUp(self):
        Category.objects.create(id=1, title="ک", slug="k", is_online_active=True)
        Product.objects.create(id=1, title="پ", slug="p", category_id=1, is_active=True)
        goods(qty=3)
        ProductVariant.objects.create(id=12, product_id=1, barcode="b2", color_id=9, color_name="کرم", size_id=7, size_name="38")
        catalog.clear_caches()
        self.addCleanup(catalog.clear_caches)

    def photos(self, color_id, *names):
        for i, name in enumerate(names):
            LebazaiImage.objects.create(product_id=1, color_id=color_id, key=f"{color_id}{name}",
                                        source_url=f"http://x/Mong/1/{name}.png", position=i)

    def cover(self):
        bundle = catalog.ProductBundle.load([1])
        first = bundle.main_images(1)[0]["id"]
        return LebazaiImage.objects.get(id=first).source_url.rsplit("/", 1)[-1]

    def test_a_model_from_the_front_in_any_color_before_a_back_or_ghost_photo(self):
        self.photos(6, "back_temp1_1", "front_ghost_1")
        self.photos(9, "back_temp1_2", "front_temp1_2")
        self.assertEqual(self.cover(), "front_temp1_2.png")

    def test_a_ghost_photo_when_no_color_has_a_model_from_the_front(self):
        self.photos(6, "back_temp1_1", "front_ghost_1")
        self.assertEqual(self.cover(), "front_ghost_1.png")

    def test_each_color_opens_on_its_best_photo(self):
        self.photos(6, "back_temp1_1", "front_temp1_1")
        bundle = catalog.ProductBundle.load([1])
        first = bundle.color_images(1, bundle.variants[1][0])[0]["id"]
        self.assertTrue(LebazaiImage.objects.get(id=first).source_url.endswith("front_temp1_1.png"))

    def test_the_admin_lists_a_color_without_photos_that_the_site_leaves_out(self):
        from apps.adminapi.models import AdminUser
        from apps.website.models import SiteSetting

        SiteSetting.objects.create(min_qty=0, only_has_media_products=True)
        self.photos(6, "front_temp1_1")  # کرم (9) has no photo
        site = catalog.ProductBundle.load([1])
        self.assertEqual([v.color_id for v in site.visible_variants(1)], [6])

        client = APIClient()
        client.force_authenticate(AdminUser.objects.create(username="a", cellphone="09000000000"))
        reply = client.get("/api/admin/v1/Products/GetDetailProduct/1").json()["data"]["result"]
        colors = {c["id"]: c["images"] for c in reply["details"][0]["items"]}
        self.assertEqual(set(colors), {6, 9})
        self.assertEqual(colors[9], [])


class ProductSpecsTests(TestCase):
    """The «مشخصات محصول» table (erp/specs.py, catalog.product_specs)."""

    OLD = "%23سبک%0a%20regular%23فصل%0a%204052%23گروه%0a%20casual (روزمره)%23رده سني%0a%20جوان(بين 18 تا35)%23قواره%0a%20Short"

    def test_the_old_sites_labels_are_read_for_what_they_hold(self):
        from apps.erp import specs

        self.assertEqual(specs.dadehfa(self.OLD, "4052", "regular"), {
            "فصل کالا": "پاییز و زمستان", "قواره": "رگولار", "گروه قد": "کوتاه", "سبک": "کژوال (روزمره)"})

    def test_the_season_code_names_the_collection(self):
        from apps.erp import specs

        self.assertEqual([specs.season(c) for c in ("4051", "9902", "4034", "983", "", "پاییز و زمستان")],
                         ["بهار و تابستان", "پاییز و زمستان", "چهارفصل", "نوروز", "", "پاییز و زمستان"])

    def test_the_sales_software_first_then_the_ai_profile(self):
        from apps.website.models import ProductAIProfile

        Category.objects.create(id=1, title="ک", slug="k", is_online_active=True)
        p = Product.objects.create(id=1, title="پ", slug="p", category_id=1, is_active=True,
                                   attributes={"جنس": "موهر", "قواره": "رگولار"}, product_season_title="")
        ai = ProductAIProfile.objects.create(product=p, attributes={
            "season_fa": "چهارفصل", "fit_fa": "آزاد", "length": "cropped", "styles_fa": ["کلاسیک", "مدرن / ترند"]})
        self.assertEqual(catalog.product_specs(p, ai), [
            {"label": "جنس", "value": "موهر"}, {"label": "فصل کالا", "value": "چهارفصل"},
            {"label": "قواره", "value": "رگولار"}, {"label": "گروه قد", "value": "کراپ"},
            {"label": "سبک", "value": "کلاسیک، مدرن / ترند"}])

    def test_a_product_not_synced_yet_reads_the_imported_columns(self):
        Category.objects.create(id=1, title="ک", slug="k", is_online_active=True)
        p = Product.objects.create(id=1, title="پ", slug="p", category_id=1, is_active=True, short_desc=self.OLD,
                                   product_season_title="4052", product_style_title="regular")
        self.assertEqual([s["label"] for s in catalog.product_specs(p, None)], ["فصل کالا", "قواره", "گروه قد", "سبک"])

    def test_the_selling_points_go_to_the_keywords_not_the_page(self):
        from apps.website.models import ProductAIProfile

        Category.objects.create(id=1, title="ک", slug="k", is_online_active=True)
        Product.objects.create(id=1, title="پ", slug="p", category_id=1, is_active=True)
        goods(qty=3)
        ProductAIProfile.objects.create(product_id=1, search_keywords=["مانتو کتی", "مانتو اداری"],
                                        summary_bullets=["یقه انگلیسی شیک", "مانتو کتی"])
        reply = APIClient().get("/api/v1/SearchEngine/product/p/meta").json()
        meta = reply.get("result", {}).get("data", reply) if isinstance(reply, dict) else reply
        self.assertEqual(meta["keywords"], "مانتو کتی, مانتو اداری, یقه انگلیسی شیک")


class CooperationOtpTests(TestCase):
    url = "/api/v1/Cooperation/CooperationRequestSubmit"
    form = {"FirstName": "مریم", "LastName": "احمدی", "CellPhone": "09121112233", "JobPositionTitle": "فروشنده"}

    def setUp(self):
        from django.contrib.auth.hashers import make_password
        from apps.website.models import CustomerOtp

        CustomerOtp.objects.create(cellphone="09121112233", code_hash=make_password("1234"),
                                   expires=timezone.now() + timedelta(minutes=5))
        self.client = APIClient()

    def send(self, **extra):
        from django.core.files.uploadedfile import SimpleUploadedFile

        with tempfile.TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=folder):
            resume = SimpleUploadedFile("cv.pdf", b"%PDF-1.4", content_type="application/pdf")
            return self.client.post(self.url, {**self.form, "ResumeFile": resume, **extra}, format="multipart")

    def test_an_applicant_who_is_not_a_customer_is_checked_by_the_code(self):
        from apps.website.models import CooperationRequest

        self.assertEqual(self.send().status_code, 403)
        self.assertEqual(self.send(OtpCode="9999").status_code, 404)
        reply = self.send(OtpCode="1234")
        self.assertEqual(reply.status_code, 200)
        self.assertTrue(reply.json()["result"]["data"]["resumeFileUploaded"])
        self.assertEqual(CooperationRequest.objects.count(), 1)
        self.assertEqual(self.send(OtpCode="1234").status_code, 404)  # a code works once

    def test_a_customer_signed_in_with_that_number_needs_no_code(self):
        from apps.storefront.account import issue_token

        customer = Customer.objects.create(first_name="م", cellphone="09121112233")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_token(customer)['token']}")
        self.assertEqual(self.send().status_code, 200)
        other = Customer.objects.create(first_name="ن", cellphone="09120000001")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_token(other)['token']}")
        self.assertEqual(self.send().status_code, 403)


class ContactConfigMigrationTests(TestCase):
    def run_it(self):
        import importlib
        from django.apps import apps as django_apps

        importlib.import_module("apps.website.migrations.0030_contact_us_config_key").copy_forward(django_apps, None)

    def test_what_the_admin_form_saved_moves_to_the_key_the_site_reads(self):
        import json
        from apps.website.models import PrimaryConfig

        PrimaryConfig.objects.create(key="contactUsConfig2", value=json.dumps({"lat": "36.29", "address": "مشهد", "enabled": True}))
        PrimaryConfig.objects.create(key="contactUsConfig", value=json.dumps({"lat": 35.7, "lng": 51.4, "address": "تهران"}))
        self.run_it()
        value = json.loads(PrimaryConfig.objects.get(key="contactUsConfig2").value)
        self.assertEqual((value["lat"], value["address"], value["enabled"]), (35.7, "تهران", True))

    def test_the_legacy_shape_is_left_alone(self):
        import json
        from apps.website.models import PrimaryConfig

        PrimaryConfig.objects.create(key="contactUsConfig2", value=json.dumps({"lat": "36.29"}))
        PrimaryConfig.objects.create(key="contactUsConfig", value=json.dumps({"location": "{'lat': 1}", "address": "x"}))
        self.run_it()
        self.assertEqual(json.loads(PrimaryConfig.objects.get(key="contactUsConfig2").value), {"lat": "36.29"})
