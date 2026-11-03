"""
Mong Blog Article Sync Script (Article #2: Body Types & Silhouette Guide)
Usage on Runflare (or local):
    python manage.py shell < sync_article_2.py
    or
    python sync_article_2.py
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
UNIQ_URL = "how-to-dress-for-your-body-type"
TITLE = "راهنمای جامع فرم اندام و انتخاب مانتو: چگونه بهترین مانتو را برای تیپ بدنی خود انتخاب کنیم؟"
DESCRIPTION = "چطور فرم اندام خود را بشناسیم و متناسب‌ترین مانتو، پالتو و شلوار را انتخاب کنیم؟ راهنمای کامل استایل بر اساس فرم‌های ساعت شنی، گلابی، سیبی و مستطیلی با کالکشن مانگ."
THUMB_URL = "https://cdn.mong.ir/9/webgeneral/515367c0-88c4-4381-9796-63f4b512cc75.webp"

CONTENT_HTML = """
<div class="article-content" style="line-height: 2.1; font-size: 16px; color: #2d3748;">
  <p class="lead" style="font-size: 18px; font-weight: 500; color: #1a202c; margin-bottom: 24px;">
    آیا تا به حال مانتویی را در ویترین یا تن یک مدل دیده‌اید که مجذوب آن شوید، اما وقتی آن را پرو می‌کنید، احساس کنید آن‌طور که باید روی تن شما نمی‌نشیند؟ 
    پاسخ این معما در سایز یا وزن شما نیست؛ بلکه در یک اصل اساسی در دنیای طراحی لباس نهفته است: <strong>«تعادل تناسبات اندام» (Body Silhouette Balance)</strong>.
  </p>

  <p>
    در فرهنگ پوشش ایرانی، مانتو و پالتو قاب اصلی استایل بیرونی شما هستند. انتخاب قد، برش سرشانه، گشادی پایین‌تنه و حتی نوع یقه مانتو می‌تواند شما را کشیده‌تر، متناسب‌تر و بسیار شیک‌تر نشان دهد. در این راهنمای تخصصی از <strong>تیم استایلینگ دپارتمان استور مانگ</strong>، روش گام‌به‌گام شناخت فرم اندام و تکنیک‌های انتخاب بهترین مدل مانتو را متناسب با کالکشن‌های روز مانگ با هم مرور می‌کنیم.
  </p>

  <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 32px 0;" />

  <h2 id="test-body-shape" style="font-size: 22px; font-weight: 700; color: #1a202c; margin-top: 36px; margin-bottom: 16px;">
    تست ۳ دقیقه‌ای: فرم اندام شما کدام است؟
  </h2>
  <p>
    روبروی یک آینه قدی با لباسی جذب بایستید و به نسبت سه نقطه کلیدی بدنتان توجه کنید: <strong>عرض سرشانه‌ها، باریکی کمر و پهنای باسن</strong>.
  </p>
  <div style="background-color: #f7fafc; border-right: 4px solid #3182ce; padding: 18px 24px; border-radius: 8px; margin: 20px 0;">
    <ul style="padding-right: 20px; margin: 0;">
      <li style="margin-bottom: 8px;"><strong>اندام گلابی (مثلثی):</strong> عرض باسن و ران‌ها پهن‌تر از سرشانه‌هاست و خط کمر مشخص است.</li>
      <li style="margin-bottom: 8px;"><strong>اندام سیبی (گرد):</strong> بالاتنه و میان‌تنه پرتر است، خط کمر تفکیک‌نشده‌تر بوده و پاها نسبتاً کشیده و ظریف‌ترند.</li>
      <li style="margin-bottom: 8px;"><strong>اندام ساعت شنی:</strong> عرض سرشانه و باسن تقریباً یکسان است و خط کمر باریک و کاملاً برجسته است.</li>
      <li style="margin-bottom: 8px;"><strong>اندام مستطیلی:</strong> عرض شانه، کمر و باسن در یک امتداد است و انحناهای کمتری به چشم می‌خورد.</li>
      <li style="margin: 0;"><strong>اندام مثلث وارونه:</strong> سرشانه‌ها یا سینه پهن‌تر از باسن است و پایین‌تنه باریک‌تر دیده می‌شود.</li>
    </ul>
  </div>

  <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 32px 0;" />

  <h2 id="pear-body-type" style="font-size: 22px; font-weight: 700; color: #1a202c; margin-top: 36px; margin-bottom: 16px;">
    ۱. اندام گلابی: چگونه تعادل بسازیم؟
  </h2>
  <p>
    بسیاری از بانوان ایرانی دارای اندام گلابی هستند. کلید طلایی شیک‌پوشی برای این اندام، <strong>جلب توجه به سمت بالاتنه و سرشانه‌ها</strong> و رها کردن ملایم پارچه روی پایین‌تنه است.
  </p>
  <p>
    <strong>مانتوهای مناسب:</strong> مانتوهای کتی با سرشانه‌های قرص، کت‌های دارای یقه پهن (مثل یقه انگلیسی یا آرشال پهن)، و مانتوهای مدل فون (A-Line) که از کمر به پایین کلوش ملایم دارند. از پوشیدن مانتوهای با جیب‌های حجیم روی باسن خودداری کنید.
  </p>

  <!-- Product Card: Pear shape recommendation -->
  <div style="display: flex; flex-wrap: wrap; gap: 16px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); align-items: center;">
    <div style="width: 130px; height: 175px; border-radius: 8px; overflow: hidden; background: #f7fafc; flex-shrink: 0; margin: 0 auto;">
      <img src="https://cdn.mong.ir/9/webgeneral/515367c0-88c4-4381-9796-63f4b512cc75.webp" alt="کت زنانه مدل سیران" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" />
    </div>
    <div style="flex: 1; min-width: 220px;">
      <span style="display: inline-block; background: #ebf8ff; color: #2b6cb0; font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 12px; margin-bottom: 6px;">پیشنهاد ویژه اندام گلابی</span>
      <h4 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: #1a202c;">کت زنانه مدل سیران</h4>
      <p style="margin: 0 0 12px 0; font-size: 13px; color: #4a5568; line-height: 1.7;">
        💡 <em>تحلیل استایل مانگ:</em> دوخت دقیق سرشانه و یقه شکیل این کت، خط شانه را تقویت کرده و تناسبی چشم‌نواز با پهنای باسن برقرار می‌کند.
      </p>
      <a href="/products-item/کت-سیران" target="_blank" style="display: inline-block; background: #3182ce; color: #ffffff; padding: 8px 16px; border-radius: 6px; font-size: 13px; font-weight: 600; text-decoration: none;">
        مشاهده و خرید کت سیران در مانگ &larr;
      </a>
    </div>
  </div>

  <h2 id="apple-body-type" style="font-size: 22px; font-weight: 700; color: #1a202c; margin-top: 36px; margin-bottom: 16px;">
    ۲. اندام سیبی: رازهای کشیده‌تر و لاغرتر دیده شدن
  </h2>
  <p>
    اگر میان‌تنه پرتری دارید و کمرتان تفکیک کمی دارد، هدف شما باید <strong>ایجاد خطوط عمودی کشیده</strong> و دور کردن توجه از ناحیه شکم باشد.
  </p>
  <p>
    <strong>مانتوهای مناسب:</strong> مانتوهای جلوباز با ریزش آزاد (Drape)، پارچه‌های لخت و روان مانند کرپ‌های سبک یا لینن، مانتوهای یقه هفت یا یقه آرشال عمودی، و پالتوهای بدون کمربند سفت. مانتوهایی که قد آن‌ها زیر باسن یا تا روی زانو است، بهترین خطوط کشیده را خلق می‌کنند.
  </p>

  <!-- Product Card: Apple shape recommendation -->
  <div style="display: flex; flex-wrap: wrap; gap: 16px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); align-items: center;">
    <div style="width: 130px; height: 175px; border-radius: 8px; overflow: hidden; background: #f7fafc; flex-shrink: 0; margin: 0 auto;">
      <img src="https://cdn.mong.ir/9/webgeneral/d5ad3f54-82a6-47da-89df-b806125e951b.webp" alt="مانتو زنانه مدل دادلی" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" />
    </div>
    <div style="flex: 1; min-width: 220px;">
      <span style="display: inline-block; background: #e6fffa; color: #234e52; font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 12px; margin-bottom: 6px;">پیشنهاد ویژه اندام سیبی</span>
      <h4 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: #1a202c;">مانتو زنانه مدل دادلی</h4>
      <p style="margin: 0 0 12px 0; font-size: 13px; color: #4a5568; line-height: 1.7;">
        💡 <em>تحلیل استایل مانگ:</em> الگوی آزاد با ریزش زیبا و طراحی جلوباز که بدون چسبیدن به میان‌تنه، استایلی لاغر و باوقار خلق می‌کند.
      </p>
      <a href="/products-item/مانتو-دادلی" target="_blank" style="display: inline-block; background: #3182ce; color: #ffffff; padding: 8px 16px; border-radius: 6px; font-size: 13px; font-weight: 600; text-decoration: none;">
        مشاهده و خرید مانتو دادلی در مانگ &larr;
      </a>
    </div>
  </div>

  <h2 id="hourglass-body-type" style="font-size: 22px; font-weight: 700; color: #1a202c; margin-top: 36px; margin-bottom: 16px;">
    ۳. اندام ساعت شنی: حفظ تعادل و نمایش ظرافت خط کمر
  </h2>
  <p>
    اندام ساعت شنی تناسبی طبیعی میان شانه و باسن دارد. بزرگ‌ترین اشتباه برای این اندام، پوشیدن لباس‌های جعبه‌ای و کاملاً بدون فرم (Boxy) است که باریکی کمر را پنهان می‌کنند.
  </p>
  <p>
    <strong>مانتوهای مناسب:</strong> مانتوها و بارانی‌های ترنچ‌کت کمربنددار، پالتوهای فیت با برش ساسون‌دار در کمر، و کت‌های تک‌دکمه جذب. کمربند مانتو بهترین ابزار شماست تا نقطه کانونی استایلتان را برجسته کند.
  </p>

  <!-- Product Card: Hourglass shape recommendation -->
  <div style="display: flex; flex-wrap: wrap; gap: 16px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); align-items: center;">
    <div style="width: 130px; height: 175px; border-radius: 8px; overflow: hidden; background: #f7fafc; flex-shrink: 0; margin: 0 auto;">
      <img src="https://cdn.mong.ir/9/webgeneral/cc36a8c3-e7ba-4279-9fa9-374e188e245d.webp" alt="بارانی زنانه مدل لوانا" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" />
    </div>
    <div style="flex: 1; min-width: 220px;">
      <span style="display: inline-block; background: #fefcbf; color: #744210; font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 12px; margin-bottom: 6px;">پیشنهاد ویژه اندام ساعت شنی</span>
      <h4 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: #1a202c;">بارانی کلاسیک زنانه مدل لوانا</h4>
      <p style="margin: 0 0 12px 0; font-size: 13px; color: #4a5568; line-height: 1.7;">
        💡 <em>تحلیل استایل مانگ:</em> طراحی کلاسیک ترنچ همراه با کمربند تنظیمی که ظرافت کمر را برجسته کرده و قدی کشیده و رسمی به شما می‌بخشد.
      </p>
      <a href="/products-item/باراني-لوانا" target="_blank" style="display: inline-block; background: #3182ce; color: #ffffff; padding: 8px 16px; border-radius: 6px; font-size: 13px; font-weight: 600; text-decoration: none;">
        مشاهده و خرید بارانی لوانا در مانگ &larr;
      </a>
    </div>
  </div>

  <h2 id="rectangle-body-type" style="font-size: 22px; font-weight: 700; color: #1a202c; margin-top: 36px; margin-bottom: 16px;">
    ۴. اندام مستطیلی: خلق انحنا با لایه‌بندی و برش‌های هوشمند
  </h2>
  <p>
    اگر اندامی لاغر، ورزشی و بدون انحنای محسوس در کمر دارید، هنر استایل شما در <strong>«ایجاد توهم انحنا و بعد»</strong> خلاصه می‌شود.
  </p>
  <p>
    <strong>مانتوهای مناسب:</strong> مانتوهای لایه‌ای همراه با وست و ژیله، کت‌های دارای جزئیات چشمگیر مانند جیب‌های پاکتی بزرگ، دکمه‌های دوبل یا پیله‌دار، و ست کردن با شلوارهای پیله‌دار یا مام‌استایل.
  </p>

  <!-- Product Card: Rectangle shape recommendation -->
  <div style="display: flex; flex-wrap: wrap; gap: 16px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; margin: 20px 0; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); align-items: center;">
    <div style="width: 130px; height: 175px; border-radius: 8px; overflow: hidden; background: #f7fafc; flex-shrink: 0; margin: 0 auto;">
      <img src="https://cdn.mong.ir/9/webgeneral/ea3dd8c9-910f-485d-ae4e-896aaddf2c78.webp" alt="جلیقه زنانه مدل جیمی کی" style="width: 100%; height: 100%; object-fit: cover;" loading="lazy" />
    </div>
    <div style="flex: 1; min-width: 220px;">
      <span style="display: inline-block; background: #feebc8; color: #7b341e; font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 12px; margin-bottom: 6px;">پیشنهاد ویژه اندام مستطیلی</span>
      <h4 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: #1a202c;">جلیقه و وست زنانه مدل جیمی کِی</h4>
      <p style="margin: 0 0 12px 0; font-size: 13px; color: #4a5568; line-height: 1.7;">
        💡 <em>تحلیل استایل مانگ:</em> پوشیدن این جلیقه روی شومیز، با ایجاد خطوط ساختاری و لایه‌ای، خط کمر را تعریف کرده و استایلی مدرن می‌سازد.
      </p>
      <a href="/products-item/جليقه-جيمي-كِي" target="_blank" style="display: inline-block; background: #3182ce; color: #ffffff; padding: 8px 16px; border-radius: 6px; font-size: 13px; font-weight: 600; text-decoration: none;">
        مشاهده و خرید جلیقه جیمی کی در مانگ &larr;
      </a>
    </div>
  </div>

  <h2 id="inverted-triangle-body-type" style="font-size: 22px; font-weight: 700; color: #1a202c; margin-top: 36px; margin-bottom: 16px;">
    ۵. اندام مثلث وارونه: نرم کردن سرشانه‌ها و هدایت توجه به پایین‌تنه
  </h2>
  <p>
    اگر شانه‌های پهن و باسن ظریفی دارید، باید از هرگونه مانتوی با اپل‌های درشت، یقه قایقی یا آستین‌های پفی پرهیز کنید.
  </p>
  <p>
    <strong>مانتوهای مناسب:</strong> مانتوهای یقه هفت کشیده، مانتوهای با آستین رگلان و افتاده، و ست کردن مانتوهای ساده تیره با شلوارهای واید، بگ یا بوت‌کات روشن که توجه را به سمت پایین‌تنه هدایت کنند.
  </p>

  <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 32px 0;" />

  <h2 id="golden-rules-silhouette" style="font-size: 22px; font-weight: 700; color: #1a202c; margin-top: 36px; margin-bottom: 16px;">
    ۳ قانون طلایی که قبل از خرید هر مانتو باید بدانید
  </h2>
  <ol style="padding-right: 20px; margin-bottom: 24px;">
    <li><strong>قانون قد مانتو و تناسب قد پا:</strong> قد مانتویی که دقیقاً در پهن‌ترین نقطه ران تمام شود، شما را کوتاه‌تر نشان می‌دهد. لبه مانتو باید کمی بالاتر (تا بالای زانو) یا کاملاً زیر زانو قرار گیرد.</li>
    <li><strong>قدرت شلوار ست:</strong> مانتو تنها نیمی از استایل است؛ یک مانتوی کتی آزاد در کنار یک <a href="/products-item/شلوار-ترنج" style="color: #3182ce; font-weight: 600; text-decoration: underline;" target="_blank">شلوار راسته یا مام‌فیت خوش‌دوخت مانند شلوار ترنج</a>، تعادل بی‌نقصی می‌آفریند.</li>
    <li><strong>پارچه‌شناسی استایل:</strong> پارچه‌های سفت و ضخیم برای ساختن زاویه و ساختار (مناسب اندام‌های باریک یا گلابی) عالی هستند؛ در حالی که پارچه‌های لخت و ریزش‌دار برای انحنا دادن و سبک نشان دادن میان‌تنه (اندام سیبی) معجزه می‌کنند.</li>
  </ol>

  <div style="background: linear-gradient(135deg, #ebf8ff 0%, #e6fffa 100%); border-radius: 12px; padding: 24px; text-align: center; margin-top: 40px;">
    <h3 style="margin-top: 0; color: #2c5282; font-size: 20px; font-weight: 700;">مانتوی متناسب با اندام خود را در مانگ بیابید</h3>
    <p style="color: #4a5568; max-width: 600px; margin: 10px auto 20px auto;">
      در دپارتمان استور مانگ، هر محصول با الگوهای مهندسی‌شده و پارچه‌های باکیفیت طراحی شده تا زیبایی طبیعی اندام شما را به بهترین شکل به نمایش بگذارد.
    </p>
    <a href="/products-category/all" style="display: inline-block; background-color: #3182ce; color: #ffffff; padding: 12px 28px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 15px; box-shadow: 0 4px 6px rgba(49, 130, 206, 0.3);">
      مشاهده کالکشن مانتو و پوشاک مانگ &larr;
    </a>
  </div>
