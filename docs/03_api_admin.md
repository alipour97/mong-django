# فصل ۳: مشخصات فنی API پنل مدیریت (`adminapi.mong.ir`)

این سند راهنمای کامل اندپوینت‌های مورد استفاده در بخش پنل مدیریت پروژه فرانت‌اند (`mong_front/src/app/(admin)/admin-panel-mong/`، آدرس `/admin-panel-mong`) است.

* **Base URL در فرانت‌اند:** `process.env.NEXT_PUBLIC_ADMIN_PO_MONG` (مثال: `https://adminapi.mong.ir/api/v1`)
* **مکانیزم احراز هویت:** JWT با ارسال هدر `Authorization: Bearer <adminToken>`. سیستم فرانت‌اند دارای اینترسپتور خودکار است که در صورت انقضای توکن، متد رفرش را صدا می‌زند.

---

## ۱. احراز هویت و کاربران پنل (Auth & Users)

### ۱.۱. ورود به پنل ادمین (Admin Login)
* **مسیر:** `POST /api/v1/Auth/login`
* **بدنه درخواست:**
  ```json
  {
    "username": "admin",
    "password": "StrongPassword123"
  }
  ```
* **پاسخ سرور:**
  ```json
  {
    "isSuccess": true,
    "data": {
      "token": "eyJhbGciOi...",
      "refreshToken": "ref_...",
      "expires": "2026-10-25T16:00:00Z"
    }
  }
  ```

### ۱.۲. تمدید توکن (Refresh Token)
* **مسیر:** `POST /api/v1/Auth/refresh`
* **بدنه درخواست:** رشته ساده یا JSON ریفرش توکن (`adminRefreshToken`).

### ۱.۳. آمار داشبورد در یک نگاه (Dashboard Stats)
* **تاریخ روز:** `GET /api/v1/Dashboard/Date`
* **نوتیفیکیشن‌های داشبورد:** `GET /api/v1/Dashboard/DashboardNotif`
* **وضعیت همگام‌سازی انبار:** `GET /api/v1/Dashboard/SynchronizationStatus`
* **نرخ رشد فروش:** `POST /api/v1/Dashboard/GrowthRate?month=7&year=1405&steps=5`

---

## ۲. مدیریت سفارشات و فاکتورها (Invoice Management)

### ۲.۱. فیلتر و جستجوی فاکتورها
* **مسیر:** `GET /api/v1/Invoice/GetFilteredInvoices`
* **پارامترهای Query:**
  * `pageNumber`, `pageSize`
  * `invoiceState`: وضعیت فاکتور (در انتظار، پرداخت شده، لغو شده، در حال بسته‌بندی، ارسال شده)
  * `fromDate`, `toDate`: بازه تاریخی ثبت
  * `customerCellphone`: فیلتر شماره موبایل خریدار
  * `ShippingMethodIds`: روش‌های ارسال انتخابی
* **پاسخ سرور:**
  ```json
  {
    "isSuccess": true,
    "data": {
      "items": [
        {
          "invoiceId": 9845,
          "customerFullName": "سارا احمدی",
          "customerMobile": "09121234567",
          "totalAmount": 15150000,
          "paymentState": "Paid",
          "shippingTitle": "پست پیشتاز",
          "createdDate": "1405/07/25 14:20",
          "traceNumber": "TR-9823412"
        }
      ],
      "totalCount": 1240
    }
  }
  ```

### ۲.۲. جزئیات فاکتور و چاپ
* **مشاهده کامل فاکتور و اقلام:** `GET /api/v1/Invoice/InvoiceDetails/{invoiceId}`
* **نسخه آماده چاپ (فیش انبار/ارسال):** `GET /api/v1/Invoice/InvoiceDetailsForPrint/{invoiceId}`
* **آمار تفکیکی فروش:**
  * `GET /api/v1/Invoice/DailyCounts?months=7&years=1405`
  * `GET /api/v1/Invoice/InvoiceCountByHour`
  * `GET /api/v1/Invoice/InvoiceAmountRange`

---

## ۳. مدیریت محصولات و کاتالوگ (Product Management)

