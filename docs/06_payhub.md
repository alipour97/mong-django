# فصل ۶: سرویس پرداخت واحد (`payhub.mong.ir`)

همهٔ پرداخت‌های هر دو سایت از یک سرویس رد می‌شوند: `apps/payhub`. درگاه‌های فعلی زرین‌پال و اسنپ‌پی هستند.

```text
سایت جدید ─ فراخوانی داخلی ─┐
                            ├─► apps/payhub ─► زرین‌پال
سایت قدیم ─ PayUrl ─────────┘              └► اسنپ‌پی
```

قرارداد HTTP دقیقاً همان Mong.Pay (`_src/Mong.Pay`) است که خودش جای هاب داده‌فا را گرفته بود. پس سایت قدیم برای وصل شدن فقط به عوض شدن `PayUrl` نیاز دارد. این سازگاری از روی کد Mong.Pay ساخته و با تست خودکار بررسی شده، ولی هنوز با خود سایت قدیم امتحان نشده است.

## مسیرها

| متد | مسیر | کار |
|---|---|---|
| POST | `/GenerateToken` | ساخت پرداخت؛ `{id, token, status, message}` |
| GET | `/GoToPayPage/{token}/{invoiceId}/{amount}` | زرین‌پال: انتقال مشتری به درگاه |
| POST | `/GetPaymentToken/{token}/{invoiceId}/{amount}` | اسنپ‌پی: توکن پرداخت و صفحهٔ پرداخت |
| GET، POST | `/zarinpal/callback/{token}` | بازگشت از زرین‌پال |
| GET، POST | `/api/SnappPay/CallBack/{id}/{token}` | `returnURL` اسنپ‌پی؛ verify همین‌جا و فقط یک بار انجام می‌شود |
| POST | `/PaymentVerification/{token}` | نهایی کردن (verify زرین‌پال یا settle اسنپ‌پی)؛ `ok` فقط یک بار |
| GET | `/CheckToken/{token}` | وضعیت پرداخت |
| POST | `/api/SnappPay/GetTokenByCompany/{id}` | توکن هاب برای چهار مسیر زیر |
| POST | `/api/SnappPay/EligibleWithAuth?amount=` | پاسخ خود اسنپ‌پی |
| POST | `/api/SnappPay/PaymentCancel`، `UpdatePayment`، `PaymentStatus` | برای پنل قدیم |
| GET | `/__health` | بررسی سلامت سرویس |

مسیرهای سرور به سرور فقط به `PAYHUB_ALLOWED_API_IPS` یا هدر `X-Mong-Hub-Key` (برابر با `PAYHUB_ACCEPT_KEY`) جواب می‌دهند. آدرس برگشت فقط روی هاست‌های `PAYHUB_ALLOWED_CALLBACK_HOSTS` پذیرفته می‌شود.

سایت جدید همین منطق را مستقیم از `apps.payhub.service` صدا می‌زند و بازگشتش `Bank/PaymentVerification` است.

## وضعیت پرداخت (`PayRecord`)

| وضعیت | معنی |
|---|---|
| `created` → `starting` → `redirected` | پرداخت ساخته شد و مشتری به درگاه رفت |
| `verifying` | اسنپ‌پی: مشتری برگشته و verify در جریان است |
| `returned` | مشتری برگشته (اسنپ‌پی: verify شده) و منتظر نهایی شدن است |
| `confirming` → `consumed` | نهایی شد و فقط یک بار به سایت تحویل شد |
| `failed`، `reverted` | ناموفق یا برگشت داده‌شده |
| `unknown` | پاسخ روشن نبود؛ بعد از ۴۰ دقیقه دوباره استعلام می‌شود |
| `review` | **باید کارشناس بررسی کند** (در `django-admin`، فهرست «پرداخت‌های هاب») |

`manage.py payhub_reconcile` هر ۵ دقیقه با cron اجرا می‌شود:

- پرداختی که verify شده ولی ۲۰ دقیقه نهایی نشده است، revert می‌شود.
- `unknown` بعد از ۴۰ دقیقه استعلام می‌شود.
- اگر اسنپ‌پی آن را خودش settle کرده باشد ولی سفارشی ثبت نشده باشد، به `review` می‌رود.

## لاگ اسنپ‌پی (`SnappLog`)

هر درخواست به اسنپ‌پی و پاسخ آن، موفق یا ناموفق یا بی‌پاسخ، در این جدول ثبت می‌شود و در ادمین جنگو با توکن پرداخت یا شناسه تراکنش پیدا می‌شود. رمز عبور و توکن دسترسی ذخیره نمی‌شوند. پاک‌سازی خودکار ندارد.

## تنظیمات `.env`

| نام | توضیح |
|---|---|
| `PAYHUB_PUBLIC_URL` | آدرس بازگشت هر دو درگاه: `https://payhub.mong.ir` |
| `PAYHUB_ACCEPT_KEY` | همان `SnappPayForward.Key` در Mong.Pay |
| `PAYHUB_ALLOWED_API_IPS` | IP سرور سایت قدیم، با کاما |
| `PAYHUB_ALLOWED_CALLBACK_HOSTS` | پیش‌فرض: `api.mong.ir,api.mongnew.ir` |
| `PAYHUB_OLD_HUB_URL` | فقط هنگام انتقال زرین‌پال: `https://zarinpal.mong.ir` |
| `SNAPPAY_BASE_URL` | آدرس پروداکشن؛ اگر خالی باشد `SNAPPAY_STAGE_URL` استفاده می‌شود |
| `SNAPPAY_COMMISSION_TYPE` | پیش‌فرض ۱۰۰ |
| `SNAPPAY_TRANSACTION_ID_START` | پیش‌فرض ۵۰۰۰۰۰۰۰ |
| `ZARINPAL_STARTPAY_BASE_URL` | پیش‌فرض `https://pay.mong.ir/pg/StartPay` |

**gunicorn باید با `--timeout 120` اجرا شود.** پیش‌فرض ۳۰ ثانیه است و verify اسنپ‌پی ممکن است تا ۹۰ ثانیه طول بکشد؛ در این صورت worker وسط پرداخت کشته می‌شود.

## راه‌اندازی

1. ابتدا `deploy/nginx/payhub.mong.ir.conf` نصب و SSL صادر می‌شود.
2. سپس `manage.py migrate payhub` اجرا و gunicorn با `--timeout 120` دوباره راه‌اندازی می‌شود.
3. خط `payhub_reconcile` از `crontab.txt` به cron اضافه می‌شود.
4. دامنهٔ ثبت‌شده نزد اسنپ‌پی باید `payhub.mong.ir` باشد.

## انتقال سایت قدیم

تا وقتی هر دو درگاه روی `samian.mong.ir` درست کار نکرده‌اند، سایت قدیم دست نمی‌خورد. بعد از آن:

1. **اسنپ‌پی:** `PayUrl` همان می‌ماند. در `appsettings.json` مربوط به Mong.Pay مقدار `SnappPayForward.Url` برابر `https://payhub.mong.ir` و `Key` برابر `PAYHUB_ACCEPT_KEY` می‌شود. زرین‌پال تغییری نمی‌کند.
2. **زرین‌پال:** `PAYHUB_OLD_HUB_URL=https://zarinpal.mong.ir` و `PAYHUB_ALLOWED_API_IPS` تنظیم می‌شود، بعد `PayUrl` در `appsettings.json` هر دو سرویس api و AdminApi به `https://payhub.mong.ir` تغییر می‌کند. Mong.Pay تا تمام شدن پرداخت‌های باز روشن می‌ماند.
