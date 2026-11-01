# فصل ۷: سایت مستقل با دو رابط

سایت، پنل، ورود، سبد و پرداخت همه در جنگو هستند و به هیچ نرم‌افزاری وابسته نیستند. نرم‌افزار فروش فقط از یک رابط وصل است و `ERP_CONNECTOR` یکی از دو رابط را انتخاب می‌کند.

```text
مشتری و پنل ─► فرانت (dadeh.mong.ir) ─► جنگو (api.dadeh.mong.ir) ─► PostgreSQL
                                          │
                     ┌── رابط داده‌فا ────┤
                     │                    └── رابط سامیان: جدول‌های samian.*
                     ▼
        DadehfaOnlineShop: خواندن کالا، نوشتن فاکتور
                     ▲
       جاب‌های .NET: موجودی و کالا از PTC، فاکتور به PTC
```

| کار | سامیان | داده‌فا |
|---|---|---|
| خواندن | `sync_samian_erp` و بعد از آن `sync_erp` | `sync_erp` با SELECT |
| ثبت فاکتور | هنوز ساخته نشده است | `erp_outbox` در `DadehfaOnlineShop` |
| کوپن و کارت هدیه | غیرفعال | از همان دیتابیس |
| موجودی | انبارهای آنلاین شعب | همهٔ انبارها |

کد در `apps/erp` است. فروشگاه و پنل فقط جدول‌های `erp.*` را می‌خوانند و هر رابط همان‌ها را پر می‌کند.

**تا وقتی سایت روی رابط داده‌فا است، سرویس `.NET` باید روشن بماند**، چون جاب‌های آن فاکتورها را به PTC می‌برند و موجودی را برمی‌گردانند. خود سایت هیچ درخواستی به `.NET` نمی‌فرستد.

## نوشتن فاکتور

- فاکتور پرداخت‌شده در صف می‌ماند تا `erp_outbox` آن را با `InvoiceType=3` و `MapId` خالی بنویسد. جاب ساعتی `SyncInvoices` آن را به PTC می‌برد.
- **`ERP_WRITES_ENABLED` پیش‌فرض خاموش است.** تا روشن نشود چیزی نوشته نمی‌شود و سفارش‌ها در سایت می‌مانند.
- نوشتن لاگین جدا دارد و اگر `sysadmin` باشد رد می‌شود. فقط دستورهای فهرست `apps/erp/dadehfa_write.py` اجرا می‌شوند.
- شمارهٔ سایت در `CreatedBy` می‌ماند، پس تکرار ارسال فاکتور را دوباره نمی‌نویسد.
- خطای ارسال در `Invoice.erp_error` می‌ماند و ارسال دقیقهٔ بعد تکرار می‌شود.
- کالای فروخته‌شده تا ۱۵ دقیقه بعد از رسیدن فاکتور به PTC از موجودی کم می‌ماند، تا آخرین عدد دو بار فروخته نشود.
- پیامک مشتری را رویهٔ PTC می‌فرستد و پیامک مدیران را جنگو.

فاکتور PTC با تأخیر تا یک ساعت ساخته می‌شود. روی سایت قدیم، `.NET` همان لحظه جاب را صدا می‌زد.

ردیف‌های ساخته‌شده با ۳۱۳ فاکتور پرداخت‌شدهٔ واقعی، فیلد به فیلد مقایسه شده‌اند: ۲۹۳ فاکتور یکسان بودند و بقیه فاکتورهای قدیمی هستند.

## نصب روی Runflare

سرویس‌ها همان `dadeh`، `dadeh-front` و `mong` هستند. **سرویس `shop` دست نمی‌خورد.**

1. روی SQL Server فایل `deploy/runflare/dadehfa_logins.sql` را با رمزهای خودتان اجرا کنید و پورت را فقط برای IP خروجی رانفلر باز کنید.
2. بسته‌ها را بسازید: `bash deploy/runflare/make_zips.sh`. خروجی در `dist/runflare` است.
3. متغیرهای `dadeh` را از `dist/runflare/backend.env` وارد کنید و `backend.zip` را آپلود کنید. `ERP_WRITES_ENABLED` را `false` بگذارید.
4. در ترمینال `dadeh` به همین ترتیب اجرا کنید:

```bash
python manage.py migrate
python manage.py import_dadehfa
python manage.py import_dadehfa --only banks
python manage.py import_dadehfa --only blog
python manage.py import_dadehfa --only cooperation
python manage.py import_dadehfa_admins
python manage.py import_dadehfa_orders
python manage.py install_media /app/public/media_pack.zip
python manage.py sync_erp --full
```

