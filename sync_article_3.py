"""
Mong Blog Article Sync Script (Article #3: Business Casual & Office Workwear Guide)
Usage on Runflare (or local):
    python manage.py shell < sync_article_3.py
    or
    python sync_article_3.py
"""
import os
import sys

# Ensure Django environment is configured
if not os.getenv("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import django
    django.setup()

from django.utils import timezone
from apps.website.models import (
    Article, BlogCategory, ArticleTag, ArticleBlogCategory,
    ArticleTagRelation, FileMedia, MediaAttachment
)

now = timezone.now()
UNIQ_URL = "business-casual-workwear-style-guide"
TITLE = "راهنمای جامع استایل کارمندی و بیزینس کژوال زنانه: شیک، حرفه‌ای و راحت در محیط کار و دانشگاه"
DESCRIPTION = "چگونه با ترکیب مانتوهای کتی، شلوارهای راسته و شومیزهای اداری، استایل کارمندی شیک و راحتی بسازیم؟ راهنمای اصول بیزینس کژوال برای محیط کار و دانشگاه با کالکشن مانگ."
THUMB_URL = "https://cdn.mong.ir/9/webgeneral/85352e4b-018e-43a8-ad7d-489be9a10d16.webp"

CONTENT_HTML = """
<div class="article-content" style="line-height: 2.1; font-size: 16px; color: #2d3748;">
  <p class="lead" style="font-size: 18px; font-weight: 500; color: #1a202c; margin-bottom: 24px;">
    دوران روپوش‌ها و مانتوهای اداری خسته‌کننده، یک‌شکل و بی‌روح به سر آمده است! امروزه بانوان شاغل و دانشجویان به دنبال سبکی هستند که هم وقار و رسمیت محیط‌های حرفه‌ای را حفظ کند و هم بازتابی از سلیقه، زیبایی و راحتی شخصی آن‌ها باشد. پاسخ دنیای مد به این نیاز، سبک محبوب <strong>«بیزینس کژوال» (Business Casual)</strong> است.
  </p>

  <p>
    اما در چارچوب پوشش محیط کار و دانشگاه در ایران، چگونه می‌توان استایلی ساخت که هم مطابق با ضوابط اداری باشد و هم در جلسات مهم کاری یا ساعات طولانی پشت میز نشستن، ظاهری قدرتمند، آراسته و آسوده به شما ببخشد؟ در این راهنمای تخصصی از <strong>تیم استایلینگ دپارتمان استور مانگ</strong>، اصول کلیدی بیزینس کژوال زنانه، ۵ آیتم بنیادین و ترفندهای ست کردن کالکشن‌های مانگ را با هم بررسی می‌کنیم.
  </p>

  <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 32px 0;" />

  <h2 id="business-casual-formula" style="font-size: 22px; font-weight: 700; color: #1a202c; margin-top: 36px; margin-bottom: 16px;">
    فرمول طلایی بیزینس کژوال در ایران: قانون ۷۰/۳۰
  </h2>
  <p>
    راز موفقیت در استایل بیزینس کژوال، ایجاد یک تعادل دقیق میان دو مفهوم است:
  </p>
  <div style="background-color: #f7fafc; border-right: 4px solid #3182ce; padding: 18px 24px; border-radius: 8px; margin: 20px 0;">
    <ul style="padding-right: 20px; margin: 0;">
      <li style="margin-bottom: 10px;"><strong>۷۰٪ ساختار و رسمیت (Professional):</strong> شامل خطوط تمیز دوخت، سرشانه‌های قرص، مانتوهای کتی اتوکشیده، شلوارهای راسته پارچه‌ای و پالت رنگی خنثی و باوقار (سرمه‌ای، طوسی دودی، زیتونی، مشکی و شتری).</li>
      <li style="margin: 0;"><strong>۳۰٪ راحتی و انعطاف روزمره (Casual & Comfort):</strong> شامل پارچه‌های ضدچروک و تنفس‌پذیر، کفش‌های لوفر یا کالج با لژ طبی، شومیزهای نخی یا کرپ با تن‌خور آزاد و جزئیات ظریف اکسسوری.</li>
    </ul>
  </div>
  <p>
    همان‌طور که در مقاله <a href="/blog/10B-capsule-wardrobe-guide-iran" style="color: #3182ce; font-weight: 600; text-decoration: underline;" target="_blank">راهنمای ساخت کمد کپسولی مانگ</a> توضیح دادیم، نیازی نیست برای هر روز یک دست لباس جدید بخرید؛ داشتن چند آیتم کلیدی باکیفیت به شما اجازه می‌دهد ده‌ها ست شیک اداری خلق کنید.
  </p>

  <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 32px 0;" />

  <h2 id="essential-workwear-items" style="font-size: 22px; font-weight: 700; color: #1a202c; margin-top: 36px; margin-bottom: 16px;">
    ۵ آیتم کلیدی برای کمد لباس کارمندی مدرن با کالکشن مانگ
  </h2>

  <!-- Item 1: Suit Set -->
  <h3 style="font-size: 19px; font-weight: 700; color: #2d3748; margin-top: 28px; margin-bottom: 12px;">
    ۱. ست کت و شلوار مونوکروم: سلاح قدرتمند جلسات و پرزنتیشن‌ها
  </h3>
  <p>
    هیچ لباسی به اندازه یک ست کت و شلوار با دوخت تمیز و رنگ یکدست، قدرت تصمیم‌گیری و اقتدار حرفه‌ای شما را در نگاه اول بازتاب نمی‌دهد. برای روزهایی که جلسه هیئت‌مدیره، دفاع پایان‌نامه، مذاکره کاری یا مصاحبه شغلی دارید، ست مونوکروم بهترین انتخاب است.
  </p>

  <!-- Product Card 1 -->
  <div style="display: flex; flex-wrap: wrap; gap: 16px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); align-items: center;">
    <div style="width: 130px; height: 175px; border-radius: 8px; overflow: hidden; background: #f7fafc; flex-shrink: 0; margin: 0 auto;">
      <img src="https://cdn.mong.ir/9/webgeneral/85352e4b-018e-43a8-ad7d-489be9a10d16.webp" alt="کت و شلوار زنانه دلیار ۲" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" />
    </div>
    <div style="flex: 1; min-width: 220px;">
      <span style="display: inline-block; background: #ebf8ff; color: #2b6cb0; font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 12px; margin-bottom: 6px;">پیشنهاد جلسات رسمی و پرزنتیشن</span>
      <h4 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: #1a202c;">ست کت و شلوار دلیار ۲</h4>
      <p style="margin: 0 0 12px 0; font-size: 13px; color: #4a5568; line-height: 1.7;">
        💡 <em>تحلیل استایل مانگ:</em> دوخت مهندسی‌شده با سرشانه‌های منظم و شلوار ست هماهنگ، اندام را کشیده‌تر نشان داده و بالاترین سطح رسمیت کاری را به نمایش می‌گذارد. در روزهای چهارشنبه می‌توانید کت آن را با شلوار جین تیره ست کنید.
      </p>
      <a href="/products-item/كت-و-شلوار-دليار2" target="_blank" style="display: inline-block; background: #3182ce; color: #ffffff; padding: 8px 16px; border-radius: 6px; font-size: 13px; font-weight: 600; text-decoration: none;">
        مشاهده و خرید کت و شلوار دلیار ۲ &larr;
      </a>
    </div>
  </div>

  <!-- Item 2: Smart Blazer -->
  <h3 style="font-size: 19px; font-weight: 700; color: #2d3748; margin-top: 32px; margin-bottom: 12px;">
    ۲. مانتو کتی خوش‌دوخت: آچارفرانسه استایل روزمره اداری
  </h3>
  <p>
    اگر محیط کاری شما سطح رسمیت انعطاف‌پذیرتری دارد، مانتو کتی تک بهترین دوست شما خواهد بود. مانتو کتی جایگزین فوق‌العاده‌ای برای مانتوهای بلند یا بدون فرم است؛ با قد مناسب، یقه انگلیسی یا بلیزر کلاسیک، استایلی مدرن و شاداب ایجاد می‌کند.
  </p>

  <!-- Product Card 2 -->
  <div style="display: flex; flex-wrap: wrap; gap: 16px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); align-items: center;">
    <div style="width: 130px; height: 175px; border-radius: 8px; overflow: hidden; background: #f7fafc; flex-shrink: 0; margin: 0 auto;">
      <img src="https://cdn.mong.ir/9/webgeneral/635506ca-1845-437c-8870-c4b819588d03.webp" alt="کت زنانه افروز مانگ" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" />
    </div>
    <div style="flex: 1; min-width: 220px;">
      <span style="display: inline-block; background: #fefcbf; color: #744210; font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 12px; margin-bottom: 6px;">پرفروش‌ترین مانتو کتی روزمره</span>
      <h4 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: #1a202c;">کت زنانه مدل افروز</h4>
      <p style="margin: 0 0 12px 0; font-size: 13px; color: #4a5568; line-height: 1.7;">
        💡 <em>تحلیل استایل مانگ:</em> کت افروز با قواره استاندارد خود برای ساعت‌های طولانی کار طراحی شده است؛ نه احساس تنگی ایجاد می‌کند و نه گشادی نامتعارف دارد. به زیبایی با شال نخی تیره یا مقنعه کرپ هماهنگ می‌شود.
      </p>
      <a href="/products-item/كت-افروز" target="_blank" style="display: inline-block; background: #3182ce; color: #ffffff; padding: 8px 16px; border-radius: 6px; font-size: 13px; font-weight: 600; text-decoration: none;">
        مشاهده و خرید کت افروز در مانگ &larr;
      </a>
    </div>
  </div>

  <!-- Item 3: Tailored Straight Pants -->
  <h3 style="font-size: 19px; font-weight: 700; color: #2d3748; margin-top: 32px; margin-bottom: 12px;">
    ۳. شلوار راسته دکمه‌دار: تضمین ۸ ساعت راحتی پشت میز
  </h3>
  <p>
    شلوار اداری باید دو ویژگی اساسی داشته باشد: اول اینکه پس از ساعت‌ها نشستن روی صندلی اداری چروک نشود، و دوم اینکه فاق و کمر آن احساس فشار یا خستگی ایجاد نکند. شلوارهای راسته با خط اتوی منظم، فرم پاها را خوش‌تراش نشان می‌دهند.
  </p>

  <!-- Product Card 3 -->
  <div style="display: flex; flex-wrap: wrap; gap: 16px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); align-items: center;">
    <div style="width: 130px; height: 175px; border-radius: 8px; overflow: hidden; background: #f7fafc; flex-shrink: 0; margin: 0 auto;">
      <img src="https://cdn.mong.ir/9/webgeneral/4f94f6bd-4b65-410f-86e7-350f8b3c6700.webp" alt="شلوار راسته سولین" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" />
    </div>
    <div style="flex: 1; min-width: 220px;">
      <span style="display: inline-block; background: #e2e8f0; color: #2d3748; font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 12px; margin-bottom: 6px;">پایه ضروری استایل کاری</span>
      <h4 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: #1a202c;">شلوار راسته مدل سولین</h4>
      <p style="margin: 0 0 12px 0; font-size: 13px; color: #4a5568; line-height: 1.7;">
        💡 <em>تحلیل استایل مانگ:</em> پارچه لطیف و بدون چروک با جزئیات دکمه‌دار روی کمر، ظاهری ساختارمند به آن بخشیده است. این شلوار به سادگی با کفش‌های پاشنه کوتاه اداری، کالج یا نیم‌بوت چرم هماهنگ می‌شود.
      </p>
      <a href="/products-item/شلوار-سولين" target="_blank" style="display: inline-block; background: #3182ce; color: #ffffff; padding: 8px 16px; border-radius: 6px; font-size: 13px; font-weight: 600; text-decoration: none;">
        مشاهده و خرید شلوار سولین در مانگ &larr;
      </a>
    </div>
  </div>

  <!-- Item 4: Layering Blouse -->
  <h3 style="font-size: 19px; font-weight: 700; color: #2d3748; margin-top: 32px; margin-bottom: 12px;">
    ۴. شومیز تنفس‌پذیر زیر کت: لایه درونی تمیز و اتوکشیده
  </h3>
  <p>
    لایه زیری مانتو یا کت اهمیت بالایی در تنظیم دمای بدن در محیط‌های کاری با سیستم گرمایش/سرمایش متغیر دارد. شومیزی که یقه ایستاده، مردانه یا کرواتی ملایم دارد، وقار استایل کتی شما را تکمیل می‌کند.
  </p>

  <!-- Product Card 4 -->
  <div style="display: flex; flex-wrap: wrap; gap: 16px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); align-items: center;">
    <div style="width: 130px; height: 175px; border-radius: 8px; overflow: hidden; background: #f7fafc; flex-shrink: 0; margin: 0 auto;">
      <img src="https://cdn.mong.ir/9/webgeneral/d81565e9-469e-4a90-8907-42d6b8fbe8b0.webp" alt="شومیز زنانه روژان" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" />
    </div>
    <div style="flex: 1; min-width: 220px;">
      <span style="display: inline-block; background: #feebc8; color: #7b341e; font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 12px; margin-bottom: 6px;">لایه پایه‌ای شیک و خنک</span>
      <h4 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: #1a202c;">شومیز زنانه مدل روژان</h4>
      <p style="margin: 0 0 12px 0; font-size: 13px; color: #4a5568; line-height: 1.7;">
        💡 <em>تحلیل استایل مانگ:</em> تن‌خور آزاد و پارچه سبک روژان بدون ایجاد حجم اضافه زیر کت قرار می‌گیرد و با حفظ فرم یقه در تمام طول روز، استایل شما را آراسته نگه می‌دارد.
      </p>
      <a href="/products-item/شومیز-روژان" target="_blank" style="display: inline-block; background: #3182ce; color: #ffffff; padding: 8px 16px; border-radius: 6px; font-size: 13px; font-weight: 600; text-decoration: none;">
        مشاهده و خرید شومیز روژان در مانگ &larr;
      </a>
    </div>
  </div>

  <!-- Item 5: Vest / Waistcoat -->
  <h3 style="font-size: 19px; font-weight: 700; color: #2d3748; margin-top: 32px; margin-bottom: 12px;">
    ۵. وست و جلیقه بلند: استایلی مدرن برای محیط‌های نوآور و دانشگاه
  </h3>
  <p>
    برای شرکت‌های استارتاپی، دفاتر معماری و طراحی، یا محیط‌های آکادمیک و دانشگاهی، ست وست و جلیقه بلند روی شومیز آستین‌بلند، یکی از شیک‌ترین ترندهای استایل روز است. این ترکیب هم پوشیدگی کامل و موقری دارد و هم خلاقیت و ذوق هنری شما را به نمایش می‌گذارد.
  </p>

  <!-- Product Card 5 -->
  <div style="display: flex; flex-wrap: wrap; gap: 16px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); align-items: center;">
    <div style="width: 130px; height: 175px; border-radius: 8px; overflow: hidden; background: #f7fafc; flex-shrink: 0; margin: 0 auto;">
      <img src="https://cdn.mong.ir/9/webgeneral/e5d7a165-610a-4af4-8785-8144d95dc028.webp" alt="وست جلیقه شلوار راز" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" />
    </div>
    <div style="flex: 1; min-width: 220px;">
      <span style="display: inline-block; background: #e9d8fd; color: #553c9a; font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 12px; margin-bottom: 6px;">ترند برتر محیط‌های مدرن و خلاق</span>
      <h4 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: #1a202c;">ست وست جلیقه و شلوار راز</h4>
      <p style="margin: 0 0 12px 0; font-size: 13px; color: #4a5568; line-height: 1.7;">
        💡 <em>تحلیل استایل مانگ:</em> خطوط کشیده جلیقه بر روی شومیز سفید یا کرم، قد اندام را بلندتر جلوه می‌دهد و جایگزینی بسیار شیک و متمایز برای مانتوهای معمولی به شمار می‌رود.
      </p>
      <a href="/products-item/وست-جليقه-شلوار-راز" target="_blank" style="display: inline-block; background: #3182ce; color: #ffffff; padding: 8px 16px; border-radius: 6px; font-size: 13px; font-weight: 600; text-decoration: none;">
        مشاهده و خرید وست جلیقه شلوار راز &larr;
      </a>
    </div>
  </div>

  <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 32px 0;" />

  <h2 id="shoes-and-accessories" style="font-size: 22px; font-weight: 700; color: #1a202c; margin-top: 36px; margin-bottom: 16px;">
    کفش، کیف و اکسسوری در بیزینس کژوال: جزئیاتی که تفاوت می‌سازند
  </h2>
  <p>
    یک ست لباس اداری عالی بدون کفش و کیف مناسب کامل نمی‌شود. در استایل کاری ایرانی، این ۳ اصل را همیشه به خاطر بسپارید:
  </p>
  <ul style="padding-right: 20px; margin-bottom: 24px;">
    <li style="margin-bottom: 10px;">
      <strong>کفش‌های برنده محیط کار:</strong> پاشنه‌های باریک و بلند ۱۰ سانتی‌متری را فراموش کنید! معجزه بیزینس کژوال در <strong>کفش‌های لوفر چرم (Loafers)، کفش‌های آکسفورد بنددار، کالج‌های لژدار طبی و کتانی‌های چرمی تک‌رنگ و مینیمال (تمام مشکی یا سفید بدون لوگوی درشت)</strong> است.
    </li>
    <li style="margin-bottom: 10px;">
      <strong>کیف اداری ساختارمند:</strong> یک کیف چرمی مدل توت (Tote Bag) یا دوشی با ساختار ایستاده، که جایگاه لپ‌تاپ و مدارک داشته باشد، جلوه شما را فوراً حرفه‌ای‌تر می‌کند. کیف‌های خیلی شل و پارچه‌ای یا ساک‌های بزرگ غیررسمی برای جلسات کاری مناسب نیستند.
    </li>
    <li style="margin-bottom: 10px;">
      <strong>شال و مقنعه:</strong> اگر در محیط کار از مقنعه استفاده می‌کنید، مقنعه کرپ با لبه اتوکشیده و ریزش تمیز، فرم صورت را قاب می‌گیرد. اگر از شال استفاده می‌کنید، شال‌های نخی اسلپ، ابریشم‌توییل یا کرپ در رنگ‌های سرمه‌ای، زرشکی تیره، طوسی، دودی یا شتری بهترین تناسب را دارند.
    </li>
  </ul>

  <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 32px 0;" />

  <h2 id="mistakes-to-avoid" style="font-size: 22px; font-weight: 700; color: #1a202c; margin-top: 36px; margin-bottom: 16px;">
    ۴ اشتباه رایج در استایل محیط کار که باید از آن‌ها دوری کنید
  </h2>
  <ol style="padding-right: 20px; margin-bottom: 24px;">
    <li style="margin-bottom: 8px;"><strong>پوشیدن پارچه‌های پلاستیکی و براق:</strong> این پارچه‌ها هم سریع بو می‌گیرند و هم جلوه ارزان‌قیمت دارند. به جای آن از کرپ‌های باکیفیت، فاستونی، کتان و پشم استفاده کنید.</li>
    <li style="margin-bottom: 8px;"><strong>لباس‌های با پارگی (Ripped Jeans) یا طرح‌های گرافیکی شلوغ:</strong> حتی در کژوال‌ترین روز کاری، مرز رسمیت محیط حرفه‌ای باید حفظ شود.</li>
    <li style="margin-bottom: 8px;"><strong>استفاده از اکسسوری‌های پرسروصدا:</strong> النگوها یا گوشواره‌های بزرگی که هنگام کار با کیبورد یا حرکت دست صدا می‌دهند، تمرکز همکاران را بر هم می‌زنند. به یک ساعت مچی شیک و مینیمال بسنده کنید.</li>
    <li style="margin-bottom: 8px;"><strong>فراموش کردن تناسب اندام:</strong> همان‌طور که در <a href="/blog/11B-how-to-dress-for-your-body-type" style="color: #3182ce; font-weight: 600; text-decoration: underline;" target="_blank">راهنمای انتخاب مانتو بر اساس فرم اندام مانگ</a> بررسی کردیم، لباسی که اندازه بدن شما نباشد (خیلی تنگ یا بیش از حد افتاده)، تسلط حرفه‌ای شما را مخدوش می‌کند.</li>
  </ol>

  <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 32px 0;" />

  <h2 id="faq-workwear" style="font-size: 22px; font-weight: 700; color: #1a202c; margin-top: 36px; margin-bottom: 16px;">
    پرسش‌های پرتکرار درباره استایل کاری و بیزینس کژوال
  </h2>
  <div style="margin-bottom: 18px;">
    <h4 style="margin: 0 0 6px 0; color: #2c5282; font-size: 16px;">آیا در استایل بیزینس کژوال می‌توان شلوار جین پوشید؟</h4>
    <p style="margin: 0; font-size: 14px; color: #4a5568;">
      بله، اما با رعایت چند شرط: شلوار جین باید راسته یا مام‌فیت، به رنگ سرمه‌ای تیره یا دودی تیره، و کاملاً بدون زاپ و پارگی باشد. آن را با یک مانتو کتی ساختارمند و کفش لوفر ست کنید تا استایل اداری حفظ شود.
    </p>
  </div>
  <div style="margin-bottom: 18px;">
    <h4 style="margin: 0 0 6px 0; color: #2c5282; font-size: 16px;">بهترین پالت رنگی برای پوشش اداری در ایران چیست؟</h4>
    <p style="margin: 0; font-size: 14px; color: #4a5568;">
      بهترین پایه‌ها سرمه‌ای عمیق، طوسی زغالی، زیتونی خاکی، مشکی، و کرم-شتری هستند. برای لایه‌های زیرین (شومیز) می‌توانید از رنگ‌های ملایم مثل آبی آسمانی، استخوانی، صورتی کثیف یا سدری استفاده کنید تا خستگی روز از استایل گرفته شود.
    </p>
  </div>
  <div style="margin-bottom: 18px;">
    <h4 style="margin: 0 0 6px 0; color: #2c5282; font-size: 16px;">برای مصاحبه کاری چه پوششی مناسب‌تر است؟</h4>
    <p style="margin: 0; font-size: 14px; color: #4a5568;">
      یک ست کت و شلوار هماهنگ مانند ست دلیار یا یک مانتو کتی اتوکشیده به رنگ سرمه‌ای یا طوسی همراه با شلوار راسته پارچه‌ای و کفش چرم، تصویری مصمم، قابل اعتماد و حرفه‌ای از شما به کارفرما منتقل می‌کند.
    </p>
  </div>

  <div style="background: linear-gradient(135deg, #ebf8ff 0%, #e6fffa 100%); border-radius: 12px; padding: 24px; text-align: center; margin-top: 40px;">
    <h3 style="margin-top: 0; color: #2c5282; font-size: 20px; font-weight: 700;">استایل کاری منحصر‌به‌فرد خود را با مانگ بسازید</h3>
    <p style="color: #4a5568; max-width: 600px; margin: 10px auto 20px auto;">
      مجموعه مانتوهای کتی، شلوارهای راسته و شومیزهای اداری مانگ با دقت در دوخت و مرغوبیت پارچه، همراه مطمئن ساعات کاری شما هستند.
    </p>
    <a href="/products-category/all" style="display: inline-block; background-color: #3182ce; color: #ffffff; padding: 12px 28px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 15px; box-shadow: 0 4px 6px rgba(49, 130, 206, 0.3);">
      مشاهده کالکشن مانتو و پوشاک زنانه مانگ &larr;
    </a>
  </div>
</div>
""".strip()

def run_sync():
    print("=== Starting Blog Article 3 Sync (Business Casual Guide) ===")

    # 1. FileMedia for Article 3 thumbnail
    fm, _ = FileMedia.objects.get_or_create(
        url=THUMB_URL,
        defaults={
            "file_name": "business-casual-workwear-guide.webp",
            "tooltip_title": "راهنمای استایل اداری و بیزینس کژوال زنانه",
            "alternative": "استایل اداری و مانتو کتی زنانه مانگ",
            "upload_time": now,
            "used": True,
        }
    )
    print(f"FileMedia ID: {fm.id}")

    # 2. Upsert Article with id=12
    article, created = Article.objects.update_or_create(
        uniq_url=UNIQ_URL,
        defaults={
            "id": 12,
            "title": TITLE,
            "description": DESCRIPTION,
            "content": CONTENT_HTML,
            "thumbnail": THUMB_URL,
            "author_id": 1,
            "publish_date": now,
            "show_on_page": True,
            "view_count": 8,
            "is_deleted": False,
        }
    )
    print(f"Article ID {article.id} {'created' if created else 'updated'}: {article.title}")

    # 3. Category: مد و لباس (id=1)
    cat, _ = BlogCategory.objects.get_or_create(
        id=1,
        defaults={"title": "مد و لباس", "slug": "fashion-clothing", "is_deleted": False}
    )
    ArticleBlogCategory.objects.get_or_create(article=article, category=cat)
    print(f"Associated with Category: {cat.title}")

    # 4. Tags
    tag_names = [
        "مد و لباس", "استایل اداری", "بیزینس کژوال", "استایل زنانه",
        "مانتو کتی", "ترفندهای استایل", "شیک", "استایل دانشجویی"
    ]
    for tag_name in tag_names:
        tag, _ = ArticleTag.objects.get_or_create(
            name=tag_name,
            defaults={"is_deleted": False}
        )
        ArticleTagRelation.objects.get_or_create(article=article, tag=tag)
    print(f"Associated {len(tag_names)} tags")

    # 5. MediaAttachment for Admin Panel Gallery
    TABLE_ARTICLES = 32
    MediaAttachment.objects.filter(table=TABLE_ARTICLES, record_id=article.id).delete()
    MediaAttachment.objects.create(
        table=TABLE_ARTICLES,
        record_id=article.id,
        media_url=THUMB_URL,
        is_video=False,
        alternative="راهنمای استایل کارمندی و بیزینس کژوال مانگ",
        tooltip_title=TITLE,
        is_product_guid=False,
        is_deleted=False,
    )
    print("MediaAttachment created.")
    print("=== Article 3 Sync Complete ===")

if __name__ == "__main__":
    run_sync()

