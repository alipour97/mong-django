"""
Mong Blog Article Sync Script (Article #1: Capsule Wardrobe)
Usage on Runflare (or local):
    python manage.py shell < sync_article_1.py
    or
    python sync_article_1.py
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
UNIQ_URL = "capsule-wardrobe-guide-iran"
TITLE = "راهنمای جامع ساخت کمد کپسولی برای خانم‌های ایرانی: با ۱۰ آیتم، ۳۰ استایل بسازید!"
DESCRIPTION = "چگونه با ۱۰ آیتم ضروری، یک کمد کپسولی شیک، کاربردی و اقتصادی برای محیط کار، دانشگاه و دورهمی بسازیم؟ راهنمای کامل استایل به سبک استایلیست‌های مانگ."
THUMB_URL = "https://cdn.mong.ir/9/webgeneral/c67db9fe-4bca-4563-a707-01af898a5ce3.webp"

CONTENT_HTML = """
<div class="article-content" style="line-height: 2.1; font-size: 16px; color: #2d3748;">
  <p class="lead" style="font-size: 18px; font-weight: 500; color: #1a202c; margin-bottom: 24px;">
    حتماً برای شما هم پیش آمده که روبروی کمدی پر از لباس بایستید و با کلافگی بگویید: <strong>«من هیچ لباسی برای پوشیدن ندارم!»</strong>. 
    این تناقض بزرگ دنیای مد—یعنی کمدی پر و استایلی تکراری یا خسته‌کننده—دقیقاً همان نقطه‌ای است که طراحان و استایلیست‌های حرفه‌ای را به سمت یک راهکار مدرن و هوشمندانه به نام <strong>«کمد کپسولی» (Capsule Wardrobe)</strong> هدایت کرده است.
  </p>

  <p>
    کمد کپسولی به این معنا نیست که خودتان را به لباس‌های بی‌روح یا تکراری محدود کنید؛ بلکه یعنی انتخابی هوشمندانه از آیتم‌های کلاسیک، باکیفیت و همه‌کاره که مانند قطعات یک پازل به زیبایی در کنار هم می‌نشینند. در این راهنمای جامع و اختصاصی، این مفهوم جهانی را با فرهنگ پوشش، سبک زندگی و نیازهای خانم‌های ایرانی بومی‌سازی کرده‌ایم تا با ۱۰ تکه لباس کلیدی از کالکشن <strong>دپارتمان استور مانگ</strong>، بیش از ۳۰ ست چشم‌نواز و متنوع برای موقعیت‌های کاری، دانشگاهی، دورهمی و روزمره بسازید.
  </p>

  <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 32px 0;" />

  <h2 id="what-is-capsule-wardrobe" style="font-size: 22px; font-weight: 700; color: #1a202c; margin-top: 36px; margin-bottom: 16px;">
    کمد کپسولی چیست و چرا برای خانم‌های ایرانی ضروری است؟
  </h2>
  <p>
    مفهوم کمد کپسولی بر یک اصل طلایی استوار است: «کیفیت و هماهنگی به جای کمیت سردرگم‌کننده». امروزه استایلیست‌های مد این رویکرد را به عنوان پایدارترین، اقتصادی‌ترین و شیک‌ترین سبک پوشش مینیمال معرفی می‌کنند. هدف کمد کپسولی داشتن بین <strong>۱۰ تا ۲۵ آیتم اصلی</strong> است که رنگ‌ها، برش‌ها و قواره آن‌ها به گونه‌ای انتخاب شوند که بیشترین تعداد ترکیب ممکن را خلق کنند.
  </p>
  <p>
    برای یک خانم ایرانی، استایل روزمره پیچیدگی‌های بیشتری نسبت به مدل‌های غربی دارد؛ پوشش لایه‌ای، نیاز به مانتوها و تن‌پوش‌های باوقار، رعایت تناسب در محیط‌های کاری و دانشگاهی، و در عین حال تمایل به به‌روز بودن و حفظ ظرافت زنانه. کمد کپسولی دقیقاً این دغدغه‌ها را حل می‌کند:
  </p>
  <ul style="padding-right: 20px; margin-bottom: 24px;">
    <li><strong>پایان سردرگمی صبحگاهی:</strong> هر آیتمی را که از کمد بردارید، با حداقل ۳ آیتم دیگر ست می‌شود.</li>
    <li><strong>صرفه‌جویی اقتصادی چشمگیر:</strong> به جای خرید ۱۰ مانتوی ارزان‌قیمت که بعد از دو بار شستشو از فرم می‌افتند، ۲ مانتوی ماندگار و خوش‌دوخت تهیه می‌کنید.</li>
    <li><strong>امضای استایل شخصی (Personal Style):</strong> استایلی مرتب، ساختاریافته و شیک که به دیگران حس وقار و سلیقه را منتقل می‌کند.</li>
  </ul>

  <h2 id="capsule-color-palette" style="font-size: 22px; font-weight: 700; color: #1a202c; margin-top: 36px; margin-bottom: 16px;">
    فرمول طلایی انتخاب پالت رنگی کمد کپسولی
  </h2>
  <p>
    راز اصلی موفقیت یک کمد کپسولی در پالت رنگی آن نهفته است. طبق توصیه استایلیست‌های حرفه‌ای، رنگ‌های کمد کپسولی باید به سه دسته تقسیم شوند:
  </p>
  <div style="background-color: #f7fafc; border-right: 4px solid #3182ce; padding: 18px 24px; border-radius: 8px; margin: 20px 0;">
    <p style="margin: 0 0 10px 0;"><strong>۱. رنگ‌های پایه و ساختاری (Base Neutrals):</strong> مشکی، سرمه‌ای، ذغالی و طوسی تیره. این رنگ‌ها برای کت‌ها، شلوارهای رسمی و کفش‌ها ایده‌آل هستند چون بیشترین استفاده را دارند و دیرتر کهنه یا کثیف به نظر می‌رسند.</p>
    <p style="margin: 0 0 10px 0;"><strong>۲. رنگ‌های خنثی روشن (Light Neutrals):</strong> کرم، استخوانی، شتری، بژ و سفید نچرال. این رنگ‌ها به استایل شما نور، شادابی و وقار می‌بخشند و برای شومیزها، مانتوهای کتی روزمره و ترنچ‌کت عالی هستند.</p>
    <p style="margin: 0;"><strong>۳. رنگ‌های بیانی و تاکیدی (Accent Colors):</strong> زرشکی، سبز زیتونی، آجری یا خردلی مات. این رنگ‌ها معمولاً در شال، کیف، یا بافت‌های ظریف به کار می‌روند تا استایل از حالت یکنواختی خارج شود.</p>
  </div>

  <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 32px 0;" />

  <h2 id="core-items-mong" style="font-size: 22px; font-weight: 700; color: #1a202c; margin-top: 36px; margin-bottom: 16px;">
    ۱۰ آیتم ضروری برای کمد کپسولی ایرانی (بر اساس کالکشن مانگ)
  </h2>
  <p>
    بر اساس بررسی‌های تخصصی استایلیست‌های مانگ و تحلیل محصولات پرفروش، این ۱۰ آیتم طلایی شاکله اصلی کمد کپسولی شما را می‌سازند:
  </p>

  <h3 id="item-1-manteau-odyssey" style="font-size: 19px; font-weight: 600; color: #2b6cb0; margin-top: 28px; margin-bottom: 12px;">
    ۱. مانتو کتی زنانه مدل اودیسه با یقه انگلیسی
  </h3>
  <p>
    هیچ کمد کپسولی بدون یک کت با دوخت بی‌نقص کامل نیست. مانتو کتی اودیسه با الگوی آزاد و ساختار دکمه‌دار جلو، تلفیقی استادانه از استایل کلاسیک و معاصر است.
  </p>
  <div style="background: #edf2f7; border-radius: 8px; padding: 16px 20px; margin: 16px 0;">
    <p style="margin: 0; font-style: italic; color: #4a5568;">
      💡 <strong>یادداشت استایلیست مانگ:</strong> «این مانتو کتی را با شلوار پارچه‌ای راسته و کفش لوفر برای موقعیت‌های کاری ست کنید، یا با شلوار جین نیم‌بگ برای یک دورهمی دوستانه بپوشید.»
    </p>
  </div>
  <p>
    <a href="/products-item/کت-عروسکی-اودیسه" style="color: #3182ce; font-weight: 600; text-decoration: underline;" target="_blank">مشاهده و بررسی مانتو کتی اودیسه در مانگ &larr;</a>
  </p>

  <h3 id="item-2-manteau-diplomat" style="font-size: 19px; font-weight: 600; color: #2b6cb0; margin-top: 28px; margin-bottom: 12px;">
    ۲. مانتو زنانه یقه آرشال دیپلمات راه راه
  </h3>
  <p>
    اگر می‌خواهید در جلسات، محل کار یا دانشگاه کشیده‌تر و باوقارتر دیده شوید، خطوط راه‌راه دیپلمات عمودی بهترین دوست شما هستند. این مانتو با یقه آرشال پهن و ایستایی چشم‌نواز، تعادلی هوشمندانه میان آزادی حرکت و فرمالیته اداری برقرار می‌کند.
  </p>
  <div style="background: #edf2f7; border-radius: 8px; padding: 16px 20px; margin: 16px 0;">
    <p style="margin: 0; font-style: italic; color: #4a5568;">
      💡 <strong>یادداشت استایلیست مانگ:</strong> «این مانتو را با شلوار راسته پارچه‌ای و یک جفت لوفر شیک ست کنید تا استایلی منظم، باوقار و مناسب محیط کار خلق شود.»
    </p>
  </div>
  <p>
    <a href="/products-item/مانتو-لینن-بامبو-یقه-ارشال-دیپلمات" style="color: #3182ce; font-weight: 600; text-decoration: underline;" target="_blank">مشاهده جزئیات مانتو دیپلمات در مانگ &larr;</a>
  </p>

  <h3 id="item-3-tailored-trousers-711" style="font-size: 19px; font-weight: 600; color: #2b6cb0; margin-top: 28px; margin-bottom: 12px;">
    ۳. شلوار راسته زنانه جلو دوخت‌دار ۷۱۱ (گاباردین)
  </h3>
  <p>
    شلوارهای راسته با خط دوخت اتوخورده سراسری، پاهای شما را کشیده نشان می‌دهند و بزرگ‌ترین حسن آن‌ها این است که خط اتوی آن‌ها هرگز در اثر نشستن یا شستشو از بین نمی‌رود. این شلوار مشکی راسته، پایه ثابت بیش از نیمی از استایل‌های شما خواهد بود.
  </p>
  <div style="background: #edf2f7; border-radius: 8px; padding: 16px 20px; margin: 16px 0;">
    <p style="margin: 0; font-style: italic; color: #4a5568;">
      💡 <strong>یادداشت استایلیست مانگ:</strong> «این شلوار را با یک مانتو کتی خوش‌دوخت و کفش لوفر ست کنید تا استایلی کاملاً مرتب، کشیده و مناسب موقعیت‌های رسمی و کاری داشته باشید.»
    </p>
  </div>
  <p>
    <a href="/products-item/شلوار-گاباردين-جلو-دوخت-دار-711" style="color: #3182ce; font-weight: 600; text-decoration: underline;" target="_blank">مشاهده شلوار راسته جلو دوخت‌دار ۷۱۱ &larr;</a>
  </p>

  <h3 id="item-4-basic-shirt" style="font-size: 19px; font-weight: 600; color: #2b6cb0; margin-top: 28px; margin-bottom: 12px;">
    ۴. شومیز بیسیک سفید یا نود (مدل آیان ۳)
  </h3>
  <p>
    شومیز بیسیک همان عنصری است که زیر هر کت، مانتو، پالتو یا ژیله‌ای می‌درخشد. شومیز آیان ۳ با برش استاندارد و پارچه سبک و خوش‌ریزش، نقطه آغاز بی‌شمار ست استایلیش است.
  </p>
  <p>
    <a href="/products-item/شومیز-آیان-3" style="color: #3182ce; font-weight: 600; text-decoration: underline;" target="_blank">مشاهده شومیز زنانه آیان ۳ &larr;</a>
  </p>

  <h3 id="item-5-sport-coat" style="font-size: 19px; font-weight: 600; color: #2b6cb0; margin-top: 28px; margin-bottom: 12px;">
    ۵. کت دو جیب فوتر اسپرت
  </h3>
  <p>
    برای روزهای خنک سال، یک کت فوتر خوش‌برش با دو جیب کاربردی، حال و هوای مینیمال و شیکی به ظاهر شما می‌دهد. این کت به اندازه پالتو سنگین نیست و به راحتی با شلوار جین یا راسته ست می‌شود.
  </p>
  <p>
    <a href="/products-item/کت-دو-جيب-فوتر-اسپرت" style="color: #3182ce; font-weight: 600; text-decoration: underline;" target="_blank">مشاهده کت دو جیب فوتر در مانگ &larr;</a>
  </p>

  <h3 id="item-6-classic-coat" style="font-size: 19px; font-weight: 600; color: #2b6cb0; margin-top: 28px; margin-bottom: 12px;">
    ۶. پالتو کلاسیک زنانه (مدل لکسی Lexy یا یارا)
  </h3>
  <p>
    پالتوی خوش‌دوخت در رنگ‌های طوسی، شتری یا مشکی ستون اصلی استایل زمستانه است. بلندی مناسب این پالتوها هماهنگی ایده‌آلی با نیم‌بوت و شلوارهای راسته یا بوت‌کات ایجاد می‌کند.
  </p>
  <p>
    <a href="/products-item/پالتو-لکسی-lexy" style="color: #3182ce; font-weight: 600; text-decoration: underline;" target="_blank">مشاهده پالتو لکسی در مانگ &larr;</a>
  </p>

  <h3 id="item-7-casual-trousers" style="font-size: 19px; font-weight: 600; color: #2b6cb0; margin-top: 28px; margin-bottom: 12px;">
    ۷. شلوار کژوال یا جین نیم‌بگ (شلوار ژاکان / ترنم)
  </h3>
  <p>
    کنار شلوار رسمی، داشتن یک شلوار نیم‌بگ یا راسته کژوال از پارچه باکیفیت به شما اجازه می‌دهد در سریع‌ترین زمان استایل‌های روزمره، دورهمی و قرارهای عصرانه را بسازید.
  </p>
  <p>
    <a href="/products-item/شلوار-ژاکان" style="color: #3182ce; font-weight: 600; text-decoration: underline;" target="_blank">مشاهده شلوار ژاکان &larr;</a>
  </p>

  <h3 id="item-8-knitwear" style="font-size: 19px; font-weight: 600; color: #2b6cb0; margin-top: 28px; margin-bottom: 12px;">
    ۸. بلوز بافت یقه ۵ سانت ظریف
  </h3>
  <p>
    بافت‌های ظریف و فیت بهترین گزینه برای لایه‌بندی در فصل‌های سرد هستند، زیرا حجم غیرضروری به بالاتنه اضافه نمی‌کنند و به سادگی زیر کت یا پالتو پوشیده می‌شوند.
  </p>

  <h3 id="item-9-scarf" style="font-size: 19px; font-weight: 600; color: #2b6cb0; margin-top: 28px; margin-bottom: 12px;">
    ۹. شال موهر جناقی و مینی‌اسکارف‌های خنثی
  </h3>
  <p>
    در استایل بانوان ایرانی، شال و روسری نزدیک‌ترین جزء به چهره است و بیشترین تأثیر را روی درخشش رنگ پوست دارد. دو شال تک‌رنگ خنثی (یک شال گرم مانند موهر جناقی برای پاییز و یک شال نخی سبک برای بهار) در کنار یک روسری ژاکارد مینی تمام نیاز شما را پوشش می‌دهد.
  </p>

  <h3 id="item-10-footwear" style="font-size: 19px; font-weight: 600; color: #2b6cb0; margin-top: 28px; margin-bottom: 12px;">
    ۱۰. کفش لوفر چرم + کتانی مینیمال سفید
  </h3>
  <p>
    استایل اسمارت‌کژوال یعنی توانایی جابجایی بین راحتی و رسمیت. یک جفت لوفر چرمی مشکی برای موقعیت‌های کاری و یک کتانی کاملاً سفید و ساده برای فعالیت‌های روزمره، کمد کپسولی شما را تکمیل می‌کنند.
  </p>

  <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 32px 0;" />

  <h2 id="outfit-formulas" style="font-size: 22px; font-weight: 700; color: #1a202c; margin-top: 36px; margin-bottom: 16px;">
    ۴ فرمول طلایی ترکیب آیتم‌ها: ۳۰ ست متنوع برای موقعیت‌های مختلف
  </h2>
  <p>
    حالا که قطعات پازل را در اختیار دارید، بیایید ببینیم چطور می‌توانید با فرمول‌های اختصاصی تیم استایلینگ مانگ، این آیتم‌ها را در چند دقیقه به زیباترین شکل ست کنید:
  </p>

  <div style="display: grid; grid-template-columns: 1fr; gap: 20px; margin: 24px 0;">
    <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.04);">
      <h4 style="margin-top: 0; color: #2b6cb0; font-size: 17px; font-weight: 700;">فرمول ۱: استایل کاری و قرارهای رسمی (Power Dressing)</h4>
      <p style="margin-bottom: 8px;"><strong>ترکیب:</strong> مانتو دیپلمات یقه آرشال + شومیز آیان ۳ + شلوار گاباردین ۷۱۱ + لوفر چرم + شال مشکی تک‌رنگ.</p>
      <p style="margin: 0; font-size: 14px; color: #718096;"><em>نتیجه:</em> استایلی شکیل و معتمد به نفس که وقار شما را بدون کوچک‌ترین زحمتی به نمایش می‌گذارد.</p>
    </div>

    <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.04);">
      <h4 style="margin-top: 0; color: #2b6cb0; font-size: 17px; font-weight: 700;">فرمول ۲: استایل اسمارت‌کژوال روزمره و دانشگاه</h4>
      <p style="margin-bottom: 8px;"><strong>ترکیب:</strong> مانتو کتی اودیسه + تی‌شرت یا بافت ظریف بیسیک + شلوار ژاکان / جین راسته + کتانی سفید مینیمال + شال نخی طوسی.</p>
      <p style="margin: 0; font-size: 14px; color: #718096;"><em>نتیجه:</em> مدرن، جوان‌پسند، راحت و در عین حال کاملاً شیک و حساب‌شده.</p>
    </div>

    <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.04);">
      <h4 style="margin-top: 0; color: #2b6cb0; font-size: 17px; font-weight: 700;">فرمول ۳: کافه‌گردی و دورهمی‌های دوستانه</h4>
      <p style="margin-bottom: 8px;"><strong>ترکیب:</strong> کت دو جیب فوتر اسپرت + بافت یقه ۵ سانت + شلوار گاباردین ۷۱۱ + نیم‌بوت چرم + مینی‌اسکارف طرح‌دار.</p>
      <p style="margin: 0; font-size: 14px; color: #718096;"><em>نتیجه:</em> استایلی گرم، دنج و عکاسی‌پسند که سلیقه خاص شما را نمایان می‌کند.</p>
    </div>

    <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.04);">
      <h4 style="margin-top: 0; color: #2b6cb0; font-size: 17px; font-weight: 700;">فرمول ۴: استایل زمستانه شیک و لایه‌ای</h4>
      <p style="margin-bottom: 8px;"><strong>ترکیب:</strong> شومیز بیسیک + مانتو کتی اودیسه (لایه‌بندی) + پالتو لکسی + شلوار راسته + بوت بلند.</p>
      <p style="margin: 0; font-size: 14px; color: #718096;"><em>نتیجه:</em> نهایت شیک‌پوشی در هوای سرد با رعایت تکنیک لایه‌بندی اصولی بدون حجیم شدن اندام.</p>
    </div>
  </div>

  <h2 id="maintenance-tips" style="font-size: 22px; font-weight: 700; color: #1a202c; margin-top: 36px; margin-bottom: 16px;">
    چک‌لیست نگهداری کمد کپسولی
  </h2>
  <ol style="padding-right: 20px; margin-bottom: 24px;">
    <li><strong>قانون ورود و خروج (One In, One Out):</strong> هر آیتم جدیدی که وارد کمد می‌شود، یک آیتم قدیمی و بدون استفاده باید اهدا یا خارج شود.</li>
    <li><strong>کیفیت بر کمیت ارجح است:</strong> به دوخت درزها، کیفیت پارچه (مانند فوتر، گاباردین و لینن باکیفیت) و استحکام دکمه‌ها توجه کنید.</li>
    <li><strong>فصلی فکر کنید:</strong> هسته مرکزی کمد ثابت است؛ فقط در ابتدای هر فصل ۲ یا ۳ آیتم فصلی (مانند پالتو در زمستان یا لینن در تابستان) به آن اضافه کنید.</li>
  </ol>

  <div style="background: linear-gradient(135deg, #ebf8ff 0%, #e6fffa 100%); border-radius: 12px; padding: 24px; text-align: center; margin-top: 40px;">
    <h3 style="margin-top: 0; color: #2c5282; font-size: 20px; font-weight: 700;">کمد رویایی‌تان را از همین امروز بسازید</h3>
    <p style="color: #4a5568; max-width: 600px; margin: 10px auto 20px auto;">
      تمام آیتم‌های معرفی‌شده در این راهنما با دقت در برش، پارچه‌های ماندگار و الگوی متناسب با بانوان ایرانی در دپارتمان استور مانگ طراحی و آماده شده‌اند.
    </p>
    <a href="/products-category/all" style="display: inline-block; background-color: #3182ce; color: #ffffff; padding: 12px 28px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 15px; box-shadow: 0 4px 6px rgba(49, 130, 206, 0.3);">
      مشاهده جدیدترین کالکشن مانگ &larr;
    </a>
  </div>
</div>
""".strip()

def run_sync():
    # 1. FileMedia
    fm, _ = FileMedia.objects.get_or_create(
        url=THUMB_URL,
        defaults={
            "file_name": "capsule-wardrobe-cover.webp",
            "format_id": 7,
            "upload_time": now,
            "size": 145000,
            "width": 1200,
            "height": 800,
            "domain": "mong.ir",
            "used": True,
            "favorite": False,
            "alternative": "کمد کپسولی مانگ برای خانم های ایرانی",
            "tooltip_title": "راهنمای ساخت کمد کپسولی ایرانی",
            "created": now,
            "last_modified": now,
            "is_deleted": False,
        }
    )

    # 2. Category
    cat, _ = BlogCategory.objects.get_or_create(
        title="مد و لباس",
        defaults={"created": now, "is_deleted": False}
    )

    # 3. Tags
    tag_names = ["کمد کپسولی", "استایل زنانه", "مانتو کتی", "مد و لباس", "شیک", "ترفندهای استایل", "استایل اداری"]
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
        alternative="کمد کپسولی مانگ",
        tooltip_title="راهنمای ساخت کمد کپسولی ایرانی",
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

    print("Sync complete successfully!")

if __name__ == "__main__":
    run_sync()
