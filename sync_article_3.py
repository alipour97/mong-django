"""
Mong Blog Article Sync Script (Article #3: Business Casual Workwear Guide)
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
UNIQ_URL = "business-casual-workwear-style-guide"
TITLE = "استایل کارمندی و بیزینس کژوال زنانه"
DESCRIPTION = "چگونه با ترکیب مانتوهای کتی، شلوارهای راسته و شومیزهای اداری، استایل کاری شیک و راحتی بسازیم؟ راهنمای اصول بیزینس کژوال با کالکشن مانگ."
THUMB_URL = "https://cdn.mong.ir/9/webgeneral/9fee463e-b095-40ad-9be5-8243fbfc426b.webp"

CONTENT_HTML = """
<div class="article-content" style="line-height: 2.1; font-size: 16px; color: #2d3748;">
  <p class="lead" style="font-size: 18px; font-weight: 500; color: #1a202c; margin-bottom: 24px;">
    دوران روپوش‌های اداری خشک و خسته‌کننده به پایان رسیده است. امروزه در محیط‌های کاری، شرکت‌ها و دانشگاه‌ها، سبکی طرفدار دارد که در عین حفظ وقار و رسمیت حرفه‌ای، راحتی و آراستگی روزمره را به همراه داشته باشد؛ یعنی سبک محبوب <strong>«بیزینس کژوال» (Business Casual)</strong>.
  </p>

  <p>
    اما چطور می‌توان لباسی انتخاب کرد که هم مطابق با ضوابط کاری باشد و هم در جلسات مهم یا ساعات طولانی پشت میز نشستن، احساس خستگی و کلافگی ایجاد نکند؟ در این راهنما، اصول کلیدی پوشش حرفه‌ای و ۵ آیتم پیشنهادی از کالکشن‌های مانگ را بررسی می‌کنیم.
  </p>

  <hr style="border: 0; border-top: 1px solid #f3e8ff; margin: 32px 0;" />

  <h2 id="workwear-formula" style="font-size: 22px; font-weight: 700; color: #711f7e; margin-top: 36px; margin-bottom: 16px;">
    فرمول تعادل در پوشش کاری (قانون ۷۰/۳۰)
  </h2>
  <p>
    راز اصلی بیزینس کژوال ایجاد یک هماهنگی دقیق میان دو بخش است:
  </p>
  <div style="background-color: #faf5ff; border-right: 4px solid #711f7e; padding: 18px 24px; border-radius: 8px; margin: 20px 0;">
    <ul style="padding-right: 20px; margin: 0; color: #4a5568;">
      <li style="margin-bottom: 8px;"><strong>۷۰٪ رسمیت و ساختار:</strong> دوخت‌های تمیز، مانتوهای کتی اتوکشیده، شلوارهای راسته و رنگ‌های باوقار (سرمه‌ای، طوسی دودی، زیتونی، مشکی و شتری).</li>
      <li style="margin: 0;"><strong>۳۰٪ راحتی روزمره:</strong> پارچه‌های ضدچروک و خنک، کفش‌های لوفر طبی، شومیزهای تنفس‌پذیر و اکسسوری‌های مینیمال.</li>
    </ul>
  </div>

  <hr style="border: 0; border-top: 1px solid #f3e8ff; margin: 32px 0;" />

  <h2 id="office-items" style="font-size: 22px; font-weight: 700; color: #711f7e; margin-top: 36px; margin-bottom: 16px;">
    آیتم‌های کلیدی کمد اداری با کالکشن مانگ
  </h2>

  <!-- Item 1: Cotton Blazer -->
  <h3 style="font-size: 18px; font-weight: 700; color: #2d3748; margin-top: 28px; margin-bottom: 12px;">
    ۱. مانتو کتی کتان (آچارفرانسه روزهای کاری)
  </h3>
  <p>
    مانتو کتی کتان بهترین جایگزین برای مانتوهای بلند و دست‌وپاگیر است. با قواره منظم و ایستایی شکیل، به راحتی با شلوار پارچه‌ای یا شال ساده اداری هماهنگ می‌شود.
  </p>

  <!-- Product Card 1 -->
  <div style="display: flex; flex-wrap: wrap; gap: 16px; background: #ffffff; border: 1px solid #f3e8ff; border-radius: 12px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 12px rgba(113, 31, 126, 0.05); align-items: center;">
    <div style="width: 120px; height: 160px; border-radius: 8px; overflow: hidden; background: #faf5ff; flex-shrink: 0; margin: 0 auto;">
      <img src="/img/lz/7150efab1781b9565e31a8f388d1c0730e86565e/full.webp" alt="کت کتان زنانه مانگ" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" />
    </div>
    <div style="flex: 1; min-width: 220px;">
      <span style="display: inline-block; background: #f3e8ff; color: #711f7e; font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 12px; margin-bottom: 6px;">پایه استایل اداری شیک</span>
      <h4 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: #1a202c;">کت کتان زنانه</h4>
      <p style="margin: 0 0 12px 0; font-size: 13px; color: #4a5568; line-height: 1.7;">
        💡 <em>پیشنهاد استایلیست:</em> الیاف کتان سبک و تن‌خور استاندارد این کت، امکان پوشش آسوده در طول ساعت‌های متمادی کار را فراهم می‌کند.
      </p>
      <a href="/products-item/كت-كتان" target="_blank" style="display: inline-block; background: #711f7e; color: #ffffff; padding: 9px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; text-decoration: none;">
        مشاهده و خرید در مانگ &larr;
      </a>
    </div>
  </div>

  <!-- Item 2: Vest & Trouser Set -->
  <h3 style="font-size: 18px; font-weight: 700; color: #2d3748; margin-top: 32px; margin-bottom: 12px;">
    ۲. ست وست جلیقه و شلوار (مدرن و متمایز)
  </h3>
  <p>
    برای شرکت‌های نوآور، دفاتر معماری و استارتاپی، ترکیب جلیقه بلند روی شومیز، استایلی نو و در عین حال کاملاً باوقار و پوشیده ایجاد می‌کند.
  </p>

  <!-- Product Card 2 -->
  <div style="display: flex; flex-wrap: wrap; gap: 16px; background: #ffffff; border: 1px solid #f3e8ff; border-radius: 12px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 12px rgba(113, 31, 126, 0.05); align-items: center;">
    <div style="width: 120px; height: 160px; border-radius: 8px; overflow: hidden; background: #faf5ff; flex-shrink: 0; margin: 0 auto;">
      <img src="/img/lz/ed146f6f2ed1ae64c2966eda78f1e13d2bb58fe6/full.webp" alt="وست جلیقه شلوار راز" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" />
    </div>
    <div style="flex: 1; min-width: 220px;">
      <span style="display: inline-block; background: #f3e8ff; color: #711f7e; font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 12px; margin-bottom: 6px;">ترند محیط‌های کاری مدرن</span>
      <h4 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: #1a202c;">ست وست جلیقه و شلوار راز</h4>
      <p style="margin: 0 0 12px 0; font-size: 13px; color: #4a5568; line-height: 1.7;">
        💡 <em>پیشنهاد استایلیست:</em> خطوط کشیده جلیقه بر روی شومیز آستین‌بلند، قد اندام را کشیده‌تر نشان داده و تنوع چشم‌نوازی در کمد اداری می‌سازد.
      </p>
      <a href="/products-item/وست-جليقه-شلوار-راز" target="_blank" style="display: inline-block; background: #711f7e; color: #ffffff; padding: 9px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; text-decoration: none;">
        مشاهده و خرید در مانگ &larr;
      </a>
    </div>
  </div>

  <!-- Item 3: Gabardine Pants -->
  <h3 style="font-size: 18px; font-weight: 700; color: #2d3748; margin-top: 32px; margin-bottom: 12px;">
    ۳. شلوار گاباردین راسته (تضمین راحتی پشت میز)
  </h3>
  <p>
    شلواری که خط اتوی آن با نشستن روی صندلی اداری از بین نرود و احساس فشار به کمر نیاورد، ضروری‌ترین سرمایه‌گذاری برای روزهای کاری است.
  </p>

  <!-- Product Card 3 -->
  <div style="display: flex; flex-wrap: wrap; gap: 16px; background: #ffffff; border: 1px solid #f3e8ff; border-radius: 12px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 12px rgba(113, 31, 126, 0.05); align-items: center;">
    <div style="width: 120px; height: 160px; border-radius: 8px; overflow: hidden; background: #faf5ff; flex-shrink: 0; margin: 0 auto;">
      <img src="/img/lz/110c5b88d25752aeb35e2b07c387b12e72c30d6d/full.webp" alt="شلوار گاباردین جلو دوخت دار مدل ۷۱۱" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" />
    </div>
    <div style="flex: 1; min-width: 220px;">
      <span style="display: inline-block; background: #f3e8ff; color: #711f7e; font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 12px; margin-bottom: 6px;">ضدچروک و بادوام</span>
      <h4 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: #1a202c;">شلوار گاباردین جلو دوخت‌دار</h4>
      <p style="margin: 0 0 12px 0; font-size: 13px; color: #4a5568; line-height: 1.7;">
        💡 <em>پیشنهاد استایلیست:</em> دوخت عمودی جلوی شلوار علاوه بر استحکام فرم، خط دید عمودی ایجاد کرده و پاها را باریک‌تر و کشیده‌تر نشان می‌دهد.
      </p>
      <a href="/products-item/شلوار-گاباردين-جلو-دوخت-دار-711" target="_blank" style="display: inline-block; background: #711f7e; color: #ffffff; padding: 9px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; text-decoration: none;">
        مشاهده و خرید در مانگ &larr;
      </a>
    </div>
  </div>

  <!-- Item 4: Office Blouse -->
  <h3 style="font-size: 18px; font-weight: 700; color: #2d3748; margin-top: 32px; margin-bottom: 12px;">
    ۴. شومیز خنک و تنفس‌پذیر زیر کت
  </h3>
  <p>
    شومیزی با یقه تمیز و ایستاده، رسمیت کت شما را تکمیل می‌کند و مانع از احساس گرمای کلافه‌کننده در محیط‌های بسته اداری می‌شود.
  </p>

  <!-- Product Card 4 -->
  <div style="display: flex; flex-wrap: wrap; gap: 16px; background: #ffffff; border: 1px solid #f3e8ff; border-radius: 12px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 12px rgba(113, 31, 126, 0.05); align-items: center;">
    <div style="width: 120px; height: 160px; border-radius: 8px; overflow: hidden; background: #faf5ff; flex-shrink: 0; margin: 0 auto;">
      <img src="/img/lz/50c6aefd4c77ce9c60c88a4abf11dd981e15be49/full.webp" alt="شومیز ویانا مانگ" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" />
    </div>
    <div style="flex: 1; min-width: 220px;">
      <span style="display: inline-block; background: #f3e8ff; color: #711f7e; font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 12px; margin-bottom: 6px;">لایه زیرین تنفس‌پذیر</span>
      <h4 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: #1a202c;">شومیز مدل ویانا</h4>
      <p style="margin: 0 0 12px 0; font-size: 13px; color: #4a5568; line-height: 1.7;">
        💡 <em>پیشنهاد استایلیست:</em> تن‌خور آزاد و برش سبک ویانا، بدون ایجاد حجم اضافی در زیر مانتو یا کت قرار می‌گیرد و فرم یقه را مرتب نگه می‌دارد.
      </p>
      <a href="/products-item/شوميز-ويانا" target="_blank" style="display: inline-block; background: #711f7e; color: #ffffff; padding: 9px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; text-decoration: none;">
        مشاهده و خرید در مانگ &larr;
      </a>
    </div>
  </div>

  <!-- Item 5: Straight Denim for Casual Days -->
  <h3 style="font-size: 18px; font-weight: 700; color: #2d3748; margin-top: 32px; margin-bottom: 12px;">
    ۵. شلوار جین راسته تیره (روزهای نیمه‌رسمی)
  </h3>
  <p>
    برای روزهای خلوت‌تر هفته مانند چهارشنبه‌ها، شلوار جین راسته تیره بدون هیچ‌گونه زاپ و پارگی، انتخابی عالی در کنار کت اداری است.
  </p>

  <!-- Product Card 5 -->
  <div style="display: flex; flex-wrap: wrap; gap: 16px; background: #ffffff; border: 1px solid #f3e8ff; border-radius: 12px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 12px rgba(113, 31, 126, 0.05); align-items: center;">
    <div style="width: 120px; height: 160px; border-radius: 8px; overflow: hidden; background: #faf5ff; flex-shrink: 0; margin: 0 auto;">
      <img src="/img/lz/de90aab90691537a98f0e48bdd330faae6772923/full.webp" alt="شلوار جین راسته ترک" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" />
    </div>
    <div style="flex: 1; min-width: 220px;">
      <span style="display: inline-block; background: #f3e8ff; color: #711f7e; font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 12px; margin-bottom: 6px;">انتخاب نیمه‌رسمی روزهای پایانی هفته</span>
      <h4 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: #1a202c;">شلوار جین راسته ترک</h4>
      <p style="margin: 0 0 12px 0; font-size: 13px; color: #4a5568; line-height: 1.7;">
        💡 <em>پیشنهاد استایلیست:</em> رنگ تیره یکدست و بدون سایه‌روشن تند، مرز میان استایل رسمی و کژوال را به زیبایی حفظ می‌کند.
      </p>
      <a href="/products-item/شلوار-جین-راسته-ترک" target="_blank" style="display: inline-block; background: #711f7e; color: #ffffff; padding: 9px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; text-decoration: none;">
        مشاهده و خرید در مانگ &larr;
      </a>
    </div>
  </div>

  <hr style="border: 0; border-top: 1px solid #f3e8ff; margin: 32px 0;" />

  <h2 id="shoes-accessories" style="font-size: 22px; font-weight: 700; color: #711f7e; margin-top: 36px; margin-bottom: 16px;">
    راهنمای کفش و اکسسوری
  </h2>
  <ul style="padding-right: 20px; margin-bottom: 24px; color: #4a5568;">
    <li style="margin-bottom: 10px;"><strong>کفش مناسب کار:</strong> پاشنه‌های باریک را کنار بگذارید؛ کفش‌های لوفر چرم (Loafers)، آکسفورد، کالج‌های لژدار و کتانی‌های چرمی تک‌رنگ و تمیز، بهترین همراهان ساعت‌های کاری هستند.</li>
    <li style="margin-bottom: 10px;"><strong>کیف ساختارمند:</strong> یک کیف چرمی مدل توت (Tote Bag) با فضای کافی برای لپ‌تاپ و مدارک، به استایل شما ظاهری منضبط و مدیرانه می‌بخشد.</li>
    <li style="margin-bottom: 10px;"><strong>شال و مقنعه:</strong> مقنعه کرپ ریزش‌دار با خط اتوی منظم، یا شال نخی تیره بدون طرح‌های شلوغ، هماهنگی بی‌نقصی با مانتو کتی می‌سازد.</li>
  </ul>

  <hr style="border: 0; border-top: 1px solid #f3e8ff; margin: 32px 0;" />

  <h2 id="faq" style="font-size: 22px; font-weight: 700; color: #711f7e; margin-top: 36px; margin-bottom: 16px;">
    پاسخ به پرسش‌های متداول
  </h2>
  <div style="margin-bottom: 18px;">
    <h4 style="margin: 0 0 6px 0; color: #711f7e; font-size: 16px;">آیا پوشیدن شلوار جین در محیط کار مجاز است؟</h4>
    <p style="margin: 0; font-size: 14px; color: #4a5568;">
      بله، مشروط بر اینکه جین راسته یا مام‌فیت تیره (سرمه‌ای یا مشکی)، کاملاً ساده و بدون هرگونه زاپ یا سنگ‌شور تند باشد و همراه با مانتو کتی پوشیده شود.
    </p>
  </div>
  <div style="margin-bottom: 18px;">
    <h4 style="margin: 0 0 6px 0; color: #711f7e; font-size: 16px;">بهترین رنگ‌ها برای کمد اداری کدامند؟</h4>
    <p style="margin: 0; font-size: 14px; color: #4a5568;">
      رنگ‌های پایه شامل سرمه‌ای، طوسی دودی، زیتونی خاکی، شتری و مشکی هستند. برای شومیز زیر کت نیز رنگ‌های ملایم مثل استخوانی، آبی روشن یا سدری بهترین انتخابند.
    </p>
  </div>

  <div style="background: linear-gradient(135deg, #faf5ff 0%, #f3e8ff 100%); border: 1px solid #e9d8fd; border-radius: 12px; padding: 24px; text-align: center; margin-top: 40px;">
    <h3 style="margin-top: 0; color: #711f7e; font-size: 20px; font-weight: 700;">استایل کاری منحصر‌به‌فرد خود را با مانگ بسازید</h3>
    <p style="color: #4a5568; max-width: 600px; margin: 10px auto 20px auto;">
      مجموعه مانتوهای کتی، شلوارهای راسته و شومیزهای اداری مانگ، همراه مطمئن و شیک روزهای کاری شما هستند.
    </p>
    <a href="/products-category/all" style="display: inline-block; background-color: #711f7e; color: #ffffff; padding: 12px 28px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 15px; box-shadow: 0 4px 10px rgba(113, 31, 126, 0.25);">
      مشاهده کالکشن پوشاک مانگ &larr;
    </a>
  </div>
