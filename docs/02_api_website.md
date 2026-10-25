# فصل ۲: مشخصات فنی API فروشگاه آنلاین (`api.mong.ir`)

این سند راهنمای کامل اندپوینت‌های مورد نیاز فرانت‌اند کاربران (`mong_front/src/app/(web)`) است. هر بک‌اند جدیدی (مانند جنگو) برای کار با این فرانت‌اند، باید این مسیرها و ساختار داده‌ها را برآورده کند.

* **Base URL در فرانت‌اند:** `process.env.NEXT_PUBLIC_PO_MONG` (مثال: `https://api.mong.ir/api/v1`)
* **هدرهای سراسری:**
  * `companyid: "1"`
  * `Authorization: Bearer <JWT_TOKEN>` (برای مسیرهای نیازمند لاگین با فلگ `auth: true`)

---

## ۱. ماژول احراز هویت و مشتریان (Authentication & Customer)

### ۱.۱. ارسال کد یکبار مصرف (Send OTP)
* **مسیر:** `POST /api/v1/Authentication/SendOtpCode`
* **دسترسی:** عمومی
* **بدنه درخواست (Request Body):**
  ```json
  {
    "cellPhone": "09121234567"
  }
  ```
* **پاسخ سرور (Response):**
  ```json
  {
    "isSuccess": true,
    "statusCode": 200,
    "message": "کد تایید ارسال گردید",
    "data": true
  }
  ```

### ۱.۲. اعتبارسنجی کد و دریافت توکن (Authenticate)
* **مسیر:** `POST /api/v1/Authentication/CustomerAuthenticate`
* **دسترسی:** عمومی
* **بدنه درخواست:**
  ```json
  {
    "cellPhone": "09121234567",
    "otpCode": "12345"
  }
  ```
* **پاسخ سرور:**
  ```json
  {
    "isSuccess": true,
    "statusCode": 200,
    "data": {
      "token": "eyJhbGciOi...",
      "refreshToken": "...",
      "expires": "2026-11-25T12:00:00Z",
      "user": {
        "id": 1052,
        "cellPhone": "09121234567",
        "firstName": "سارا",
        "lastName": "احمدی"
      }
    }
  }
  ```

### ۱.۳. استعلام پروفایل کاربر
* **مسیر:** `GET /api/v1/Customer/GetMyProfileAsync`
* **هدر:** `auth: true`
* **پاسخ سرور:**
  ```json
  {
    "isSuccess": true,
    "data": {
      "id": 1052,
      "firstName": "سارا",
      "lastName": "احمدی",
      "cellphone": "09121234567",
      "nationalCode": "0012345678",
      "email": "user@example.com",
      "birthDate": "1375/06/15"
    }
  }
  ```

### ۱.۴. مدیریت آدرس‌ها
* **دریافت لیست آدرس‌ها:** `GET /api/v1/Customer/GetCustomerAddress` (هدر: `auth: true`)
* **ثبت آدرس جدید:** `POST /api/v1/Customer/AddCustomerAddress`
  ```json
  {
    "provinceId": 8,
    "cityId": 125,
    "address": "بلوار اندرزگو، خیابان سلیمی، پلاک ۱۲",
    "postalCode": "1938912345",
    "plaque": "12",
    "unit": "4",
    "latitude": 35.801,
    "longitude": 51.455,
    "recipientName": "سارا احمدی",
    "recipientMobile": "09121234567"
  }
  ```
* **ویرایش آدرس:** `POST /api/v1/Customer/UpdateCustomerAddress`
* **حذف نرم آدرس:** `GET /api/v1/Customer/SoftDeleteCustomerAddress/{addressId}`

### ۱.۵. استان‌ها و شهرها
* **لیست استان‌ها:** `GET /api/v1/ProvinceCity/GetAllProvince`
* **لیست شهرهای یک استان:** `GET /api/v1/ProvinceCity/GetAllCity/{provinceId}`

---

## ۲. کاتالوگ، محصولات و موجودی (Products & Catalog)

