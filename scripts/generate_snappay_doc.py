# -*- coding: utf-8 -*-
import os
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn, nsdecls

def set_cell_background(cell, fill_hex):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)

def set_cell_margins(cell, top=120, bottom=120, left=160, right=160):
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for m, val in [('top', top), ('bottom', bottom), ('left', left), ('right', right)]:
        node = OxmlElement(f'w:{m}')
        node.set(qn('w:w'), str(val))
        node.set(qn('w:type'), 'dxa')
        tcMar.append(node)
    tcPr.append(tcMar)

def set_cell_border(cell, **kwargs):
    """
    kwargs: top, bottom, left, right
    values: dict(sz=4, val='single', color='E2E8F0')
    """
    tcPr = cell._tc.get_or_add_tcPr()
    tcBorders = OxmlElement('w:tcBorders')
    for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        edge_data = kwargs.get(edge)
        if edge_data:
            tag = f'w:{edge}'
            element = OxmlElement(tag)
            element.set(qn('w:val'), edge_data.get('val', 'single'))
            element.set(qn('w:sz'), str(edge_data.get('sz', 4)))
            element.set(qn('w:space'), '0')
            element.set(qn('w:color'), edge_data.get('color', 'E2E8F0'))
            tcBorders.append(element)
    tcPr.append(tcBorders)

def make_p_rtl(p):
    p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    pPr = p._p.get_or_add_pPr()
    pBidi = OxmlElement('w:bidi')
    pBidi.set(qn('w:val'), '1')
    pPr.append(pBidi)

def make_p_ltr(p):
    p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    pPr = p._p.get_or_add_pPr()
    pBidi = OxmlElement('w:bidi')
    pBidi.set(qn('w:val'), '0')
    pPr.append(pBidi)

def add_persian_heading(doc, text, level=1):
    h = doc.add_heading(level=level)
    make_p_rtl(h)
    h.paragraph_format.space_before = Pt(14)
    h.paragraph_format.space_after = Pt(6)
    run = h.add_run(text)
    run.font.name = 'Tahoma'
    rPr = run._r.get_or_add_rPr()
    rFonts = OxmlElement('w:rFonts')
    rFonts.set(qn('w:cs'), 'Tahoma')
    rFonts.set(qn('w:ascii'), 'Tahoma')
    rPr.append(rFonts)
    
    if level == 1:
        run.font.size = Pt(16)
        run.font.bold = True
        run.font.color.rgb = RGBColor(15, 44, 89) # Navy
    elif level == 2:
        run.font.size = Pt(13)
        run.font.bold = True
        run.font.color.rgb = RGBColor(2, 132, 199) # Blue
    elif level == 3:
        run.font.size = Pt(11.5)
        run.font.bold = True
        run.font.color.rgb = RGBColor(51, 65, 85) # Slate
    return h

def add_persian_p(doc, text="", bold_prefix="", space_after=6):
    p = doc.add_paragraph()
    make_p_rtl(p)
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.25

    if bold_prefix:
        r_pre = p.add_run(bold_prefix)
        r_pre.font.name = 'Tahoma'
        r_pre.font.bold = True
        r_pre.font.size = Pt(10)
        r_pre.font.color.rgb = RGBColor(30, 41, 59)
        rPr = r_pre._r.get_or_add_rPr()
        rFonts = OxmlElement('w:rFonts')
        rFonts.set(qn('w:cs'), 'Tahoma')
        rFonts.set(qn('w:ascii'), 'Tahoma')
        rPr.append(rFonts)

    if text:
        r = p.add_run(text)
        r.font.name = 'Tahoma'
        r.font.size = Pt(10)
        r.font.color.rgb = RGBColor(51, 65, 85)
        rPr = r._r.get_or_add_rPr()
        rFonts = OxmlElement('w:rFonts')
        rFonts.set(qn('w:cs'), 'Tahoma')
        rFonts.set(qn('w:ascii'), 'Tahoma')
        rPr.append(rFonts)

    return p

