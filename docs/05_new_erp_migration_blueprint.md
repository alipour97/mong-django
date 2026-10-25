# فصل ۵: راهنمای گام‌به‌گام پیاده‌سازی بک‌اند جنگو و اتصال به ERP جدید

این سند نقشه راه عملیاتی برای تیم فنی جهت توسعه بک‌اند جدید در پایتون/جنگو و اجرای موازی با سیستم فعلی بدون خوابیدن سایت اصلی است.

---

## ۱. ساختار پیشنهادی پروژه جنگو (Django Apps Structure)

برای اینکه کدها دقیقاً با ۳ ماژول تشریح‌شده در مستندات تطابق داشته باشند، معماری ماژولار زیر پیشنهاد می‌شود:

```text
mong_backend/
├── config/                  # تنظیمات اصلی جنگو (settings, wsgi, asgi, urls)
├── apps/
│   ├── authentication/      # کاربران، لاگین با پیامک (OTP)، توکن JWT (SimpleJWT)
│   ├── catalog/             # کالاها، تنوع‌ها (رنگ و سایز)، دسته‌بندی‌ها، کالکشن‌ها
│   ├── orders/              # سبد خرید، فاکتور، روش‌های ارسال، کوپن و کارت هدیه
│   ├── payments/            # درگاه‌های پرداخت (زرین‌پال، اسنپ‌پی، سداد) و تایید تراکنش
│   ├── interactions/        # نظرات محصولات، مقالات وبلاگ، فرم‌های همکاری
│   ├── partner/             # ماژول ۳ (فید ترب، وب‌هوک شاپینو و اسنپ‌پی)
│   └── erp_integration/     # سرویس رابط با APIهای نرم‌افزار حسابداری جدید
└── tasks/                   # جاب‌های زمان‌بندی‌شده Celery (سینک دوره‌ای موجودی و قیمت)
```

---

## ۲. نگاشت مدل‌های داده‌ای (Data Modeling)

### ۲.۱. مدل کاتالوگ پوشاک و تنوع‌ها (Catalog & Variants)
پوشاک منگ مبتنی بر سیستم ماتریسی است. در جنگو مدل‌ها به شکل زیر تعریف می‌شوند:

```python
# apps/catalog/models.py
from django.db import models

class Product(models.Model):
    erp_id = models.CharField(max_length=64, unique=True, db_index=True)  # کد کالا در نرم‌افزار جدید
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, allow_unicode=True)
    category = models.ForeignKey('Category', on_delete=models.CASCADE, related_name='products')
    base_price = models.DecimalField(max_digits=12, decimal_places=0)      # قیمت ریالی
    base_discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    short_description = models.TextField(blank=True)
    long_description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    erp_variant_id = models.CharField(max_length=64, unique=True, db_index=True) # بارکد / شناسه تنوع در ERP
    color_name = models.CharField(max_length=64)     # مثال: صورتی
    color_hex = models.CharField(max_length=16)      # مثال: #FFC0CB
    size_name = models.CharField(max_length=32)      # مثال: 38 یا FreeSize
    price = models.DecimalField(max_digits=12, decimal_places=0)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    stock = models.PositiveIntegerField(default=0)   # موجودی لحظه‌ای انبار
    barcode = models.CharField(max_length=64, blank=True, db_index=True)
```

### ۲.۲. مدل سفارش و فاکتور (Invoice & Orders)
```python
# apps/orders/models.py
class Invoice(models.Model):
    STATUS_CHOICES = [
        ('pending', 'در انتظار پرداخت'),
        ('paid', 'پرداخت شده'),
        ('processing', 'در حال پردازش'),
        ('shipped', 'ارسال شده'),
        ('canceled', 'لغو شده'),
    ]
    customer = models.ForeignKey('authentication.Customer', on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    total_amount = models.DecimalField(max_digits=12, decimal_places=0)
    payable_amount = models.DecimalField(max_digits=12, decimal_places=0)
    shipping_method = models.ForeignKey('ShippingMethod', on_delete=models.PROTECT)
    shipping_cost = models.DecimalField(max_digits=10, decimal_places=0, default=0)
    address_snapshot = models.JSONField() # ذخیره متن کامل آدرس در زمان ثبت
    erp_invoice_id = models.CharField(max_length=64, null=True, blank=True) # کد پیگیری در نرم‌افزار حسابداری
    created_at = models.DateTimeField(auto_now_add=True)
```