### ۲.۱. لیست محصولات با فیلتر (Product Listing)
* **مسیر:** `POST /api/v1/Product/GetAll`
* **بدنه درخواست (فیلترهای ارسالی فرانت‌اند):**
  ```json
  {
    "pageNumber": 1,
    "pageSize": 20,
    "categoryId": 15,
    "brandIds": [],
    "minPrice": 5000000,
    "maxPrice": 30000000,
    "sizes": ["S", "M"],
    "colors": ["مشکی", "سفید"],
    "isAvailable": true,
    "sortCriteria": 1
  }
  ```
* **پاسخ سرور:**
  ```json
  {
    "isSuccess": true,
    "data": {
      "items": [
        {
          "id": 450,
          "productName": "شومیز لینن راه راه ایپک",
          "slug": "shomiz-linen-ipek-450",
          "product_Base_Price": 23870000,
          "product_base_reduction": 39.25,
          "priceAfterReduction": 14500000,
          "mainImages": [
            {
              "id": 120,
              "mediaUrl": "https://cdn.mong.ir/products/p450_1.webp",
              "isVideo": false
            }
          ],
          "hasColor": true
        }
      ],
      "totalCount": 85,
      "pageNumber": 1,
      "pageSize": 20
    }
  }
  ```

### ۲.۲. جزئیات کامل یک کالا (Product Full Detail)
* **مسیر:** `GET /api/v1/Product/GetById/{id}` یا با اسلاگ
* **پاسخ سرور:**
  ```json
  {
    "isSuccess": true,
    "data": {
      "id": 450,
      "productName": "شومیز لینن راه راه ایپک",
      "slug": "shomiz-linen-ipek-450",
      "categoryId": 15,
      "product_Base_Price": 23870000,
      "product_base_reduction": 39.25,
      "priceAfterReduction": 14500000,
      "shortDescriptionHtml": "<p>پارچه لینن ترک درجه یک</p>",
      "longDescriptionHtml": "...",
      "mainImages": [ ... ],
      "productSizes": [
        { "id": 1, "sizeName": "FreeSize" }
      ],
      "details": [
        {
          "id": 1,
          "title": "رنگ‌بندی و سایز",
          "hasColor": true,
          "items": [
            {
              "id": 1617,
              "productVariantId": 450004552,
              "name": "صورتی / FreeSize",
              "value": "#FFC0CB",
              "price": 23870000,
              "reduction": 39.25,
              "discount": 9370000,
              "mojodi": 5,
              "displayPriority": 1
            },
            {
              "id": 1618,
              "productVariantId": 450004553,
              "name": "مشکی / FreeSize",
              "value": "#000000",
              "price": 23870000,
              "reduction": 39.25,
              "discount": 9370000,
              "mojodi": 0,
              "displayPriority": 2
            }
          ]
        }
      ]
    }
  }
  ```

### ۲.۳. دسته‌بندی‌ها، کالکشن‌ها و استایل‌ها
* **دسته‌بندی‌های منو:** `GET /api/v1/Category/GetAll` و `GET /api/v1/Category/GetBanners`
* **کالکشن‌های فصلی:** `GET /api/v1/Collection/GetAll` و `GET /api/v1/Collection/GetById/{id}`
* **استایل‌ها (Outfits):** `GET /api/v1/Outfit/GetAll`

---

## ۳. سبد خرید، سفارشات و پیش‌فاکتور (Cart & Invoices)

### ۳.۱. استعلام پیش‌فاکتور (Pre-Invoice / Cart Check)
* **مسیر:** `GET /api/v1/Invoice/GetLastPreInvoice`
* **هدر:** `auth: true`
* **وظیفه:** بررسی سبد خرید مشتری و اطمینان از موجود بودن کالاها در انبار و ثبات قیمت.

### ۳.۲. روش‌های ارسال و هزینه‌ها (Shipping Methods)
* **مسیر:** `GET /api/v1/ShipingMethod/GetAllShipingMethod`
* **پاسخ سرور:**
  ```json
  {
    "isSuccess": true,
    "data": [
      {
        "id": 1,
        "title": "پست پیشتاز",
        "description": "ارسال طی ۳ تا ۵ روز کاری",
        "cost": 650000,
        "freeDeliveryThreshold": 20000000
      },
      {
        "id": 2,
        "title": "پیک فوری (مخصوص تهران)",
        "description": "ارسال همان روز",
        "cost": 1500000
      }
    ]
  }
  ```