def add_bullet_item(doc, title, desc=""):
    p = doc.add_paragraph(style='List Bullet')
    make_p_rtl(p)
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.2

    r_title = p.add_run(title)
    r_title.font.name = 'Tahoma'
    r_title.font.bold = True
    r_title.font.size = Pt(9.5)
    r_title.font.color.rgb = RGBColor(15, 23, 42)
    rPr = r_title._r.get_or_add_rPr()
    rFonts = OxmlElement('w:rFonts')
    rFonts.set(qn('w:cs'), 'Tahoma')
    rPr.append(rFonts)

    if desc:
        r_desc = p.add_run(" " + desc)
        r_desc.font.name = 'Tahoma'
        r_desc.font.size = Pt(9.5)
        r_desc.font.color.rgb = RGBColor(71, 85, 105)
        rPr2 = r_desc._r.get_or_add_rPr()
        rFonts2 = OxmlElement('w:rFonts')
        rFonts2.set(qn('w:cs'), 'Tahoma')
        rPr2.append(rFonts2)
    return p

def add_code_block(doc, code_str, caption=""):
    if caption:
        p_cap = doc.add_paragraph()
        make_p_rtl(p_cap)
        p_cap.paragraph_format.space_before = Pt(6)
        p_cap.paragraph_format.space_after = Pt(2)
        r_cap = p_cap.add_run(f"📌 {caption}")
        r_cap.font.name = 'Tahoma'
        r_cap.font.bold = True
        r_cap.font.size = Pt(9.5)
        r_cap.font.color.rgb = RGBColor(2, 132, 199)

    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = tbl.cell(0, 0)
    set_cell_background(cell, "F8FAFC")
    set_cell_margins(cell, top=140, bottom=140, left=180, right=180)
    set_cell_border(cell,
        top=dict(sz=6, color='CBD5E1', val='single'),
        bottom=dict(sz=6, color='CBD5E1', val='single'),
        left=dict(sz=18, color='0284C7', val='single'), # Nice blue left accent line
        right=dict(sz=6, color='CBD5E1', val='single')
    )

    p = cell.paragraphs[0]
    make_p_ltr(p)
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.15

    lines = code_str.strip().split('\n')
    for i, line in enumerate(lines):
        r = p.add_run(line + ('\n' if i < len(lines)-1 else ''))
        r.font.name = 'Consolas'
        r.font.size = Pt(8.5)
        r.font.color.rgb = RGBColor(15, 23, 42)
        rPr = r._r.get_or_add_rPr()
        rFonts = OxmlElement('w:rFonts')
        rFonts.set(qn('w:ascii'), 'Consolas')
        rPr.append(rFonts)

    doc.add_paragraph().paragraph_format.space_after = Pt(4)

