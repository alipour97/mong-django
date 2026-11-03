"""
Mong Blog Article Sync Script (Article #2: Body Shape & Manteau Guide)
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
UNIQ_URL = "how-to-dress-for-your-body-type"
TITLE = "راهنمای انتخاب مانتو بر اساس فرم اندام"
DESCRIPTION = "چطور فرم اندام خود را بشناسیم و بهترین مدل مانتو را برای ایجاد تعادل در اندام انتخاب کنیم؟ راهنمای کاربردی با مدل‌های موجود در مانگ."
THUMB_URL = "https://cdn.mong.ir/9/webgeneral/1740c94c-c917-4e58-bb8b-da2850402af3.webp"

CONTENT_HTML = """
<div class="article-content" style="line-height: 2.1; font-size: 16px; color: #2d3748;">
  <p class="lead" style="font-size: 18px; font-weight: 500; color: #1a202c; margin-bottom: 24px;">
    حتماً برای شما هم پیش آمده که مانتویی را در ویترین یا تن فرد دیگری تحسین کنید، اما بعد از پرو احساس کنید روی تن شما آن جلوه دلخواه را ندارد. 
    راز این موضوع در وزن یا سایز نیست، بلکه در یک اصل اساسی نهفته است: <strong>«تعادل تناسبات اندام»</strong>.
  </p>

  <p>
    مانتو و پالتو در پوشش روزمره قاب اصلی ظاهر شما هستند. با انتخاب درست برش یقه، قد مانتو و فرم سرشانه، می‌توانید ویژگی‌های زیبای اندام خود را برجسته کرده و خطوط نامتقارن را به بهترین شکل متعادل کنید. در این راهنما، تکنیک‌های انتخاب مانتو را برای ۴ تیپ بدنی اصلی مرور می‌کنیم.
  </p>

  <hr style="border: 0; border-top: 1px solid #f3e8ff; margin: 32px 0;" />

  <h2 id="quick-test" style="font-size: 22px; font-weight: 700; color: #711f7e; margin-top: 36px; margin-bottom: 16px;">
    شناخت سریع فرم اندام
  </h2>
  <p>
    روبروی آینه قدی بایستید و به نسبت سه بخش توجه کنید: <strong>عرض شانه، باریکی کمر و پهنای باسن</strong>:
  </p>
  <div style="background-color: #faf5ff; border-right: 4px solid #711f7e; padding: 18px 24px; border-radius: 8px; margin: 20px 0;">
    <ul style="padding-right: 20px; margin: 0; color: #4a5568;">
      <li style="margin-bottom: 8px;"><strong>گلابی:</strong> باسن و ران‌ها پهن‌تر از سرشانه‌هاست و خط کمر مشخص است.</li>
      <li style="margin-bottom: 8px;"><strong>سیبی:</strong> بالاتنه و میان‌تنه پرتر است و خط کمر تفکیک کمتری دارد.</li>
      <li style="margin-bottom: 8px;"><strong>ساعت شنی:</strong> عرض شانه و باسن متعادل بوده و کمر کاملاً باریک است.</li>
      <li style="margin: 0;"><strong>مستطیلی:</strong> عرض شانه، کمر و باسن در یک امتداد و بدون انحنای محسوس است.</li>
    </ul>
  </div>

  <hr style="border: 0; border-top: 1px solid #f3e8ff; margin: 32px 0;" />

  <h2 id="pear-shape" style="font-size: 22px; font-weight: 700; color: #711f7e; margin-top: 36px; margin-bottom: 16px;">
    ۱. اندام گلابی (مثلثی)
  </h2>
  <p>
    برای اندام گلابی، کلید اصلی جلب توجه به سمت بالاتنه و سرشانه‌هاست تا تعادل زیبایی با پهنای باسن برقرار شود. مانتوهای کتی با سرشانه‌های قرص، یقه‌های پهن انگلیسی یا آرشال، گزینه‌ای ایده‌آل هستند.
  </p>

  <!-- Product Card 1 -->
  <div style="display: flex; flex-wrap: wrap; gap: 16px; background: #ffffff; border: 1px solid #f3e8ff; border-radius: 12px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 12px rgba(113, 31, 126, 0.05); align-items: center;">
    <div style="width: 120px; height: 160px; border-radius: 8px; overflow: hidden; background: #faf5ff; flex-shrink: 0; margin: 0 auto;">
      <img src="/img/lz/e5417c670ae0d71ac202bdb6e7a5841101e0909a/full.webp" alt="کت آستردار فریال برجسته" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" />
    </div>
    <div style="flex: 1; min-width: 220px;">
      <span style="display: inline-block; background: #f3e8ff; color: #711f7e; font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 12px; margin-bottom: 6px;">پیشنهاد ویژه اندام گلابی</span>
      <h4 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: #1a202c;">کت آستردار فریال برجسته</h4>
      <p style="margin: 0 0 12px 0; font-size: 13px; color: #4a5568; line-height: 1.7;">
        💡 <em>پیشنهاد استایلیست:</em> سرشانه‌های ساختارمند و بافت ژاکارد این کت، توجه را به بالاتنه هدایت کرده و تعادل اندام را کامل می‌کند.
      </p>
      <a href="/products-item/كت-آستردار-فريال-برجسته" target="_blank" style="display: inline-block; background: #711f7e; color: #ffffff; padding: 9px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; text-decoration: none;">
        مشاهده و خرید در مانگ &larr;
      </a>
    </div>
  </div>

  <hr style="border: 0; border-top: 1px solid #f3e8ff; margin: 32px 0;" />

  <h2 id="apple-shape" style="font-size: 22px; font-weight: 700; color: #711f7e; margin-top: 36px; margin-bottom: 16px;">
    ۲. اندام سیبی (گرد)
  </h2>
  <p>
    اگر میان‌تنه پرتری دارید، هدف اصلی ایجاد <strong>خطوط کشیده عمودی</strong> است. مانتوهای جلوباز، یقه‌های کشیده هفت یا تک‌دکمه‌های عمودی، بالاتنه را کشیده‌تر و لاغرتر نشان می‌دهند.
  </p>

  <!-- Product Card 2 -->
  <div style="display: flex; flex-wrap: wrap; gap: 16px; background: #ffffff; border: 1px solid #f3e8ff; border-radius: 12px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 12px rgba(113, 31, 126, 0.05); align-items: center;">
    <div style="width: 120px; height: 160px; border-radius: 8px; overflow: hidden; background: #faf5ff; flex-shrink: 0; margin: 0 auto;">
      <img src="/img/lz/6498efc99a7460968a8707d3d28cf4b4cd0bec89/full.webp" alt="کت دو جیب تک دکمه هرمس" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" />
    </div>
    <div style="flex: 1; min-width: 220px;">
      <span style="display: inline-block; background: #f3e8ff; color: #711f7e; font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 12px; margin-bottom: 6px;">خطوط لاغرکننده و کشیده</span>
      <h4 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: #1a202c;">کت دو جیب تک دکمه هرمس</h4>
      <p style="margin: 0 0 12px 0; font-size: 13px; color: #4a5568; line-height: 1.7;">
        💡 <em>پیشنهاد استایلیست:</em> برش راسته و تک‌دکمه عمودی این کت، خط دید را کشیده کرده و پهنای شکم و پهلو را محو می‌کند.
      </p>
      <a href="/products-item/كت-دو-جيب-تك-دكمه-هرمس" target="_blank" style="display: inline-block; background: #711f7e; color: #ffffff; padding: 9px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; text-decoration: none;">
        مشاهده و خرید در مانگ &larr;
      </a>
    </div>
  </div>

  <hr style="border: 0; border-top: 1px solid #f3e8ff; margin: 32px 0;" />

  <h2 id="hourglass-shape" style="font-size: 22px; font-weight: 700; color: #711f7e; margin-top: 36px; margin-bottom: 16px;">
    ۳. اندام ساعت شنی
  </h2>
  <p>
    باریکی طبیعی کمر در این اندام بهترین نقطه قوت است. مانتوها و بارانی‌های کمربنددار، بارانی‌های ترنچ کلاسیک و کت‌های فیت روی کمر، این انحنا را به زیباترین شکل نمایان می‌کنند.
  </p>

  <!-- Product Card 3 -->
  <div style="display: flex; flex-wrap: wrap; gap: 16px; background: #ffffff; border: 1px solid #f3e8ff; border-radius: 12px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 12px rgba(113, 31, 126, 0.05); align-items: center;">
    <div style="width: 120px; height: 160px; border-radius: 8px; overflow: hidden; background: #faf5ff; flex-shrink: 0; margin: 0 auto;">
      <img src="/img/lz/72eafcd03b0053a2a5fe1dca72b770f59ec5e8d1/full.webp" alt="بارانی کوتاه سانتانا ۴ دکمه" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" />
    </div>
    <div style="flex: 1; min-width: 220px;">
      <span style="display: inline-block; background: #f3e8ff; color: #711f7e; font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 12px; margin-bottom: 6px;">تاکید بر انحنای زیبای کمر</span>
      <h4 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: #1a202c;">بارانی کوتاه سانتانا ۴ دکمه</h4>
      <p style="margin: 0 0 12px 0; font-size: 13px; color: #4a5568; line-height: 1.7;">
        💡 <em>پیشنهاد استایلیست:</em> فیت استاندارد و دکمه‌های متقارن این بارانی، تقارن طبیعی اندام ساعت شنی را به بهترین شکل نشان می‌دهد.
      </p>
      <a href="/products-item/بارانی-کوتاه-سانتانا-4-دکمه" target="_blank" style="display: inline-block; background: #711f7e; color: #ffffff; padding: 9px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; text-decoration: none;">
        مشاهده و خرید در مانگ &larr;
      </a>
    </div>
  </div>

  <hr style="border: 0; border-top: 1px solid #f3e8ff; margin: 32px 0;" />

  <h2 id="rectangle-shape" style="font-size: 22px; font-weight: 700; color: #711f7e; margin-top: 36px; margin-bottom: 16px;">
    ۴. اندام مستطیلی
  </h2>
  <p>
    در اندام مستطیلی هدف اصلی <strong>ایجاد خط کمر و شکستن خط مستقیم</strong> است. پوشیدن وست، جلیقه و استایل‌های لایه‌لایه روی شومیز، خطوط بصری چشم‌نوازی خلق کرده و اندام را فرم‌دار می‌کند.
  </p>

  <!-- Product Card 4 -->
  <div style="display: flex; flex-wrap: wrap; gap: 16px; background: #ffffff; border: 1px solid #f3e8ff; border-radius: 12px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 12px rgba(113, 31, 126, 0.05); align-items: center;">
    <div style="width: 120px; height: 160px; border-radius: 8px; overflow: hidden; background: #faf5ff; flex-shrink: 0; margin: 0 auto;">
      <img src="/img/lz/84f963ef9c00d48d74ec1efb8b165cc6a9340cc3/full.webp" alt="وست فوتر جناقی" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" />
    </div>
    <div style="flex: 1; min-width: 220px;">
      <span style="display: inline-block; background: #f3e8ff; color: #711f7e; font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 12px; margin-bottom: 6px;">ایجاد ساختار و خط کمر</span>
      <h4 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: #1a202c;">وست فوتر جناقی</h4>
      <p style="margin: 0 0 12px 0; font-size: 13px; color: #4a5568; line-height: 1.7;">
        💡 <em>پیشنهاد استایلیست:</em> پوشیدن این وست جناقی روی شومیز، بُعد و حجم زیبایی به تنه می‌دهد و یکنواختی اندام مستقیم را می‌شکند.
      </p>
      <a href="/products-item/وست-فوتر-جناقي" target="_blank" style="display: inline-block; background: #711f7e; color: #ffffff; padding: 9px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; text-decoration: none;">
        مشاهده و خرید در مانگ &larr;
      </a>
    </div>
  </div>

  <hr style="border: 0; border-top: 1px solid #f3e8ff; margin: 32px 0;" />

  <h2 id="golden-rules" style="font-size: 22px; font-weight: 700; color: #711f7e; margin-top: 36px; margin-bottom: 16px;">
    نکات طلایی قد و پارچه
  </h2>
  <ul style="padding-right: 20px; margin-bottom: 24px; color: #4a5568;">
    <li style="margin-bottom: 8px;"><strong>قد مانتو:</strong> لبه مانتو نباید دقیقاً روی پهن‌ترین بخش ران تمام شود؛ یا بالای زانو یا زیر زانو بهترین جلوه را دارد.</li>
    <li style="margin-bottom: 8px;"><strong>شلوار مکمل:</strong> برای مانتوهای آزاد کتی، یک شلوار راسته خوش‌دوخت مانند <a href="/products-item/شلوار-بزياق-دو-سگك" style="color: #711f7e; font-weight: 600; text-decoration: underline;" target="_blank">شلوار بزیاق دو سگک</a> تعادل بی‌نقصی در پایین‌تنه ایجاد می‌کند.</li>
    <li style="margin-bottom: 8px;"><strong>جنس پارچه:</strong> پارچه‌های آستردار و سفت برای ساختن زاویه شانه عالی هستند و پارچه‌های لخت و ریزش‌دار برای کشیده‌تر نشان دادن میان‌تنه معجزه می‌کنند.</li>
  </ul>

  <div style="background: linear-gradient(135deg, #faf5ff 0%, #f3e8ff 100%); border: 1px solid #e9d8fd; border-radius: 12px; padding: 24px; text-align: center; margin-top: 40px;">
    <h3 style="margin-top: 0; color: #711f7e; font-size: 20px; font-weight: 700;">مانتوی متناسب با اندام خود را در مانگ بیابید</h3>
    <p style="color: #4a5568; max-width: 600px; margin: 10px auto 20px auto;">
      هر محصول در مانگ با برش‌های مهندسی‌شده و پارچه‌های باکیفیت طراحی شده تا زیبایی طبیعی شما را به بهترین شکل جلوه دهد.
    </p>
    <a href="/products-category/all" style="display: inline-block; background-color: #711f7e; color: #ffffff; padding: 12px 28px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 15px; box-shadow: 0 4px 10px rgba(113, 31, 126, 0.25);">
      مشاهده کالکشن مانتوهای مانگ &larr;
    </a>
  </div>
