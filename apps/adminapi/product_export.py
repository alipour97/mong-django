"""Complete product report, batched independently of the list's filters/pagination."""
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
import json

from django.conf import settings
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill

from apps.erp.models import LebazaiImage
from apps.erp.store import online_stock
from apps.website.models import (
    HiddenImage, Product, ProductAIProfile,
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


_HEADER_FONT = Font(bold=True, color="FFFFFF")
_HEADER_FILL = PatternFill("solid", fgColor="214B8A")
_HEADER_ALIGNMENT = Alignment(vertical="top", wrap_text=True)


def _append(sheet, values, *, header=False):
    cells = []
    for value in values:
        value = _value(value)
        # Numeric/empty cells can use openpyxl's fast path. Only strings need
        # explicit typing to preserve codes and prevent formula interpretation.
        if not header and not isinstance(value, str):
            cells.append(value)
            continue
        cell = WriteOnlyCell(sheet, value=value)
        # Names, barcodes and descriptions are data, never Excel formulas.
        if isinstance(cell.value, str):
            cell.data_type = "s"
        if header:
            cell.font = _HEADER_FONT
            cell.fill = _HEADER_FILL
            cell.alignment = _HEADER_ALIGNMENT
        cells.append(cell)
    sheet.append(cells)
    sheet.export_row_count = getattr(sheet, "export_row_count", 0) + 1


def product_workbook():
    wb = Workbook(write_only=True)
    # Explicit report schema follows the reviewed workbook (red columns removed).
    names = {"created", "last_modified", "title", "price", "reduction", "show_torob",
             "view_count", "product_season_title", "on_sale", "erp_id", "sale_price"}
    fields = [f for f in Product._meta.concrete_fields if f.name in names]
    sheets = {}
    headers = {
        "Products": [f.attname + (" (IRR)" if f.name in {"price", "sale_price"} else "") for f in fields]
            + ["subcode", "category", "brand", "qty_online_available", "colors", "visible_image_count"],
        "Warehouse Stock": ["product_id", "variant_id", "barcode", "warehouse_id", "warehouse", "qty", "online_warehouse"],
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
    ids = list(Product.objects.filter(is_deleted=False, brand_id__in=settings.STOREFRONT_BRAND_IDS).order_by("id").values_list("id", flat=True))
    for start in range(0, len(ids), 1000):
        batch = ids[start:start + 1000]
        products = Product.objects.filter(id__in=batch).select_related("category", "brand").order_by("id")
        variants = list(ProductVariant.objects.filter(product_id__in=batch, is_deleted=False).order_by("id"))
        online_ids = set(online_stock().filter(variant__product_id__in=batch).values_list("id", flat=True))
        stock = list(online_stock().filter(variant__product_id__in=batch, variant__is_deleted=False).select_related("variant"))
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
                sum(i.key not in hidden for i in photos)])
    for sheet in sheets.values():
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers[sheet.title]))}{sheet.export_row_count}"
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output