def add_styled_table(doc, headers, rows, col_widths=None):
    tbl = doc.add_table(rows=len(rows) + 1, cols=len(headers))
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER

    # Header Row
    hdr_cells = tbl.rows[0].cells
    for i, title in enumerate(headers):
        hdr_cells[i].text = ""
        set_cell_background(hdr_cells[i], "0F2C59")
        set_cell_margins(hdr_cells[i], top=120, bottom=120, left=140, right=140)
        set_cell_border(hdr_cells[i],
            top=dict(sz=4, color='0F2C59'),
            bottom=dict(sz=8, color='0284C7'),
            left=dict(sz=4, color='1E3A8A'),
            right=dict(sz=4, color='1E3A8A')
        )
        p = hdr_cells[i].paragraphs[0]
        make_p_rtl(p)
        r = p.add_run(title)
        r.font.name = 'Tahoma'
        r.font.bold = True
        r.font.size = Pt(9.5)
        r.font.color.rgb = RGBColor(255, 255, 255)
        rPr = r._r.get_or_add_rPr()
        rFonts = OxmlElement('w:rFonts')
        rFonts.set(qn('w:cs'), 'Tahoma')
        rPr.append(rFonts)

    # Data Rows
    for r_idx, row in enumerate(rows):
        row_cells = tbl.rows[r_idx + 1].cells
        bg_color = "FFFFFF" if r_idx % 2 == 0 else "F8FAFC"
        for c_idx, val in enumerate(row):
            row_cells[c_idx].text = ""
            set_cell_background(row_cells[c_idx], bg_color)
            set_cell_margins(row_cells[c_idx], top=100, bottom=100, left=120, right=120)
            set_cell_border(row_cells[c_idx],
                top=dict(sz=4, color='E2E8F0'),
                bottom=dict(sz=4, color='E2E8F0'),
                left=dict(sz=4, color='E2E8F0'),
                right=dict(sz=4, color='E2E8F0')
            )
            p = row_cells[c_idx].paragraphs[0]
            # If text starts with English letter or slash or curl, make LTR
            if any(val.strip().startswith(c) for c in ['http', '/', '{', 'x-', 'curl', 'POST', 'GET', '200', '40', '50', 'id', 'slug', 'limit', 'page']):
                make_p_ltr(p)
                r = p.add_run(val)
                r.font.name = 'Consolas'
                r.font.size = Pt(8.5)
                r.font.color.rgb = RGBColor(15, 23, 42)
            else:
                make_p_rtl(p)
                r = p.add_run(val)
                r.font.name = 'Tahoma'
                r.font.size = Pt(9)
                r.font.color.rgb = RGBColor(51, 65, 85)
                rPr = r._r.get_or_add_rPr()
                rFonts = OxmlElement('w:rFonts')
                rFonts.set(qn('w:cs'), 'Tahoma')
                rPr.append(rFonts)

    doc.add_paragraph().paragraph_format.space_after = Pt(4)

