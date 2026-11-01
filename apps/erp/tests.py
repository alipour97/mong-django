from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.storefront import catalog
from apps.website.models import (
    Category, Customer, CustomerAddress, Invoice, InvoiceLine, InvoicePayment, Product, SiteSetting,
)

from . import dadehfa, dadehfa_write as write, outbox, store
from .connector import Connector, Coupon, GiftCard, Refused, SourceError
from .dadehfa import DadehfaConnector
from .management.commands.import_dadehfa_orders import Command as ImportOrders
from .models import ErpImage, ErpProduct, ErpStock, ErpVariant, LebazaiImage


def use_dadehfa(case: TestCase) -> None:
    patcher = mock.patch("apps.erp.store.get_connector", return_value=DadehfaConnector())
    patcher.start()
    case.addCleanup(patcher.stop)


def goods(pid=1, vid=11, qty=5, ref=901) -> ErpVariant:
    ErpProduct.objects.create(product_id=pid, erp_id=pid, base_price=1000000, sale_price=1000000, synced_at=timezone.now())
    variant = ErpVariant.objects.create(id=vid, product_id=pid, erp_ref=ref, barcode="b1", color_id=6, color_name="مشکی", size_id=7, size_name="38")
    ErpStock.objects.create(variant=variant, warehouse_id=1, qty=qty)
    return variant


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
            store.replace(store.Read())
        self.assertEqual(ErpProduct.objects.count(), 1)

    def fresh_read(self, qty=5) -> store.Read:
        now = timezone.now()
        return store.Read(
            products=[ErpProduct(product_id=1, erp_id=1, synced_at=now)], variants=[ErpVariant(id=11, product_id=1)],
            stock=[ErpStock(variant_id=11, warehouse_id=1, qty=qty)])

    def test_a_paid_order_stays_held_until_the_software_has_it(self):
        customer = Customer.objects.create(cellphone="09121111111")
        order(customer)
        store.replace(self.fresh_read())
        self.assertEqual(ErpStock.objects.get().qty, 3)

    def test_a_settled_order_is_no_longer_held(self):
        customer = Customer.objects.create(cellphone="09121111111")
        order(customer, erp_taken_at=timezone.now() - timedelta(hours=1))
        store.replace(self.fresh_read())
        self.assertEqual(ErpStock.objects.get().qty, 5)

    def test_a_just_taken_order_is_held_a_little_longer(self):
        customer = Customer.objects.create(cellphone="09121111111")
        order(customer, erp_taken_at=timezone.now())
        store.replace(self.fresh_read())
        self.assertEqual(ErpStock.objects.get().qty, 3)

    def test_a_cart_holds_nothing(self):
        customer = Customer.objects.create(cellphone="09121111111")
        order(customer, state=Invoice.State.PRE_INVOICE)
        store.replace(self.fresh_read())
        self.assertEqual(ErpStock.objects.get().qty, 5)