### ۳.۳. ایجاد فاکتور جدید (Checkout / Add Invoice)
* **مسیر:** `POST /api/v1/Invoice/Add`
* **هدر:** `auth: true`
* **بدنه درخواست:**
  ```json
  {
    "customerAddressId": 45,
    "shippingMethodId": 1,
    "couponCode": "OFFSUMMER",
    "description": "لطفاً عصر تحویل داده شود",
    "details": [
      {
        "productVariantId": 450004552,
        "qty": 1
      }
    ]
  }
  ```
* **پاسخ سرور:**
  ```json
  {
    "isSuccess": true,
    "data": {
      "id": 9845,
      "shippingMethodId": 1,
      "payableAmount": 15150000
    }
  }
  ```

### ۳.۴. تخلیه سبد خرید
* **مسیر:** `POST /api/v1/Invoice/ClearCart` (هدر: `auth: true`)

### ۳.۵. تاریخچه فاکتورهای مشتری
* **لیست فاکتورها:** `GET /api/v1/Invoice/GetAllCustomerInvoice`
* **جزئیات فاکتور با کد:** `GET /api/v1/Invoice/GetCustomerInvoiceById/{invoiceId}`

---

## ۴. درگاه‌های پرداخت و تسویه حساب (Banking & Payment)

### ۴.۱. لیست درگاه‌های پرداخت
* **مسیر:** `GET /api/v1/Bank/GetGateways`
* **پاسخ سرور:**
  ```json
  {
    "isSuccess": true,
    "data": [
      { "id": 1, "name": "zarinpal", "title": "درگاه زرین‌پال (کارت‌های شتابی)" },
      { "id": 2, "name": "snapppay", "title": "پرداخت اقساطی ۴ ماهه اسنپ‌پی" },
      { "id": 3, "name": "sadad", "title": "درگاه پرداخت الکترونیک سداد" }
    ]
  }
  ```

### ۴.۲. شروع پرداخت (Get Payment Link)
* **مسیر:** `GET /api/v1/Bank/PayInvoiceById?InvoiceId=9845&ShippingMethodId=1&GateWayId=1`
* **پاسخ سرور:**
  ```json
  {
    "isSuccess": true,
    "data": {
      "paymentUrl": "https://www.zarinpal.com/pg/StartPay/A0000000000...",
      "authority": "A0000000000..."
    }
  }
  ```

### ۴.۳. استعلام اهلیت اسنپ‌پی (SnappPay Eligibility)
* **مسیر:** `GET /api/v1/Bank/SnappPayEligible?Amount=15150000`
* **پاسخ سرور:**
  ```json
  {
    "isSuccess": true,
    "data": {
      "eligible": true,
      "title_message": "واجد شرایط پرداخت اقساطی",
      "description": "پرداخت در ۴ قسط بدون کارمزد"
    }
  }
  ```

### ۴.۴. وریفای تراکنش (Payment Verification)
* **مسیر:** `POST /api/v1/Invoice/PaymentVerification`
* **وظیفه:** دریافت پارامترهای بازگشتی از درگاه، تایید با سرور بانک و تغییر وضعیت فاکتور به "پرداخت شده" و کسر از انبار.

---

## ۵. نظرات، وبلاگ و فرم‌ها (Comments, Blog & Cooperation)

* **ثبت نظر برای کالا:** `POST /api/v1/Comment/add/?productId=450&featureValueId=1617`
* **خواندن نظرات یک کالا:** `GET /api/v1/Comment/GetByProductIdAsync?productId=450`
* **لایک نظر:** `POST /api/v1/Comment/Reaction`
* **مقالات وبلاگ:** `GET /api/v1/Article/GetAll`, `GET /api/v1/Article/GetBySlug/{slug}`
* **فرم همکاری / استخدام:** `POST /api/v1/Cooperation/CooperationRequestSubmit`