def build_document():
    doc = docx.Document()

    # Set margins
    sections = doc.sections
    for section in sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)

    # Header / Title Block
    title_tbl = doc.add_table(rows=1, cols=1)
    title_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = title_tbl.cell(0, 0)
    set_cell_background(cell, "0F2C59")
    set_cell_margins(cell, top=240, bottom=240, left=260, right=260)
    set_cell_border(cell,
        top=dict(sz=12, color='0284C7', val='single'),
        bottom=dict(sz=12, color='0284C7', val='single'),
        left=dict(sz=12, color='0284C7', val='single'),
        right=dict(sz=12, color='0284C7', val='single')
    )
    p_title = cell.paragraphs[0]
    make_p_rtl(p_title)
    r_t = p_title.add_run("مستندات جامع وب‌سرویس و موتور جستجوی محصولات اسنپ‌پی (SearchWise)")
    r_t.font.name = 'Tahoma'
    r_t.font.bold = True
    r_t.font.size = Pt(16)
    r_t.font.color.rgb = RGBColor(255, 255, 255)
    rPr = r_t._r.get_or_add_rPr()
    rFonts = OxmlElement('w:rFonts')
    rFonts.set(qn('w:cs'), 'Tahoma')
    rPr.append(rFonts)

    p_sub = cell.add_paragraph()
    make_p_rtl(p_sub)
    p_sub.paragraph_format.space_before = Pt(6)
    r_s = p_sub.add_run("راهنمای ۳ روش اتصال، دریافت کاتالوگ و ایندکس کالاها در مانگ (Mong.ir) به همراه دستورات cURL")
    r_s.font.name = 'Tahoma'
    r_s.font.size = Pt(11)
    r_s.font.color.rgb = RGBColor(186, 230, 253) # Light Blue
    rPr = r_s._r.get_or_add_rPr()
    rFonts = OxmlElement('w:rFonts')
    rFonts.set(qn('w:cs'), 'Tahoma')
    rPr.append(rFonts)

    doc.add_paragraph().paragraph_format.space_after = Pt(8)

    # 1. مقدمه و اطلاعات عمومی
    add_persian_heading(doc, "۱. کلیات و الزامات عمومی سامانه", level=1)
    add_persian_p(doc, "این سند جهت ارائه به تیم فنی و پشتیبانی سرویس اسنپ‌پی (SnappPay) و موتور جستجوی سرچ‌وایز (SearchWise) تهیه شده است. در فروشگاه اینترنتی مانگ، هر ۳ روش استاندارد اعلام شده توسط اسنپ‌پی برای جمع‌آوری اطلاعات و جستجوی محصولات به صورت کامل، پایدار و تست‌شده پیاده‌سازی و در دسترس قرار گرفته است.")

    add_persian_heading(doc, "آدرس‌های IP رسمی سرچ‌وایز (وایت‌لیست شده روی سرور مانگ)", level=2)
    add_persian_p(doc, "تمامی IPهای رسمی اعلامی سرچ‌وایز در فایروال و لایه برنامه وایت‌لیست بوده و دسترسی بدون وقفه و بدون لیمیت به داده‌ها دارند:")
    add_bullet_item(doc, "185.206.93.115")
    add_bullet_item(doc, "185.206.94.25")
    add_bullet_item(doc, "37.152.176.176")
    add_bullet_item(doc, "188.121.106.231")

    add_persian_heading(doc, "مشخصات محیط و اطلاعات پایه‌ای", level=2)
    add_styled_table(doc, 
        ["پارامتر", "مقدار / توضیح"],
        [
            ["دامنه اصلی فروشگاه", "https://mong.ir"],
            ["واحد پولی قیمت‌ها", "ریال (IRR) - مطابق با مبالغ درگاه پرداخت اسنپ‌پی"],
            ["کدگذاری متون و اسلاگ‌ها", "UTF-8 (پشتیبانی کامل از حروف فارسی و کاراکترهای نیم‌فاصله)"],
            ["فرمت خروجی پیش‌فرض", "application/json"],
            ["موتور همگام‌سازی کاتالوگ", "Real-Time / کش هوشمند با قابلیت Force Refresh"]
        ]
    )

    # روش اول: Sitemap
    add_persian_heading(doc, "۲. روش اول: جمع‌آوری مستقیم با ربات خزنده و نقشه سایت (Sitemap)", level=1)
    add_persian_p(doc, "در این روش، ربات خزنده‌ی سرچ‌وایز اسنپ‌پی به صورت خودکار و روزانه به آدرس نقشه سایت مراجعه نموده و لینک کلیه محصولات فعال و جدید را دریافت کرده و سپس به صفحه اختصاصی هر کالا مراجعه می‌کند.")

    add_bullet_item(doc, "آدرس مستقیم نقشه سایت (Sitemap XML):", "https://mong.ir/sitemap.xml")
    add_bullet_item(doc, "الگوی لینک صفحات محصول:", "https://mong.ir/products-item/{slug}")
    add_bullet_item(doc, "نحوه ارائه داده‌ها در صفحه محصول:", "کلیه مشخصات ضروری شامل عنوان، دسته‌بندی، قیمت جاری، وضعیت موجودی، تصاویر اصلی، جدول مشخصات و تگ‌های متادیتای استاندارد (Schema.org Product و OpenGraph) بدون نیاز به پردازش جاوااسکریپت در سمت کلاینت (SSR) در خروجی HTML قرار دارند.")

    add_code_block(doc,
"""# ۱. استعلام و دریافت نقشه سایت جامع فروشگاه مانگ
curl -X GET "https://mong.ir/sitemap.xml" \\
  -H "Accept: application/xml, text/xml, */*" \\
  -H "User-Agent: SearchwiseBot/1.0 (+https://searchwise.ir)"

# ۲. بررسی هدر پاسخ و وضعیت دسترسی به صفحه محصول نمونه
curl -I "https://mong.ir/products-item/%D8%B4%D9%84%D9%88%D8%A7%D8%B1-%DA%AF%D8%A7%D8%A8%D8%A7%D8%B1%D8%AF%DB%8C%D9%86-%D8%A8%D8%BA%D9%84-%DA%87%D8%A7%DA%A9%D8%AF%D8%A7%D8%B1" \\
  -H "User-Agent: SearchwiseBot/1.0"

# ۳. نمونه واکشی تگ‌های متادیتا و قیمت صفحه کالا به صورت مستقیم
curl -s "https://mong.ir/products-item/%D8%B4%D9%84%D9%88%D8%A7%D8%B1-%DA%AF%D8%A7%D8%A8%D8%A7%D8%B1%D8%AF%DB%8C%D9%86-%D8%A8%D8%BA%D9%84-%DA%87%D8%A7%DA%A9%D8%AF%D8%A7%D8%B1" | grep -E "og:title|og:price|schema.org|availability"
""", caption="دستورات cURL برای روش اول (Sitemap / Direct Crawl)")

    # روش دوم: خوراک محصول فایل مبتنی بر JSON
    add_persian_heading(doc, "۳. روش دوم: خوراک محصول مبتنی بر فایل (Product Feed JSON / XML)", level=1)
    add_persian_p(doc, "در این روش، کلیه محصولات فعال فروشگاه به همراه تمامی صفات فنی، ابعاد، رنگ‌ها، قیمت‌ها و لینک‌های تصاویر در قالب یک فایل/اندپوینت ساختاریافته JSON یا XML بدون نیاز به صفحه‌بندی عرضه می‌شود. ربات اسنپ‌پی می‌تواند با یک درخواست کل کاتالوگ را دانلود و همگام‌سازی نماید.")

    add_bullet_item(doc, "آدرس خوراک به فرمت JSON:", "https://mong.ir/api/snappay/feed.json (یا https://mong.ir/api/snappay/feed)")
    add_bullet_item(doc, "آدرس خوراک به فرمت XML:", "https://mong.ir/api/snappay/feed.xml")

    add_persian_p(doc, "ساختار و مشخصات کلیدی هر آیتم در خوراک محصول JSON:", bold_prefix="اقلام داده‌ای (Schema): ")
    add_styled_table(doc,
        ["نام فیلد", "نوع داده", "توضیح و ساختار"],
        [
            ["id", "integer / string", "شناسه یکتای محصول در سامانه فروشگاه (SKU)"],
            ["title", "string", "عنوان کامل و سئو شده کالا (نوع + مدل + برند)"],
            ["subtitle", "string", "نام لاتین، مدل یا عنوان دوم کالا"],
            ["link", "string (URL)", "آدرس مستقیم و متعارف (Canonical) صفحه خرید کالا در سایت"],
            ["image_link", "array of URLs", "آرایه تصاویر کالا؛ ایندکس اول تصویر اصلی، باکیفیت و غیر تامبنیل"],
            ["availability", "string", "وضعیت موجودی در انبار: in stock یا out of stock"],
            ["regular_price", "number (Rials)", "قیمت پایه و مصوب کالا به ریال قبل از تخفیف"],
            ["sale_price", "number (Rials)", "قیمت فروش نهایی کالا به ریال بعد از اعمال تخفیف"],
            ["category", "string", "درخت دسته‌بندی با تفکیک علامت > (مثال: زنانه > پایین تنه > شلوار)"],
            ["description", "object (Key-Value)", "مشخصات فنی شامل رنگ، جنس، سبک، فصل، قواره و ..."],
            ["brand", "string", "نام برند رسمی محصول (مانگ)"],
            ["GTIN", "string", "شناسه بین‌المللی کالا یا بارکد سازمانی"],
            ["shipping_cost", "number", "هزینه ارسال به ریال"],
            ["delivery_time", "number", "زمان تخمینی ارسال سفارش بر حسب روز کاری"]
        ]
    )

    add_code_block(doc,
"""# دریافت کامل خوراک محصولات به صورت JSON
curl -X GET "https://mong.ir/api/snappay/feed.json" \\
  -H "Accept: application/json"

# دریافت خوراک به همراه رفرش اجباری کش (Force Refresh)
curl -X GET "https://mong.ir/api/snappay/feed.json?refresh=true" \\
  -H "Accept: application/json"

# دریافت نسخه فشرده خوراک با هدر Gzip برای کاهش حجم ترافیک
curl -X GET "https://mong.ir/api/snappay/feed.json" \\
  -H "Accept-Encoding: gzip, deflate" \\
  -H "Accept: application/json" --compressed -o snappay_feed.json
""", caption="دستورات cURL برای روش دوم (Product Feed JSON)")

    add_code_block(doc,
"""[
  {
    "id": 41462,
    "title": "شلوار گاباردین بغل چاکدار مدل 715 مانگ",
    "subtitle": "Women's Gabardine Trousers 715",
    "link": "https://mong.ir/products-item/%D8%B4%D9%84%D9%88%D8%A7%D8%B1-%DA%AF%D8%A7%D8%A8%D8%A7%D8%B1%D8%AF%DB%8C%D9%86-%D8%A8%D8%BA%D9%84-%DA%87%D8%A7%DA%A9%D8%AF%D8%A7%D8%B1",
    "image_link": [
      "https://cdn.mong.ir/9/webgeneral/11c3a2eb-d255-4707-9e93-1243027928c3.webp",
      "https://cdn.mong.ir/9/webgeneral/7ce61789-8a0c-4ca7-ab3b-7f0450e0a9fc.webp"
    ],
    "availability": "in stock",
    "regular_price": 36800000,
    "sale_price": 25800000,
    "category": "زنانه > پایین تنه > شلوار",
    "description": {
      "برند": "مانگ",
      "سبک": "straight",
      "فصل": "پاییز و زمستان",
      "قواره": "Short",
      "رده سنی": "میانسال و جوان"
    },
    "brand": "مانگ",
    "GTIN": "0740000715",
    "shipping_cost": 0,
    "delivery_time": 3,
    "color": "مشکی",
    "size": "L"
  }
]
""", caption="نمونه خروجی استاندارد خوراک محصول JSON")

    # روش سوم: API ووکامرس
    add_persian_heading(doc, "۴. روش سوم: خوراک مبتنی بر API مانند ووکامرس (WooCommerce API Data Feed)", level=1)
    add_persian_p(doc, "تیم فنی مانگ جهت سهولت کامل در ادغام با موتور جستجوی اسنپ‌پی، وب‌سرویس رسمی افزونه SearchWise WooCommerce (ورژن 1.0.2) را به صورت Native پیاده‌سازی نموده است. این اندپوینت کاملاً منطبق بر رفتار افزونه رسمی ووکامرس سرچ‌وایز بوده و قابلیت‌های صفحه‌بندی، فیلتر با شناسه (ID)، فیلتر با اسلاگ (Slug)، دریافت متن کامل توضیحات و اعتبارسنجی با API Key را فراهم می‌سازد.")

    add_bullet_item(doc, "آدرس اندپوینت اصلی (REST API):", "POST https://mong.ir/wp-json/v1/product/feed")
    add_bullet_item(doc, "روش ارسال درخواست (HTTP Methods):", "پشتیبانی کامل از هر دو متد POST (پیشنهادی سرچ‌وایز) و GET")
    add_bullet_item(doc, "هدرهای مورد نیاز (Headers):", "Content-Type: application/json و هدر امنیتی x-api-key: YOUR_API_KEY_HERE")

    add_persian_heading(doc, "جدول پارامترهای ورودی اندپوینت ووکامرس", level=2)
    add_styled_table(doc,
        ["پارامتر", "نوع داده", "الزامی", "پیش‌فرض", "توضیح کارکرد"],
        [
            ["limit (یا size)", "integer", "اختیاری", "100", "تعداد کالاهای دریافتی در هر صفحه (حداکثر: 500)"],
            ["page", "integer", "اختیاری", "1", "شماره صفحه برای فرآیند صفحه‌بندی"],
            ["products", "string", "اختیاری", "-", "شناسه‌های کالا با کاما جهت استعلام خاص (مثال: '41462,48827')"],
            ["slugs", "string", "اختیاری", "-", "اسلاگ‌های کالا با کاما جهت استعلام مستقیم با نامک"],
            ["include_content", "boolean", "اختیاری", "false", "درج یا عدم درج محتوای تفصیلی متن معرفی کالا (content)"]
        ]
    )

    add_persian_heading(doc, "نمونه دستورات کامل cURL برای روش ووکامرس", level=2)

    add_code_block(doc,
"""# ۱. دریافت صفحه اول کاتالوگ با صفحه‌بندی (Pagination)
curl -X POST "https://mong.ir/wp-json/v1/product/feed" \\
  -H "Content-Type: application/json" \\
  -H "x-api-key: YOUR_API_KEY_HERE" \\
  -d '{
    "page": 1,
    "limit": 20
  }'

# ۲. استعلام بلادرنگ چند کالای مشخص بر اساس شناسه‌ها (IDs)
curl -X POST "https://mong.ir/wp-json/v1/product/feed" \\
  -H "Content-Type: application/json" \\
  -H "x-api-key: YOUR_API_KEY_HERE" \\
  -d '{
    "products": "41462,48827"
  }'

# ۳. استعلام بلادرنگ کالا بر اساس نامک (Slug)
curl -X POST "https://mong.ir/wp-json/v1/product/feed" \\
  -H "Content-Type: application/json" \\
  -H "x-api-key: YOUR_API_KEY_HERE" \\
  -d '{
    "slugs": "شلوار-گاباردین-بغل-چاکدار"
  }'

# ۴. دریافت اطلاعات همراه با متن کامل نقد و بررسی محصول (include_content: true)
curl -X POST "https://mong.ir/wp-json/v1/product/feed" \\
  -H "Content-Type: application/json" \\
  -H "x-api-key: YOUR_API_KEY_HERE" \\
  -d '{
    "page": 1,
    "limit": 10,
    "include_content": true
  }'

# ۵. فراخوانی به شیوه GET با Query Parameters (پشتیبانی موازی)
curl -X GET "https://mong.ir/wp-json/v1/product/feed?page=1&limit=20" \\
  -H "x-api-key: YOUR_API_KEY_HERE"
""", caption="دستورات کامل cURL برای روش سوم (WooCommerce Data Feed API)")

    add_code_block(doc,
"""{
  "count": 364,
  "max_pages": 19,
  "products": [
    {
      "id": 41462,
      "slug": "شلوار-گاباردین-بغل-چاکدار",
      "title": "شلوار گاباردین بغل چاکدار 715",
      "subtitle": "شلوار گاباردین بغل چاکدار 715",
      "regular_price": 36800000,
      "sale_price": 25800000,
      "availability": "instock",
      "category": [
        "زنانه",
        "پایین تنه",
        "شلوار"
      ],
      "image_link": [
        "https://cdn.mong.ir/9/webgeneral/11c3a2eb-d255-4707-9e93-1243027928c3.webp",
        "https://cdn.mong.ir/9/webgeneral/7ce61789-8a0c-4ca7-ab3b-7f0450e0a9fc.webp"
      ],
      "link": "https://mong.ir/products-item/%D8%B4%D9%84%D9%88%D8%A7%D8%B1-%DA%AF%D8%A7%D8%A8%D8%A7%D8%B1%D8%AF%DB%8C%D9%86-%D8%A8%D8%BA%D9%84-%DA%87%D8%A7%DA%A9%D8%AF%D8%A7%D8%B1",
      "short_description": "شلوار زنانه گاباردین با تن‌خور بسیار عالی و پارچه با دوام و مناسب مجلسی و روزمره",
      "description": {
        "سبک": "straight",
        "فصل": "4034",
        "گروه": "casual (روزمره)",
        "رده سنی": "میانسال (بین 35 تا 55)",
        "قواره": "Short",
        "برند": "مانگ"
      },
      "shipping_cost": 0,
      "delivery_time": 3,
      "brand": "مانگ",
      "GTIN": "0740000715"
    }
  ],
  "plugin_version": "1.0.2",
  "wc_version": "8.2.0",
  "wp_version": "6.4.0"
}
""", caption="نمونه پاسخ JSON مطابق با استاندارد رسمی افزونه SearchWise WooCommerce")

    # پیوست اندپوینت‌های اختصاصی و سازگار با دات‌نت
    add_persian_heading(doc, "۵. پیوست: وب‌سرویس‌های اختصاصی و موروثی (Legacy .NET & Native REST)", level=1)
    add_persian_p(doc, "علاوه بر مسیر ووکامرس، جهت پشتیبانی از اتصالات سابق یا پیاده‌سازی‌های اختصاصی شرکت داده‌فا / دات‌نت، اندپوینت‌های زیر نیز در سامانه مانگ فعال بوده و قابل استفاده می‌باشند:")

    add_styled_table(doc,
        ["عنوان سرویس", "متد و آدرس فراخوانی", "فرمت خروجی"],
        [
            ["لیست محصولات (.NET)", "POST/GET https://mong.ir/api/SnappPay/ProductList", "ResultDto با فیلدهای data، pageNumber و ..."],
            ["اطلاعات تک محصول (.NET)", "POST/GET https://mong.ir/api/SnappPay/ProductInfo?Id=41462", "ResultDto تک آیتم بر اساس Id یا Slug"],
            ["سرویس محصولات REST", "GET https://mong.ir/api/snappay/products?page=1&size=50", "JSON به همراه هدرهای X-Total-Count و ..."],
            ["تک محصول REST مستقیم", "GET https://mong.ir/api/snappay/products/{id_or_slug}", "JSON مستقیم مشخصات کالا"]
        ]
    )

    add_code_block(doc,
"""# فراخوانی وب‌سرویس موروثی دات‌نت (سازگار با سند dadehfa-snappay)
curl --location --request POST 'https://mong.ir/api/SnappPay/ProductList?PageNumber=1&PageSize=10' \\
  -H 'accept: application/json'

# استعلام تک محصول در وب‌سرویس دات‌نت با شناسه یا اسلاگ
curl --location --request POST 'https://mong.ir/api/SnappPay/ProductInfo?Id=41462' \\
  -H 'accept: application/json'

# فراخوانی وب‌سرویس Native مدرن
curl -X GET "https://mong.ir/api/snappay/products?page=1&size=20" \\
  -H "Accept: application/json"
""", caption="دستورات cURL برای وب‌سرویس‌های پیوست")

    # جمع‌بندی و نتیجه‌گیری
    add_persian_heading(doc, "۶. جمع‌بندی و پیشنهاد اجرایی", level=1)
    add_persian_p(doc, "با توجه به اینکه وب‌سرویس /wp-json/v1/product/feed بر روی دامنه اصلی مانگ (https://mong.ir) به صورت ۱۰۰٪ منطبق بر استاندارد SearchWise WooCommerce پیاده‌سازی شده است، پیشنهاد فنی ما فعال‌سازی موتور جستجوی اسنپ‌پی بر پایه روش سوم (WooCommerce API) یا روش دوم (Feed JSON) می‌باشد. این امر باعث حداکثر سرعت در بروزرسانی لحظه‌ای موجودی و قیمت کالاها در اپلیکیشن اسنپ‌پی خواهد شد.")

    output_path = "/mnt/sda2/mong/snappay_search_documentation.docx"
    doc.save(output_path)
    print(f"Document successfully created at: {output_path}")

    # Also save in back/docs/snappay/
    docs_dir_path = "/mnt/sda2/mong/back/docs/snappay/snappay_search_documentation.docx"
    doc.save(docs_dir_path)
    print(f"Document duplicate saved at: {docs_dir_path}")

if __name__ == "__main__":
    build_document()