</div>
""".strip()

def run_sync():
    print("=== Updating Blog Article 2 (Body Shape Guide) ===")

    # 1. FileMedia banner
    fm, _ = FileMedia.objects.get_or_create(
        url=THUMB_URL,
        defaults={
            "file_name": "body-shape-cover-fashion.webp",
            "tooltip_title": TITLE,
            "alternative": "راهنمای فرم اندام مانگ",
            "upload_time": now,
            "used": True,
        }
    )

    # 2. Update Article ID 11
    article, _ = Article.objects.update_or_create(
        uniq_url=UNIQ_URL,
        defaults={
            "id": 11,
            "title": TITLE,
            "description": DESCRIPTION,
            "content": CONTENT_HTML,
            "thumbnail": THUMB_URL,
            "author_id": 1,
            "publish_date": now,
            "show_on_page": True,
            "view_count": 10,
            "is_deleted": False,
        }
    )
    print(f"Article 11 updated: {article.title}")

    # 3. Category
    cat, _ = BlogCategory.objects.get_or_create(id=1, defaults={"title": "مد و لباس", "is_deleted": False})
    ArticleBlogCategory.objects.get_or_create(article=article, category=cat)

    # 4. Tags
    for tag_name in ["مد و لباس", "فرم اندام", "انتخاب مانتو", "استایل زنانه", "مانتو کتی", "ترفندهای استایل", "شیک"]:
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
        alternative="راهنمای فرم اندام مانگ",
        tooltip_title=TITLE,
        is_product_guid=False,
        is_deleted=False,
    )
    print("=== Article 2 Updated Successfully ===")

if __name__ == "__main__":
    run_sync()