5. خط‌های `deploy/runflare/crontab.txt` را در کران‌جاب `dadeh` بگذارید.
6. متغیرهای `dadeh-front` را از `dist/runflare/frontend.env` وارد کنید و `frontend.zip` را آپلود کنید.

بستهٔ رسانه همان فایل قبلی است و لازم نیست دوباره ساخته شود. فرانت و کران قبلی با این نسخه جایگزین می‌شوند.

## متغیرهای `dadeh`

| نام | مقدار |
|---|---|
| `ERP_CONNECTOR` | `dadehfa` |
| `ERP_WRITES_ENABLED` | `false` تا تست خرید |
| `SITE_URL` | `https://dadeh.mong.ir` |
| `PUBLIC_BASE_URL`، `PUBLIC_MEDIA_BASE_URL`، `PAYHUB_PUBLIC_URL` | `https://api.dadeh.mong.ir` |
| `MEDIA_ROOT` | `/app/public/media` |
| `LEGACY_CDN_ROOT` | `/app/public/media/cdn` |
| `DADEHFA_DB_USER`، `DADEHFA_DB_PASSWORD` | لاگین `mong_reader` |
| `DADEHFA_WRITE_DB_USER`، `DADEHFA_WRITE_DB_PASSWORD` | لاگین `mong_writer` |
| `SMS_KEY` | کلید sms.ir برای کد ورود |
| `ZARINPAL_KEY` | مرچنت زرین‌پال |

بقیهٔ متغیرها مثل قبل می‌مانند. تا وقتی متغیرهای `SNAPPAY_*` خالی باشند اسنپ‌پی نشان داده نمی‌شود و درخواستی به آن نمی‌رود.

## متغیرهای `dadeh-front`

| نام | مقدار |
|---|---|
| `SITE_URL` | `https://dadeh.mong.ir` |
| `API_ORIGIN` | `https://api.dadeh.mong.ir` |
| `SITE_NOINDEX` | `true` برای مخفی ماندن از گوگل، `false` برای سنجش واقعی یا سوییچ |

## تست پیش از سوییچ

1. ورود با کد پیامکی، ساخت سبد و دیدن تاریخچهٔ یک مشتری قدیمی را امتحان کنید.
2. با `ERP_WRITES_ENABLED=false` یک خرید کم‌مبلغ با زرین‌پال انجام دهید. سفارش باید در پنل جنگو دیده شود و در `.NET` نه. مبلغ این خرید واقعی است و باید دستی ثبت یا برگشت داده شود.
3. به انبار خبر بدهید، `ERP_WRITES_ENABLED=true` کنید و سرویس را ری‌استارت کنید. `erp_outbox` همان سفارش را می‌نویسد.
4. در پنل قدیم فاکتور باید با وضعیت پرداخت‌شده دیده شود و بعد از جاب ساعتی `MapId` بگیرد و در PTC بیاید.
5. بعد از آن `erp_taken_at` سفارش پر می‌شود و کوپن یا کارت هدیه را هم با یک خرید دیگر امتحان کنید.

## سوییچ به `mong.ir`

1. درست پیش از سوییچ `python manage.py import_dadehfa_orders` را دوباره اجرا کنید تا مشتری‌ها و سفارش‌های تازه هم بیایند.
2. در `dadeh-front`: `SITE_URL=https://mong.ir` و `SITE_NOINDEX=false`، سپس build دوباره.
3. در `dadeh`: `SITE_URL=https://mong.ir`.
4. دامنهٔ `mong.ir` را از `shop` بردارید و به `dadeh-front` بدهید.
5. `.NET` و جاب‌هایش را خاموش نکنید.

راه برگشت: دامنهٔ `mong.ir` را به `shop` برگردانید. سفارش‌های نوشته‌شده در `DadehfaOnlineShop` در پنل قدیم هستند.

## سوییچ به سامیان

1. فرستادن فاکتور به سامیان در `SamianConnector.push` ساخته می‌شود.
2. `ERP_CONNECTOR=samian` می‌شود و کران‌های `crontab.txt` جای کران داده‌فا را می‌گیرند.
3. سبدهای باز به‌خاطر تفاوت شناسهٔ تنوع‌ها خالی می‌شوند. تاریخچهٔ سفارش‌ها می‌ماند.