class ReadTests(TestCase):
    def rows(self, sql, params=None):
        if "VariantWarehouses" in sql:
            return [{"vid": 50, "warehouse": 2, "title": "انبار", "qty": Decimal("4")}]
        if "Products p" in sql and "p.Barcode" in sql:
            return [{"Id": 5, "Barcode": "00500", "Price": Decimal("26800000"), "Reduction": Decimal("62.724"), "SalesCount": 3}]
        if "FROM FeatureValues" in sql:
            return [{"Id": 6, "Name": "مشکی", "Value": "000000", "DisplayPriority": 1}, {"Id": 7, "Name": "38", "Value": "38", "DisplayPriority": 2}]
        if "FROM ProductVariants v" in sql:
            base = {"pid": 5, "vid": 50, "barcode": " b ", "color": 6, "size": 7}
            return [{**base, "ref": 900}, {**base, "ref": 901}]
        if "FeatureValueMedias f" in sql:
            return [{"Id": 2, "ProductId": 5, "FeatureValueId": 6, "MediaUrl": "https://cdn.mong.ir/9/g.webp", "IsVideo": 0, "Alternative": None, "TooltipTitle": None}]
        if "FROM MediaAttachments" in sql:
            return [{"Id": 1, "RecordId": 5, "MediaUrl": "https://cdn.mong.ir/9/m.webp", "IsVideo": 0, "Alternative": None, "TooltipTitle": None}]
        raise AssertionError(sql)

    def test_a_product_as_the_shop_shows_it(self):
        LebazaiImage.objects.create(product_id=5, color_id=6, key="lz/x", source_url="https://l/x.jpg")
        with mock.patch("apps.erp.dadehfa.fetch_all", side_effect=self.rows):
            read = dadehfa.read()
        product = read.products[0]
        self.assertEqual((product.base_price, product.sale_price, product.reduction), (26800000, 9990000, Decimal("62.724")))
        variant = read.variants[0]
        self.assertEqual((variant.erp_ref, variant.barcode, variant.color_family, variant.size_name), (901, "b", "مشکی", "38"))
        self.assertEqual(read.stock[0].qty, 4)
        order_shown = [(i.is_main, i.key) for i in read.images]
        self.assertEqual(order_shown, [(False, "lz/x"), (False, "c/9/g"), (True, "lz/x"), (True, "c/9/m")])

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
        ErpImage.objects.create(product_id=1, color_id=6, source="https://cdn.mong.ir/9/g.webp", position=0)
        ErpImage.objects.create(product_id=1, is_main=True, source="https://cdn.mong.ir/9/m.webp", position=1)

    def test_only_what_the_software_has_is_on_the_site(self):
        bundle = catalog.ProductBundle.load([1, 2])
        self.assertEqual(list(bundle.products), [1])

    def test_stock_less_what_is_kept_back(self):
        bundle = catalog.ProductBundle.load([1])
        self.assertEqual(bundle.variant_stock(1, bundle.variants[1][0]), 2)

    def test_the_product_gallery_comes_first_when_there_is_one(self):
        bundle = catalog.ProductBundle.load([1])
        self.assertTrue(bundle.main_images(1)[0]["mediaUrl"].endswith("m.webp"))
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
        banks = [p["BankId"] for s, p in self.db.statements if s.startswith("INSERT INTO InvoicePayments")]
        self.assertCountEqual(banks, [1, write.GIFT_CARD_BANK])
        self.assertTrue(any(s.startswith("UPDATE GiftCards") and p["d"] == 500000 for s, p in self.db.statements))
        self.assertEqual(self.db.row("Invoices")["GiftCardId"], 44)

    def test_a_general_coupon_gets_the_customers_own_copy(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(coupon_serial="S1")
        self.invoice.refresh_from_db()
        self.db = FakeDb({"FROM Coupons": {"ExpiredDate": None, "MinPrice": 0, "MaxPrice": None, "Reduction": 10, "MapId": "9"}})
        self.push()
        self.assertEqual(self.db.row("Coupons")["IsUsed"], 1)
        self.assertEqual(self.db.row("Invoices")["CouponId"], self.db.next_id - 3)

    def test_an_own_coupon_is_marked_used(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(coupon_serial="S1", coupon_id=77)
        self.invoice.refresh_from_db()
        self.push()
        self.assertTrue(any(s.startswith("UPDATE Coupons") and p["id"] == 77 for s, p in self.db.statements))

    def test_a_line_without_reference_stays_for_someone_to_look_at(self):
        self.invoice.lines.update(erp_ref=None)
        with self.assertRaises(write.CannotSend):
            self.push()

    def test_only_the_listed_statements_pass(self):
        for good in ("INSERT INTO Invoices (Amount) OUTPUT INSERTED.Id VALUES (:Amount)", "UPDATE Coupons SET IsUsed = 1 WHERE Id = :id",
                     "SELECT TOP 1 Id FROM Customers"):
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

    def test_no_writing_login_no_writing(self):
        write.get_engine.cache_clear()
        self.addCleanup(write.get_engine.cache_clear)
        with override_settings(DADEHFA_WRITE_DB_USER=""), self.assertRaises(write.CannotSend):
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


class VoucherConnector(Connector):
    def coupon(self, serial, customer):
        if serial != "OK":
            raise Refused("کوپن وجود ندارد.")
        return Coupon(id=9, serial=serial, reduction=Decimal(10), min_price=Decimal(1000), max_price=None, expires=None)

    def gift_card(self, number, customer):
        return GiftCard(id=4, number=number, balance=Decimal(5000000), min_price=Decimal(0), use_whole=False)

    def gift_cards(self, customer):
        now = timezone.now()
        return [{"GCNum": "G1", "StartDate": now, "ExpDate": None, "GCBalance": Decimal(5), "IsActive": True, "UseDepCode": False,
                 "MinFactorPrice": None, "UseCompelete": False}]


class VoucherTests(TestCase):
    def setUp(self):
        SiteSetting.objects.create(min_qty=0, only_has_media_products=False, coupon_calculation_type=2, gift_card_use_type=1)
        Category.objects.create(id=1, title="ک", slug="k", is_online_active=True)
        Product.objects.create(id=1, title="پ", slug="p", category_id=1, is_active=True)
        goods()
        ErpProduct.objects.filter(pk=1).update(reduction=10, sale_price=900000)
        catalog.clear_caches()
        self.addCleanup(catalog.clear_caches)
        self.customer = Customer.objects.create(first_name="ع", cellphone="09121234567")
        self.client = APIClient()
        self.client.force_authenticate(self.customer)
        for patcher in (mock.patch("apps.storefront.orders.get_connector", return_value=VoucherConnector()),
                        mock.patch("apps.storefront.catalog.listing_rows", return_value=[SimpleNamespace(id=1)])):
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
        self.assertEqual(ErpStock.objects.get(variant=variant).qty, 3)

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