</div>
""".strip()

def run_sync():
    # 1. FileMedia for Article 2 thumbnail
    fm, _ = FileMedia.objects.get_or_create(
        url=THUMB_URL,
        defaults={
            "file_name": "body-type-manteau-guide.webp",
            "format_id": 7,
            "upload_time": now,
            "size": 138000,
            "width": 1200,
            "height": 800,
            "domain": "mong.ir",
            "used": True,
            "favorite": False,
            "alternative": "راهنمای فرم اندام و انتخاب مانتو مانگ",
            "tooltip_title": "راهنمای انتخاب مانتو بر اساس تیپ بدنی",
            "created": now,
            "last_modified": now,
            "is_deleted": False,
        }
    )

    # 2. Category: مد و لباس
    cat, _ = BlogCategory.objects.get_or_create(
        title="مد و لباس",
        defaults={"created": now, "is_deleted": False}
    )

    # 3. Tags
    tag_names = ["فرم اندام", "انتخاب مانتو", "استایل زنانه", "مد و لباس", "شیک", "ترفندهای استایل", "مانتو کتی"]
    tags = []
    for tname in tag_names:
        t, _ = ArticleTag.objects.get_or_create(name=tname, defaults={"created": now, "is_deleted": False})
        if t.is_deleted:
            t.is_deleted = False
            t.save()
        tags.append(t)

    # 4. Article (Upsert by uniq_url)
    article, created = Article.objects.update_or_create(
        uniq_url=UNIQ_URL,
        defaults={
            "title": TITLE,
            "content": CONTENT_HTML,
            "description": DESCRIPTION,
            "thumbnail": THUMB_URL,
            "author_id": 1,
            "publish_date": now,
            "show_on_page": True,
            "last_modified": now,
            "is_deleted": False,
        }
    )
    action = "Created" if created else "Updated"
    print(f"{action} Article ID: {article.id}")

    # 5. MediaAttachment for Admin Panel Gallery
    TABLE_ARTICLES = 32
    MediaAttachment.objects.filter(table=TABLE_ARTICLES, record_id=article.id).delete()
    MediaAttachment.objects.create(
        table=TABLE_ARTICLES,
        record_id=article.id,
        media_url=THUMB_URL,
        map_id=str(fm.id),
        alternative="راهنمای فرم اندام مانگ",
        tooltip_title="راهنمای انتخاب مانتو بر اساس فرم بدنی",
        created=now,
        last_modified=now,
        is_deleted=False,
        is_video=False,
    )

    # 6. Category Link
    ArticleBlogCategory.objects.filter(article=article).delete()
    ArticleBlogCategory.objects.create(
        article=article,
        category=cat,
        created=now,
        is_deleted=False
    )

    # 7. Tag Links
    ArticleTagRelation.objects.filter(article=article).delete()
    for tag in tags:
        ArticleTagRelation.objects.create(
            article=article,
            tag=tag,
            created=now,
            is_deleted=False
        )

    print("Article #2 sync complete successfully!")

if __name__ == "__main__":
    run_sync()
