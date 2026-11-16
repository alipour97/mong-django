"""Complete product report, batched independently of the list's filters/pagination."""
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
import json

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill

from apps.erp.models import LebazaiImage
from apps.erp.store import online_stock
from apps.website.models import (
    HiddenImage, Product, ProductAIProfile, ProductCollection, ProductTag,
    ProductVariant, SiteSetting, VariantStock,
)


def _value(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, (date, datetime)):
        value = value.isoformat()
    if isinstance(value, str):
        return ILLEGAL_CHARACTERS_RE.sub("", value)
    if isinstance(value, Decimal):
        return float(value)
    return value


def _append(sheet, values, *, header=False):
    cells = []
    for value in values:
        cell = WriteOnlyCell(sheet, value=_value(value))
        # Names, barcodes and descriptions are data, never Excel formulas.
        if isinstance(cell.value, str):
            cell.data_type = "s"
        if header:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="214B8A")
        cell.alignment = Alignment(vertical="top", wrap_text=True)
        cells.append(cell)
    sheet.append(cells)
    sheet.export_row_count = getattr(sheet, "export_row_count", 0) + 1


def product_workbook():
    wb = Workbook(write_only=True)
    fields = [f for f in Product._meta.concrete_fields]
    variant_fields = list(ProductVariant._meta.concrete_fields)
    ai_fields = list(ProductAIProfile._meta.concrete_fields)
    sheets = {}
    headers = {
        "Products": [f.attname + (" (IRR)" if f.name in {"price", "sale_price"} else "") for f in fields]
            + ["subcode", "category", "brand", "qty_online_available", "colors", "image_count", "visible_image_count", "tags", "collections"],
        "Variants": [f.attname for f in variant_fields] + ["qty_online_available", "price_before_sale (IRR)", "price_after_sale (IRR)"],
        "Colors": ["product_id", "subcode", "color_id", "color", "color_value", "qty_online_available", "image_count", "visible_image_count"],
        "Images": ["product_id", "subcode", "color_id", "image_id", "position", "key", "source_url", "hidden"],
        "Features": ["product_id", "subcode", "source", "feature", "value"],
        "Warehouse Stock": ["product_id", "variant_id", "barcode", "warehouse_id", "warehouse", "qty", "online_warehouse"],
        "AI Details": [f.attname for f in ai_fields],
    }
    for title, columns in headers.items():
        sheet = sheets[title] = wb.create_sheet(title)
        sheet.sheet_view.rightToLeft = True
        sheet.freeze_panes = "C2"
        from openpyxl.utils import get_column_letter
        for i, name in enumerate(columns, 1):
            sheet.column_dimensions[get_column_letter(i)].width = 42 if any(x in name for x in ("description", "attributes", "url")) else 22
        _append(sheet, columns, header=True)
    setting = SiteSetting.objects.filter(is_deleted=False).first()
    minimum = float(setting.min_qty) if setting else 0
    hidden = set(HiddenImage.objects.values_list("key", flat=True))
    # Include inactive/out-of-stock products too. Deleted products are excluded.
    ids = list(Product.objects.filter(is_deleted=False).order_by("id").values_list("id", flat=True))
    for start in range(0, len(ids), 250):
        batch = ids[start:start + 250]
        products = Product.objects.filter(id__in=batch).select_related("category", "brand").order_by("id")
        variants = list(ProductVariant.objects.filter(product_id__in=batch, is_deleted=False).order_by("id"))
        online_ids = set(online_stock().filter(variant__product_id__in=batch).values_list("id", flat=True))
        stock = list(VariantStock.objects.filter(variant__product_id__in=batch).select_related("variant"))
        qty = defaultdict(float)
        for row in stock:
            if row.id in online_ids:
                qty[row.variant_id] += float(row.qty)
            _append(sheets["Warehouse Stock"], [row.variant.product_id, row.variant_id, row.variant.barcode,
                row.warehouse_id, row.warehouse_title, row.qty, row.id in online_ids])
        available = {v.id: max(0, qty[v.id] - minimum) for v in variants}
        images = defaultdict(list)
        for img in LebazaiImage.objects.filter(product_id__in=batch).order_by("product_id", "color_id", "position", "id"):
            images[img.product_id].append(img)
        profiles = {a.product_id: a for a in ProductAIProfile.objects.filter(product_id__in=batch)}
        tags, collections = defaultdict(list), defaultdict(list)
        for link in ProductTag.objects.filter(product_id__in=batch, is_deleted=False).select_related("tag"):
            tags[link.product_id].append(link.tag.title)
        for link in ProductCollection.objects.filter(product_id__in=batch, is_deleted=False).select_related("collection"):
            collections[link.product_id].append(link.collection.title)
        grouped = defaultdict(list)
        for v in variants:
            grouped[v.product_id].append(v)
        for p in products:
            ai = profiles.get(p.id)
            subcode = (ai.subcode if ai else "") or p.barcode
            vs, photos = grouped[p.id], images[p.id]
            _append(sheets["Products"], [getattr(p, f.attname) for f in fields] + [subcode,
                p.category.title if p.category else "", p.brand.title if p.brand else "",
                sum(available[v.id] for v in vs), ", ".join(dict.fromkeys(v.color_name for v in vs)),
                len(photos), sum(i.key not in hidden for i in photos), tags[p.id], collections[p.id]])
            colors = {}
            for v in vs:
                _append(sheets["Variants"], [getattr(v, f.attname) for f in variant_fields] + [available[v.id], p.price, p.sale_price])
                c = colors.setdefault(v.color_id, [v.color_name, v.color_value, 0])
                c[2] += available[v.id]
            for img in photos:
                colors.setdefault(img.color_id, ["", "", 0])
                _append(sheets["Images"], [p.id, subcode, img.color_id, img.id, img.position, img.key, img.source_url, img.key in hidden])
            for cid, (name, value, count) in colors.items():
                color_photos = [i for i in photos if i.color_id == cid]
                _append(sheets["Colors"], [p.id, subcode, cid, name, value, count, len(color_photos), sum(i.key not in hidden for i in color_photos)])
            for source, attrs in [("product", p.attributes), ("AI", ai.attributes if ai else {})]:
                for key, value in (attrs.items() if isinstance(attrs, dict) else [("attributes", attrs)]):
                    _append(sheets["Features"], [p.id, subcode, source, key, value])
            if ai:
                _append(sheets["AI Details"], [getattr(ai, f.attname) for f in ai_fields])
    for sheet in sheets.values():
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers[sheet.title]))}{sheet.export_row_count}"
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output