</div>
""".strip()

def run_sync():
    print("=== Updating Blog Article 3 (Business Casual Guide) ===")

    # 1. FileMedia banner
    fm, _ = FileMedia.objects.get_or_create(
        url=THUMB_URL,
        defaults={
            "file_name": "business-casual-cover-fashion.webp",
            "tooltip_title": TITLE,
            "alternative": "استایل اداری و بیزینس کژوال مانگ",
            "upload_time": now,
            "used": True,
        }
    )

    # 2. Update Article ID 12
    article, _ = Article.objects.update_or_create(
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
    print(f"Article 12 updated: {article.title}")

    # 3. Category
    cat, _ = BlogCategory.objects.get_or_create(id=1, defaults={"title": "مد و لباس", "is_deleted": False})
    ArticleBlogCategory.objects.get_or_create(article=article, category=cat)

    # 4. Tags
    for tag_name in ["مد و لباس", "استایل اداری", "بیزینس کژوال", "استایل زنانه", "مانتو کتی", "ترفندهای استایل", "شیک"]:
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
        alternative="استایل اداری مانگ",
        tooltip_title=TITLE,
        is_product_guid=False,
        is_deleted=False,
    )
    print("=== Article 3 Updated Successfully ===")

if __name__ == "__main__":
    run_sync()