### ۳.۱. لیست محصولات در پنل ادمین
* **مسیر:** `GET /api/v1/Products/GetAllProduct`
* **پارامترها:** `pageNumber`, `pageSize`, `search`, `categoryId`, `hasMedia`, `isActive`
* **جزئیات محصول جهت ویرایش:** `GET /api/v1/Products/GetDetailProduct/{id}`

### ۳.۲. ویرایش توضیحات و سئوی محصول
* **مسیر:** `POST /api/v1/Products/{id}/descriptions`
* **بدنه درخواست:**
  ```json
  {
    "shortDescriptionHtml": "توضیح کوتاه معرفی کالا",
    "longDescriptionHtml": "توضیحات جامع، جنس، شستشو...",
    "metaTitle": "خرید شومیز لینن ایپک - برند منگ",
    "metaDescription": "شومیز لینن باکیفیت و تن‌خور عالی...",
    "slug": "shomiz-linen-ipek"
  }
  ```

### ۳.۳. مدیریت برچسب‌ها (Tags)
* **افزودن برچسب به کالا:** `POST /api/v1/TagControllers/AddTagsToProduct`
* **افزودن برچسب به دسته‌بندی:** `POST /api/v1/TagControllers/AddTagsToCategory`
* **دریافت لیست تمام تگ‌ها:** `POST /api/v1/TagControllers/GetAllTags`

---

## ۴. مدیا و گالری تصاویر (FileMedia & CDN)

* **دریافت لیست تصاویر با فیلتر:** `POST /api/v1/FileMedia/GetFilteredMedia`
* **الصاق تصویر به کالا/دسته‌بندی:** `POST /api/v1/FileMedia/AddFilesToEntity`
  ```json
  {
    "entityId": 450,
    "entityType": "Product",
    "mediaIds": [120, 121, 122],
    "isMain": true
  }
  ```
* **حذف یا قطع اتصال مدیا:** `POST /api/v1/FileMedia/DetachMedia/{id}` و `RemoveFiles`

---

## ۵. نظرات کاربران و بازخوردها (Comment Moderation)

* **لیست نظرات در انتظار تایید:** `GET /api/v1/ProductComment/GetFilteredComments?status=Pending`
* **تغییر وضعیت نظر (تایید یا رد):** `POST /api/v1/ProductComment/UpdateStatus/{commentId}?status=Approved&adminReply=ممنون از نظر شما`

---

## ۶. تحلیل ترافیک خارجی و ترب (Third-Party Analytics)

این بخش مستقیماً با سرویس ترب و خزشگرها مرتبط است تا آمار ورودی‌ها مشخص باشد:
* **خلاصه لاگ‌های ورودی ترب:** `GET /api/v1/ThirdParty/LogSummary`
* **گزارش کالاها در ترب:** `GET /api/v1/ThirdParty/ProductReport?pageNumber=1&pageSize=20`
* **نمودار میله‌ای بازدید ورودی‌ها در بازه زمانی:** `GET /api/v1/ThirdParty/ProductVisitBarChart?startDate=1405-07-01&endDate=1405-07-25`
* **نمودار سهم پلتفرم‌ها (ترب، ایمالز، گوگل):** `GET /api/v1/ThirdParty/ProductVisitPieChart`

---

## ۷. تنظیمات پایه، درگاه‌ها و ریدایرکت‌ها (Settings & Redirects)

* **درگاه‌های بانکی:**
  * لیست درگاه‌ها: `GET /api/v1/Bank/GetGateway`
  * ایجاد درگاه جدید: `POST /api/v1/Bank/AddBankGateway`
  * ویرایش درگاه: `POST /api/v1/Bank/UpdateBankGateway`
  * غیرفعال‌سازی درگاه: `GET /api/v1/Bank/SoftDelete?gatewayId=1&active=false`
* **وضعیت اتصالات پرداخت:** `GET /api/v1/Setting/GetPaymentConnections` و `POST /Setting/UpdatePaymentConnections`
* **مدیریت ریدایرکت‌های سئو (Redirect Manager):**
  * لیست: `POST /api/v1/RedirectManager/GetAll`
  * ثبت یا ویرایش: `POST /api/v1/RedirectManager/AddOrUpdateRedirects`
  * حذف ریدایرکت: `POST /api/v1/RedirectManager/DeleteRedirect/{id}`
