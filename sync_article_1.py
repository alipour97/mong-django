"""
Mong Blog Article Sync Script (Article #1: Capsule Wardrobe Guide)
Updated with:
- Natural, punchy editorial Persian tone
- Brand purple colors (#711f7e)
- In-stock verified products with real model photoshoot images
- High-res fashion banner
"""
import os
import sys

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
UNIQ_URL = "capsule-wardrobe-guide-iran"
TITLE = "کمد کپسولی: با ۱۰ آیتم، ۳۰ استایل بسازید"
DESCRIPTION = "چطور با چند آیتم کاربردی و باکیفیت، کمدی خلوت اما پر از استایل‌های شیک و متنوع داشته باشیم؟ راهنمای کاربردی کمد کپسولی با محصولات موجود در مانگ."
THUMB_URL = "https://cdn.mong.ir/9/webgeneral/ffde6ae2-6212-46b4-a74d-daa22851774d.webp"

CONTENT_HTML = """
<div class="article-content" style="line-height: 2.1; font-size: 16px; color: #2d3748;">
  <p class="lead" style="font-size: 18px; font-weight: 500; color: #1a202c; margin-bottom: 24px;">
    شاید برای شما هم پیش آمده باشد که روبروی کمدی پر از لباس بایستید و با کلافگی بگویید: «من هیچی ندارم بپوشم!» 
    این معضل همیشگی ناشی از کمبود لباس نیست؛ بلکه به خاطر نداشتن یک استراتژی هوشمندانه است. راهکار مدرن این مشکل، ساختن یک <strong>کمد کپسولی (Capsule Wardrobe)</strong> است.
  </p>

  <p>
    ایده کمد کپسولی بسیار ساده است: داشتن تعداد مشخصی آیتم اصلی، باکیفیت و همه‌کاره که رنگ‌ها و فرم آن‌ها به راحتی با یکدیگر ست می‌شوند. با این روش، هم از خرید لباس‌های بی‌استفاده خلاص می‌شوید و هم هر روز در چند دقیقه، استایلی آراسته و شیک برای بیرون، دانشگاه یا محیط کار خلق می‌کنید.
  </p>

  <hr style="border: 0; border-top: 1px solid #f3e8ff; margin: 32px 0;" />

  <h2 id="why-capsule" style="font-size: 22px; font-weight: 700; color: #711f7e; margin-top: 36px; margin-bottom: 16px;">
    کمد کپسولی چیست و چرا به آن نیاز داریم؟
  </h2>
  <p>
    کمد کپسولی مجموعه‌ای محدود اما کاربردی از لباس‌هاست که هیچ‌کدام بی‌مصرف در گوشه کمد رها نمی‌شوند. در سبک پوشش روزمره بانوان ایرانی، داشتن یک لایه اصلی خوش‌دوخت (کت یا مانتو)، شلوارهای خوش‌برش و زیرمانتویی‌های استاندارد، هسته اصلی این کمد را تشکیل می‌دهند.
  </p>
  <div style="background-color: #faf5ff; border-right: 4px solid #711f7e; padding: 18px 24px; border-radius: 8px; margin: 20px 0;">
    <ul style="padding-right: 20px; margin: 0; color: #4a5568;">
      <li style="margin-bottom: 8px;"><strong>صرفه‌جویی در هزینه:</strong> سرمایه‌گذاری روی چند لباس مرغوب به جای ده‌ها لباس کم‌کیفیت.</li>
      <li style="margin-bottom: 8px;"><strong>آرامش و سرعت:</strong> تصمیم‌گیری برای انتخاب لباس روزانه در کمتر از ۲ دقیقه.</li>
      <li style="margin: 0;"><strong>تنوع واقعی:</strong> ترکیب آیتم‌ها با فرمول‌های مختلف بدون تکراری شدن ظاهر شما.</li>
    </ul>
  </div>

  <hr style="border: 0; border-top: 1px solid #f3e8ff; margin: 32px 0;" />

  <h2 id="key-items" style="font-size: 22px; font-weight: 700; color: #711f7e; margin-top: 36px; margin-bottom: 16px;">
    ۵ آیتم پایه برای شروع با کالکشن مانگ
  </h2>

  <!-- Item 1: Coat / Blazer -->
  <h3 style="font-size: 18px; font-weight: 700; color: #2d3748; margin-top: 28px; margin-bottom: 12px;">
    ۱. ست پیراهن و کت (ستون اصلی کمد)
  </h3>
  <p>
    یک کت با رنگ خنثی و تن‌خور استاندارد، به هر استایلی رسمیت و زیبایی می‌بخشد؛ چه آن را با شلوار پارچه‌ای بپوشید و چه با جین.
  </p>

  <!-- Product Card 1 -->
  <div style="display: flex; flex-wrap: wrap; gap: 16px; background: #ffffff; border: 1px solid #f3e8ff; border-radius: 12px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 12px rgba(113, 31, 126, 0.05); align-items: center;">
    <div style="width: 120px; height: 160px; border-radius: 8px; overflow: hidden; background: #faf5ff; flex-shrink: 0; margin: 0 auto;">
      <img src="/img/lz/bb4080f098b1fab04032e4e5a6118f9892d0ab2d/full.webp" alt="ست پیراهن و کت آوان" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" />
    </div>
    <div style="flex: 1; min-width: 220px;">
      <span style="display: inline-block; background: #f3e8ff; color: #711f7e; font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 12px; margin-bottom: 6px;">آیتم کلیدی کمد کپسولی</span>
      <h4 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: #1a202c;">ست پیراهن و کت آوان</h4>
      <p style="margin: 0 0 12px 0; font-size: 13px; color: #4a5568; line-height: 1.7;">
        💡 <em>پیشنهاد استایلیست:</em> می‌توانید کت را به تنهایی روی شلوار راسته ست کنید یا همراه با پیراهن ست آن در دورهمی‌ها بپوشید.
      </p>
      <a href="/products-item/ست-پيراهن-و-كت-آوان" target="_blank" style="display: inline-block; background: #711f7e; color: #ffffff; padding: 9px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; text-decoration: none;">
        مشاهده و خرید در مانگ &larr;
      </a>
    </div>
  </div>

  <!-- Item 2: Straight Pants -->
  <h3 style="font-size: 18px; font-weight: 700; color: #2d3748; margin-top: 32px; margin-bottom: 12px;">
    ۲. شلوار پارچه‌ای راسته (برای روزهای کاری و رسمی)
  </h3>
  <p>
    شلوار راسته خوش‌دوخت در رنگ‌های مشکی، زغالی یا کرم، پای ثابت استایل‌های روزمره و رسمی است و قد پا را کشیده‌تر نشان می‌دهد.
  </p>

  <!-- Product Card 2 -->
  <div style="display: flex; flex-wrap: wrap; gap: 16px; background: #ffffff; border: 1px solid #f3e8ff; border-radius: 12px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 12px rgba(113, 31, 126, 0.05); align-items: center;">
    <div style="width: 120px; height: 160px; border-radius: 8px; overflow: hidden; background: #faf5ff; flex-shrink: 0; margin: 0 auto;">
      <img src="/img/lz/7b742d5ed5f12dc195cab3fc41f9734113b3e9b4/full.webp" alt="شلوار راسته مدل ۷۶۵" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" />
    </div>
    <div style="flex: 1; min-width: 220px;">
      <span style="display: inline-block; background: #f3e8ff; color: #711f7e; font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 12px; margin-bottom: 6px;">پایه ضروری هر کمد</span>
      <h4 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: #1a202c;">شلوار راسته مدل ۷۶۵</h4>
      <p style="margin: 0 0 12px 0; font-size: 13px; color: #4a5568; line-height: 1.7;">
        💡 <em>پیشنهاد استایلیست:</em> خط اتوی بادوام و فرم متناسب این شلوار، با انواع کتانی سفید، لوفر یا نیم‌بوت به خوبی هماهنگ می‌شود.
      </p>
      <a href="/products-item/شلوار-راسته-765" target="_blank" style="display: inline-block; background: #711f7e; color: #ffffff; padding: 9px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; text-decoration: none;">
        مشاهده و خرید در مانگ &larr;
      </a>
    </div>
  </div>

  <!-- Item 3: Straight Denim -->
  <h3 style="font-size: 18px; font-weight: 700; color: #2d3748; margin-top: 32px; margin-bottom: 12px;">
    ۳. شلوار جین راسته بدون زاپ (همه‌کاره‌ترین آیتم کژوال)
  </h3>
  <p>
    یک شلوار جین راسته خوش‌فرم با رنگ سرمه‌ای یا آبی کلاسیک، پایه اصلی استایل‌های آخر هفته، قرارهای دوستانه و دانشگاه است.
  </p>

  <!-- Product Card 3 -->
  <div style="display: flex; flex-wrap: wrap; gap: 16px; background: #ffffff; border: 1px solid #f3e8ff; border-radius: 12px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 12px rgba(113, 31, 126, 0.05); align-items: center;">
    <div style="width: 120px; height: 160px; border-radius: 8px; overflow: hidden; background: #faf5ff; flex-shrink: 0; margin: 0 auto;">
      <img src="/img/lz/de90aab90691537a98f0e48bdd330faae6772923/full.webp" alt="شلوار جین راسته ترک" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" />
    </div>
    <div style="flex: 1; min-width: 220px;">
      <span style="display: inline-block; background: #f3e8ff; color: #711f7e; font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 12px; margin-bottom: 6px;">همه‌کاره و بادوام</span>
      <h4 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: #1a202c;">شلوار جین راسته ترک</h4>
      <p style="margin: 0 0 12px 0; font-size: 13px; color: #4a5568; line-height: 1.7;">
        💡 <em>پیشنهاد استایلیست:</em> سادگی و فیت استاندارد این جین باعث می‌شود به راحتی با هر مانتو، پالتو یا بارانی ست شود.
      </p>
      <a href="/products-item/شلوار-جین-راسته-ترک" target="_blank" style="display: inline-block; background: #711f7e; color: #ffffff; padding: 9px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; text-decoration: none;">
        مشاهده و خرید در مانگ &larr;
      </a>
    </div>
  </div>

  <!-- Item 4: Blouse -->
  <h3 style="font-size: 18px; font-weight: 700; color: #2d3748; margin-top: 32px; margin-bottom: 12px;">
    ۴. شومیز لطیف و خنک (لایه زیرین تنفس‌پذیر)
  </h3>
  <p>
    شومیزهای تهیه شده از الیاف طبیعی مانند بامبو یا لیوسل، راحتی فوق‌العاده‌ای در طول روز دارند و زیر هر کتی اتوکشیده می‌مانند.
  </p>

  <!-- Product Card 4 -->
  <div style="display: flex; flex-wrap: wrap; gap: 16px; background: #ffffff; border: 1px solid #f3e8ff; border-radius: 12px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 12px rgba(113, 31, 126, 0.05); align-items: center;">
    <div style="width: 120px; height: 160px; border-radius: 8px; overflow: hidden; background: #faf5ff; flex-shrink: 0; margin: 0 auto;">
      <img src="/img/lz/46e1f2afd2c5b51721ef1dfc4613e2c4087ae6e6/full.webp" alt="شومیز لیوسل بامبو" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" />
    </div>
    <div style="flex: 1; min-width: 220px;">
      <span style="display: inline-block; background: #f3e8ff; color: #711f7e; font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 12px; margin-bottom: 6px;">لطیف و بدون تعریق</span>
      <h4 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: #1a202c;">شومیز لیوسل بامبو</h4>
      <p style="margin: 0 0 12px 0; font-size: 13px; color: #4a5568; line-height: 1.7;">
        💡 <em>پیشنهاد استایلیست:</em> به دلیل تنفس‌پذیری بالا، بهترین گزینه برای پوشیدن زیر کت یا وست در ساعات طولانی بیرون از منزل است.
      </p>
      <a href="/products-item/شوميز-ليوسل-بامبو" target="_blank" style="display: inline-block; background: #711f7e; color: #ffffff; padding: 9px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; text-decoration: none;">
        مشاهده و خرید در مانگ &larr;
      </a>
    </div>
  </div>

  <!-- Item 5: Knit / Sweater -->
  <h3 style="font-size: 18px; font-weight: 700; color: #2d3748; margin-top: 32px; margin-bottom: 12px;">
    ۵. بافت سبک یقه هفت (قهرمان فصل‌های خنک)
  </h3>
  <p>
    یک بافت سبک پنبه‌ای را می‌توانید روی شومیز، زیر بارانی یا به تنهایی بپوشید و لایه‌بندی‌های گرم و چشم‌نوازی بسازید.
  </p>

  <!-- Product Card 5 -->
  <div style="display: flex; flex-wrap: wrap; gap: 16px; background: #ffffff; border: 1px solid #f3e8ff; border-radius: 12px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 12px rgba(113, 31, 126, 0.05); align-items: center;">
    <div style="width: 120px; height: 160px; border-radius: 8px; overflow: hidden; background: #faf5ff; flex-shrink: 0; margin: 0 auto;">
      <img src="/img/lz/77572ccd6d008b29d211ba51a811c2542ca82ae8/full.webp" alt="بافت یقه هفت آکریل پنبه" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" />
    </div>
    <div style="flex: 1; min-width: 220px;">
      <span style="display: inline-block; background: #f3e8ff; color: #711f7e; font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 12px; margin-bottom: 6px;">لایه‌بندی پاییزه و زمستانه</span>
      <h4 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: #1a202c;">بافت یقه هفت آکریل پنبه</h4>
      <p style="margin: 0 0 12px 0; font-size: 13px; color: #4a5568; line-height: 1.7;">
        💡 <em>پیشنهاد استایلیست:</em> یقه هفت این بافت اجازه می‌دهد یقه شومیز زیری شما به زیبایی دیده شود و استایلی لایه‌ای و هوشمند خلق کند.
      </p>
      <a href="/products-item/بافت-یقه-هفت-آکریل-پنبه" target="_blank" style="display: inline-block; background: #711f7e; color: #ffffff; padding: 9px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; text-decoration: none;">
        مشاهده و خرید در مانگ &larr;
      </a>
    </div>
  </div>

  <hr style="border: 0; border-top: 1px solid #f3e8ff; margin: 32px 0;" />

  <h2 id="styling-formula" style="font-size: 22px; font-weight: 700; color: #711f7e; margin-top: 36px; margin-bottom: 16px;">
    فرمول ترکیب و استایل‌سازی
  </h2>
  <p>
    برای خلق استایل‌های متنوع از این ۵ آیتم، کافی است قانون <strong>تعادل فرم و رنگ</strong> را رعایت کنید:
  </p>
  <ul style="padding-right: 20px; margin-bottom: 24px; color: #4a5568;">
    <li style="margin-bottom: 8px;"><strong>تیپ اداری و رسمی:</strong> کت آوان + شلوار راسته ۷۶۵ + شومیز لیوسل + کفش لوفر چرم</li>
    <li style="margin-bottom: 8px;"><strong>تیپ کژوال آخر هفته:</strong> کت آوان + شلوار جین راسته + بافت یقه هفت + کتانی سفید</li>
    <li style="margin-bottom: 8px;"><strong>تیپ دانشگاه و روزمرگی:</strong> بافت پنبه‌ای روی شومیز + شلوار جین راسته + شال نخی خنثی</li>
  </ul>

  <hr style="border: 0; border-top: 1px solid #f3e8ff; margin: 32px 0;" />

  <h2 id="mistakes" style="font-size: 22px; font-weight: 700; color: #711f7e; margin-top: 36px; margin-bottom: 16px;">
    ۳ اشتباه رایج در ساخت کمد کپسولی
  </h2>
  <ol style="padding-right: 20px; margin-bottom: 24px; color: #4a5568;">
    <li style="margin-bottom: 8px;"><strong>خرید لباس‌های ترندی و موقتی:</strong> طرح‌های زودگذر بعد از چند ماه تکراری و غیرقابل استفاده می‌شوند.</li>
    <li style="margin-bottom: 8px;"><strong>نادیده گرفتن جنس پارچه:</strong> لباسی که سریع چروک شود یا بعد از دو بار شستشو پرز دهد، کمد کپسولی شما را مختل می‌کند.</li>
    <li style="margin-bottom: 8px;"><strong>تک‌رنگ بودن بیش از حد:</strong> لازم نیست همه چیز مشکی باشد؛ ترکیب تناژهای خاکی، شیری، کرم، سرمه‌ای و دودی شادابی بیشتری به استایل می‌دهد.</li>
  </ol>

  <div style="background: linear-gradient(135deg, #faf5ff 0%, #f3e8ff 100%); border: 1px solid #e9d8fd; border-radius: 12px; padding: 24px; text-align: center; margin-top: 40px;">
    <h3 style="margin-top: 0; color: #711f7e; font-size: 20px; font-weight: 700;">کمد کپسولی خود را با کالکشن مانگ بسازید</h3>
    <p style="color: #4a5568; max-width: 600px; margin: 10px auto 20px auto;">
      تمام آیتم‌های معرفی‌شده با کیفیت استاندارد و دوخت تمیز در مانگ موجود است تا بتوانید با کمترین تعداد، بیشترین تنوع را داشته باشید.
    </p>
    <a href="/products-category/all" style="display: inline-block; background-color: #711f7e; color: #ffffff; padding: 12px 28px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 15px; box-shadow: 0 4px 10px rgba(113, 31, 126, 0.25);">
      مشاهده محصولات مانگ &larr;
    </a>
  </div>
</div>
""".strip()