---

## ۳. فرآیند همگام‌سازی با ERP جدید (Sync Pipeline)

### سناریوی الف: دریافت تغییرات موجودی و قیمت از ERP
به جای روش سنگین قبلی (اتصال مستقیم به دیتابیس PTC)، با یک Task در Celery انجام می‌شود:

```python
# tasks/sync_tasks.py
from celery import shared_task
from apps.erp_integration.client import NewErpApiClient
from apps.catalog.models import ProductVariant

@shared_task
def sync_stock_and_prices_from_erp():
    erp = NewErpApiClient()
    # دریافت لیست کالاهایی که در ۵ دقیقه اخیر تغییر موجودی یا قیمت داشتند
    updates = erp.get_stock_and_price_updates(since_minutes=5)
    
    for item in updates:
        ProductVariant.objects.filter(erp_variant_id=item['variant_id']).update(
            stock=item['available_stock'],
            price=item['price'],
            discount_percent=item.get('discount', 0)
        )
```

### سناریوی ب: ثبت فاکتور در ERP پس از تایید بانک
بلافاصله در متد `PaymentVerification`:
```python
# apps/payments/services.py
def finalize_order(invoice, bank_tracking_code):
    # ۱. تغییر وضعیت فاکتور به پرداخت شده
    invoice.status = 'paid'
    invoice.save()
    
    # ۲. ارسال سفارش به API نرم‌افزار حسابداری جدید
    erp = NewErpApiClient()
    erp_response = erp.create_sales_invoice({
        'customer_mobile': invoice.customer.cellphone,
        'customer_name': invoice.customer.get_full_name(),
        'items': [
            {'variant_id': item.variant.erp_variant_id, 'qty': item.qty, 'unit_price': item.price}
            for item in invoice.items.all()
        ],
        'bank_reference_id': bank_tracking_code,
        'shipping_amount': invoice.shipping_cost,
        'description': f"خرید آنلاین از سایت منگ - شناسه وب: {invoice.id}"
    })
    
    # ۳. ذخیره کد فاکتور رسمی صادر شده در ERP
    invoice.erp_invoice_id = erp_response['invoice_number']
    invoice.save()
```

---

## ۴. چک‌لیست راه‌اندازی موازی (Step-by-Step Staging Setup)

1. **کپی فرانت‌اند:**
   * پوشه `mong_front` را در کنار دایرکتوری جدید کپی کنید.
   * فایل `.env` آن را باز کرده و آدرس‌های API را به سرور تست جنگو تغییر دهید:
     ```env
     NEXT_PUBLIC_PO_MONG="https://stage-api.mong.ir/api/v1"
     NEXT_PUBLIC_ADMIN_PO_MONG="https://stage-adminapi.mong.ir/api/v1"
     ```
2. **اجرای لوکال فرانت:**
   ```bash
   cd mong_front
   npm install
   npm run dev
   ```
3. **تست اندپوینت به اندپوینت با ابزار Swagger / Postman:**
   * لیست کالاها، صفحه محصول، انتخاب رنگ/سایز، اضافه به سبد خرید، لاگین با پیامک.
4. **تست درگاه پرداخت در محیط SandBox:**
   * ایجاد یک پرداخت آزمایشی با زرین‌پال تستی یا درگاه شبیه‌ساز و بررسی ثبت رکورد در نرم‌افزار جدید.
5. **سوییچ نهایی به لایو (Go-Live):**
   * تغییر مسیر روت وب‌سرور (Nginx/IIS) از پروژه قبلی به خروجی `mong_front` و جنگو.