def run_sync():
    print("=== Updating Blog Article 1 (Capsule Wardrobe) ===")

    # 1. FileMedia banner
    fm, _ = FileMedia.objects.get_or_create(
        url=THUMB_URL,
        defaults={
            "file_name": "capsule-wardrobe-cover-fashion.webp",
            "tooltip_title": TITLE,
            "alternative": "کمد کپسولی مانگ",
            "upload_time": now,
            "used": True,
        }
    )

    # 2. Update Article ID 10
    article, _ = Article.objects.update_or_create(
        uniq_url=UNIQ_URL,
        defaults={
            "id": 10,
            "title": TITLE,
            "description": DESCRIPTION,
            "content": CONTENT_HTML,
            "thumbnail": THUMB_URL,
            "author_id": 1,
            "publish_date": now,
            "show_on_page": True,
            "view_count": 12,
            "is_deleted": False,
        }
    )
    print(f"Article 10 updated: {article.title}")

    # 3. Category
    cat, _ = BlogCategory.objects.get_or_create(id=1, defaults={"title": "مد و لباس", "is_deleted": False})
    ArticleBlogCategory.objects.get_or_create(article=article, category=cat)

    # 4. Tags
    for tag_name in ["مد و لباس", "کمد کپسولی", "استایل زنانه", "ترفندهای استایل", "شیک"]:
        tag, _ = ArticleTag.objects.get_or_create(name=tag_name, defaults={"is_deleted": False})
        ArticleTagRelation.objects.get_or_create(article=article, tag=tag)

    # 5. MediaAttachment
    TABLE_ARTICLES = 32
    MediaAttachment.objects.filter(table=TABLE_ARTICLES, record_id=article.id).delete()
    MediaAttachment.objects.create(
        table=TABLE_ARTICLES,
        record_id=article.id,
        media_url=THUMB_URL,
        is_video=False,
        alternative="کمد کپسولی مانگ",
        tooltip_title=TITLE,
        is_product_guid=False,
        is_deleted=False,
    )
    print("=== Article 1 Updated Successfully ===")

if __name__ == "__main__":
    run_sync()
