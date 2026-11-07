"""
Products/* — the admin's product pages, as the old ProductsController.

Products, prices, stock, colors and sizes come from the sales software's sync and
photos from LEBAZAI; the admin edits what only the site has: slug, descriptions,
«نمایش در ترب». Every synced product is listed, ShowOnPage narrows the list to what
the site shows or does not show.

    GET  Products/GetAllProduct?Search=&ParentCategoryIds=&ChildeCategoryIds=&CollectionIds=&FromPrice=&ToPrice=
         &QtyFrom=&QtyTo=&HasQty=&HasReduction=&ShowOnPage=&HasScore=&HasMedia=&hasLongDescription=
         &hasShortDescription=&pageNumber=&pageSize=
    GET  Products/GetProductLables
    GET  Products/GetDetailProduct/{id}
    POST Products/SetImageVisibility {key, hidden}   (new: hide a Samian photo on the site)
    POST Products/UpdateSlug {productId, slug, hasManualSlug}
    POST Products/ValidateSlug?slug=&productId=
    GET  Products/ShowInTrob?productId=&show=      (no productId: every product)
    GET  Products/{id}/descriptions,  POST Products/{id}/descriptions {longDescriptionHtml, shortDescriptionHtml}
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django.db.models import Max, Min, Sum
from django.utils import timezone

from apps.erp.store import online_stock
from apps.storefront import catalog
from apps.website import slugs
from apps.website.models import (
    Collection,
    HiddenImage,
    MediaAttachment,
    Product,
    ProductAIProfile,
    ProductCollection,
    ProductTag,
    SelectedProduct,
)

from .. import products as index
from ..envelope import fail, ok
from ..paging import int_list, paginated, to_bool, to_int, sort_rows
from .auth import AdminView

NOT_FOUND = "محصولی با این شناسه پیدا نشد."


def _number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _warehouses(bundle: catalog.ProductBundle, pids: list[int]) -> dict[int, dict[int, list[dict]]]:
    """product id -> variant id -> [{warehouseId, warehouseTitle, qty, realQty}] in the online warehouses."""
    variant_of = {v.id: (pid, v) for pid in pids for v in bundle.variants.get(pid, [])}
    out: dict[int, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in (
        online_stock().filter(variant_id__in=variant_of, qty__gt=0)
        .values("variant_id", "warehouse_id", "warehouse_title").annotate(total=Sum("qty"))
    ):
        pid, v = variant_of[r["variant_id"]]
        real = float(r["total"] or 0)
        out[pid][v.id].append({
            "productVariantId": v.id, "warehouseId": r["warehouse_id"], "warehouseTitle": r["warehouse_title"],
            "qty": max(0.0, real - bundle.min_qty), "realQty": real,
        })
    return out


class FiltersView(AdminView):
    """GET Products/GetFilters?parentCategoryId= -> {minPrice, maxPrice, collections, categories} for the list's filters."""

    def get(self, request):
        prices = [r.price for r in index.admin_rows() if r.price > 0] or [0]
        tree = catalog.category_tree()
        parent = to_int(request.query_params.get("parentCategoryId"))
        if parent is None:
            cats = list(tree.nodes.values())
        else:
            cats = [tree.nodes[i] for i in tree.descendants(parent) if i != parent and i in tree.nodes]
        return ok({"result": {
            "minPrice": min(prices), "maxPrice": max(prices),
            "collections": [{"id": c.id, "title": c.title} for c in Collection.objects.filter(is_deleted=False).order_by("id")],
            "categories": [{"id": c.id, "title": c.title, "isParent": c.parent_id is None} for c in sorted(cats, key=lambda c: c.id)],
        }})


class ListView(AdminView):
    def get(self, request):
        q = request.query_params
        rows = index.admin_rows()
        tree = catalog.category_tree()

        cat_ids = int_list(q.getlist("ChildeCategoryIds")) or int_list(q.getlist("ParentCategoryIds"))
        if cat_ids:
            allowed = set().union(*(tree.descendants(c) for c in cat_ids))
            rows = [r for r in rows if r.category_id in allowed]
        collection_ids = int_list(q.getlist("CollectionIds"))
        if collection_ids:
            in_collections = set(ProductCollection.objects.filter(
                collection_id__in=collection_ids, is_deleted=False).values_list("product_id", flat=True))
            rows = [r for r in rows if r.id in in_collections]
        search = catalog.norm(q.get("Search") or "")
        if search:
            rows = [r for r in rows if search in r.title or search in r.barcode]

        for key, test in (
            ("FromPrice", lambda r, v: r.price >= v), ("ToPrice", lambda r, v: r.price <= v),
            ("QtyFrom", lambda r, v: r.qty >= v), ("QtyTo", lambda r, v: r.qty <= v),
        ):
            value = _number(q.get(key))
            if value is not None:
                rows = [r for r in rows if test(r, value)]
        show_on_page = to_bool(q.get("ShowOnPage"))
        if show_on_page is not None:
            rows = [r for r in rows if r.on_site == show_on_page]
        for key, attr in (
            ("HasQty", lambda r: r.qty > 0), ("HasReduction", lambda r: r.reduction > 0),
            ("HasScore", lambda r: r.has_score), ("HasMedia", lambda r: r.media_count > 0),
            ("hasLongDescription", lambda r: r.has_long_description),
            ("hasShortDescription", lambda r: r.has_short_description),
        ):
            want = to_bool(q.get(key) if key in q else q.get(key[0].upper() + key[1:]))
            if want is not None:
                rows = [r for r in rows if attr(r) == want]

        rows = sort_rows(rows, q, {
            "price": lambda r: r.price, "reduction": lambda r: r.reduction, "mediaCount": lambda r: r.media_count,
            "qty": lambda r: r.qty, "isSaleable": lambda r: r.on_site,
        })
        page = paginated(rows, to_int(q.get("pageNumber"), 1), to_int(q.get("pageSize"), 10))
        pids = [r.id for r in page["items"]]
        bundle = catalog.ProductBundle.load(pids, with_images=False)
        stock = _warehouses(bundle, pids)
        collections: dict[int, list[str]] = defaultdict(list)
        for pid, title in ProductCollection.objects.filter(product_id__in=pids, is_deleted=False).values_list(
                "product_id", "collection__title"):
            collections[pid].append(title)

        def item(r: index.AdminRow) -> dict:
            p = bundle.products.get(r.id)
            category = tree.nodes.get(r.category_id)
            parent = tree.nodes.get(category.parent_id) if category else None
            warehouses = {w["warehouseId"]: w["warehouseTitle"] for ws in stock[r.id].values() for w in ws}
            return {
                "id": r.id, "name": r.name, "barcode": r.barcode, "price": r.price, "reduction": r.reduction,
                "mediaCount": r.media_count, "categoryName": category.title if category else "",
                "parentCategoryName": parent.title if parent else "", "collectionName": "/".join(collections[r.id]),
                "qty": r.qty, "isSaleable": r.on_site,
                "variantIds": [v.id for v in bundle.variants.get(r.id, [])] if p else [],
                "warehouses": [{"id": k, "title": v} for k, v in sorted(warehouses.items(), key=lambda kv: kv[1])],
                "hasLongDescription": r.has_long_description, "hasShortDescription": r.has_short_description,
            }

        page["items"] = [item(r) for r in page["items"]]
        return ok({"result": page})


class LabelsView(AdminView):
    """GET Products/GetProductLables -> the four counters above the product list."""

    def get(self, request):
        rows = index.admin_rows()
        available = sum(1 for r in rows if r.qty > 0)
        return ok({"result": {
            "totalProduct": len(rows), "availableProducts": available,
            "productWithReduction": sum(1 for r in rows if r.reduction > 0),
            "productNonExistent": len(rows) - available,
        }})


class DetailView(AdminView):
    def get(self, request, product_id: int):
        # Hidden photos are included and marked (isHidden) so they can be shown again.
        bundle = catalog.ProductBundle.load([product_id], include_hidden=True)
        # Every color of the sales software, also those the site leaves out for having no photo (the panel marks
        # them), so the admin sees what is missing.
        bundle.only_media = False
        p = bundle.products.get(product_id)
        if not p or p.is_deleted:
            return fail(NOT_FOUND, 404)
        pr = bundle.pricing(product_id)
        stock = _warehouses(bundle, [product_id])[product_id]
        details = bundle.details(product_id, pr, with_barcode=True)
        variants = {v.id: v for v in bundle.variants.get(product_id, [])}
        for group in details:
            for item in group["items"]:
                v = variants.get(item.get("productVariantId"))
                if v is not None:
                    ws = stock.get(v.id, [])
                    item["warehouses"] = ws
                    item["realQty"] = sum(w["realQty"] for w in ws)
        category = p.category
        parent = category.parent if category else None
        guide = MediaAttachment.objects.filter(
            table=MediaAttachment.Table.PRODUCTS, record_id=product_id, is_product_guid=True, is_deleted=False,
        ).first()
        return ok({"result": {
            "id": p.id, "productId": p.id, "barcode": p.barcode,
            "categoryId": p.category_id, "categoryName": category.title if category else "",
            "parentCategoryId": parent.id if parent else None, "parentCategoryName": parent.title if parent else "",
            "brandId": catalog.MONG_BRAND["id"], "brandTitle": catalog.MONG_BRAND["title"],
            "title": p.title, "originalPrice": pr.base, "reduction": pr.reduction, "priceAfterReduction": pr.after,
            "description": p.description or None, "shortDesc": p.short_desc or None, "showTorob": p.show_torob,
            "slug": p.slug, "hasManualSlug": p.has_manual_slug,
            "tags": catalog.tags_for(ProductTag, "product_id", [product_id]).get(product_id, []),
            "mainImages": bundle.main_images(product_id),
            "guidMedia": {"guidId": guide.id, "guidMediaUrl": catalog.media_dict(guide)["mediaUrl"]} if guide else None,
            "details": details,
        }})


def _validate_slug(slug: str, product_id: int | None) -> dict:
    errors = []
    valid_format = slugs.is_valid(slug) and slug == slug.lower()
    if not valid_format:
        errors.append("فرمت اسلاگ معتبر نیست.")
    valid_length = bool(slug.strip()) and len(slug) <= slugs.MAX_LENGTH
    if not valid_length:
        errors.append("طول اسلاگ بیشتر از حد مجاز است.")
    others = Product.objects.filter(slug_key=slugs.slug_key(slug))
    if product_id:
        others = others.exclude(id=product_id)
    unique = not others.exists()
    if not unique:
        errors.append("این اسلاگ قبلاً استفاده شده است.")
    return {"isFormatValid": valid_format, "isLengthValid": valid_length, "isUnique": unique,
            "errors": errors, "allValidationsPass": not errors}


class ValidateSlugView(AdminView):
    def post(self, request):
        q = request.query_params
        return ok({"result": _validate_slug(q.get("slug") or "", to_int(q.get("productId")))})


class UpdateSlugView(AdminView):
    """A manual slug is checked; without one the slug is rebuilt from the title (unique, -2, -3 ...)."""

    def post(self, request):
        p = Product.objects.filter(id=to_int(request.data.get("productId"))).first()
        if not p:
            return fail(NOT_FOUND, 404)
        manual = bool(request.data.get("hasManualSlug"))
        wanted = (request.data.get("slug") or "").strip()
        if manual and wanted:
            check = _validate_slug(wanted, p.id)
            if not check["allValidationsPass"]:
                return fail(" | ".join(check["errors"]), 400)
            slug = wanted
        else:
            taken = set(Product.objects.exclude(id=p.id).values_list("slug_key", flat=True))
            slug = slugs.make_slug(p.title, taken, fallback=p.barcode)
        p.slug, p.has_manual_slug = slug, manual
        p.save(update_fields=["slug", "slug_key", "has_manual_slug"])
        index.clear()
        return ok({"result": True})


class TorobView(AdminView):
    def get(self, request):
        show = bool(to_bool(request.query_params.get("show")))
        pid = to_int(request.query_params.get("productId"))
        if pid is None:
            Product.objects.update(show_torob=show)
            return ok({"result": True})
        if not Product.objects.filter(id=pid).update(show_torob=show):
            return fail(NOT_FOUND, 404)
        return ok({"result": True})


class ImageVisibilityView(AdminView):
    """
    POST Products/SetImageVisibility {"key", "hidden"} — hide a Samian photo on the site, or show it again.
    New endpoint (the old panel uploaded its own photos); key comes with each photo of GetDetailProduct.
    """

    def post(self, request):
        key = (request.data.get("key") or "").strip()
        if not key.startswith("s/"):
            return fail("شناسه‌ی عکس معتبر نیست.", 400)
        if to_bool(request.data.get("hidden")):
            HiddenImage.objects.get_or_create(key=key, defaults={"hidden_by": request.user.username})
        else:
            HiddenImage.objects.filter(key=key).delete()
        index.clear()
        return ok({"result": True})


class DescriptionsView(AdminView):
    """«عنوان هیبرید» and «توضیح تکمیلی»: LEBAZAI's AI copy, until the site's own text replaces it here."""

    def get(self, request, product_id: int):
        p = Product.objects.filter(id=product_id).first()
        if not p:
            return fail(NOT_FOUND, 404)
        ai = ProductAIProfile.objects.filter(product=p).first()
        return ok({"result": {"longDescriptionHtml": p.long_description_html or (ai.description if ai else "") or None,
                              "shortDescriptionHtml": p.short_description_html or (ai.title if ai else "") or None}})

    def post(self, request, product_id: int):
        p = Product.objects.filter(id=product_id).first()
        if not p:
            return fail(NOT_FOUND, 404)
        p.long_description_html = request.data.get("longDescriptionHtml") or ""
        p.short_description_html = request.data.get("shortDescriptionHtml") or ""
        p.save(update_fields=["long_description_html", "short_description_html"])
        index.clear()
        return ok({"result": True})


# -----------------------------------------------------------------------------
# Size guides (adding one goes through FileMedia/AddFilesToEntity with ProductGuides/CategoryGuides)
# -----------------------------------------------------------------------------
class DeleteGuideView(AdminView):
    """GET Products/DeleteGuid?productId= and Category/DeleteGuid?categoryId=."""

    table: int = MediaAttachment.Table.PRODUCTS
    param: str = "productId"

    def get(self, request):
        record = to_int(request.query_params.get(self.param))
        removed = MediaAttachment.objects.filter(
            table=self.table, record_id=record, is_product_guid=True, is_deleted=False,
        ).update(is_deleted=True)
        if not removed:
            return fail("تصویر پیدا نشد.", 404)
        index.clear()
        return ok({"result": True})


# -----------------------------------------------------------------------------
# Selected products (the home page's «منتخب» row and the «منتخب» sort)
# -----------------------------------------------------------------------------
WEIGHT_STEP = Decimal(256)


def _cards(pids: list[int], selections: dict[int, SelectedProduct]) -> list[dict]:
    """Storefront product cards, plus the selection's id, weight and first color."""
    bundle = catalog.ProductBundle.load(pids)
    out = []
    for pid in pids:
        if pid not in bundle.products:
            continue
        item = bundle.list_item(pid)
        s = selections.get(pid)
        item["selectedProductId"] = s.id if s else None
        item["sortingWeight"] = float(s.sorting_weight) if s else None
        if s and s.color_id and item["details"]:
            item["details"][0]["defaultItemId"] = s.color_id
        out.append(item)
    return out


def _selections() -> dict[int, SelectedProduct]:
    return {s.product_id: s for s in SelectedProduct.objects.filter(is_deleted=False).order_by("sorting_weight", "id")}


class SelectedListView(AdminView):
    def get(self, request):
        selections = _selections()
        return ok({"result": _cards(list(selections), selections)})


class SelectedAddView(AdminView):
    """POST Products/AddSelectedProduct?productId=&featureValueId= -> adds it (or moves it) to the end."""

    def post(self, request):
        pid = to_int(request.query_params.get("productId"))
        if not Product.objects.filter(id=pid, is_deleted=False).exists():
            return fail(NOT_FOUND, 404)
        color = to_int(request.query_params.get("featureValueId"))
        top = SelectedProduct.objects.filter(is_deleted=False).aggregate(m=Max("sorting_weight"))["m"] or Decimal(0)
        s = SelectedProduct.objects.filter(product_id=pid).first()
        if s is None:
            s = SelectedProduct.objects.create(product_id=pid, color_id=color, sorting_weight=top + WEIGHT_STEP,
                                               created=timezone.now())
        else:
            s.color_id = color if color is not None else s.color_id
            if s.sorting_weight != top or s.is_deleted:
                s.sorting_weight = top + WEIGHT_STEP
            s.is_deleted = False
            s.save(update_fields=["color_id", "sorting_weight", "is_deleted"])
        index.clear()
        return ok({"id": s.id})


class SelectedDeleteView(AdminView):
    def post(self, request):
        qs = SelectedProduct.objects.filter(is_deleted=False)
        sid, pid = to_int(request.query_params.get("id")), to_int(request.query_params.get("productId"))
        if sid is not None:
            qs = qs.filter(id=sid)
        if pid is not None:
            qs = qs.filter(product_id=pid)
        s = qs.first() if (sid is not None or pid is not None) else None
        if s is None:
            return fail("ایتمی با این شناسه یافت نشد.", 404)
        s.delete()
        index.clear()
        return ok({"result": True})


class SelectedWeightView(AdminView):
    """Like the old panel: below the smallest weight -> half of it; above the largest -> largest + 256."""

    def post(self, request):
        s = SelectedProduct.objects.filter(id=to_int(request.query_params.get("id")), is_deleted=False).first()
        if s is None:
            return fail("ایتمی با این شناسه یافت نشد.", 404)
        try:
            weight = Decimal(str(request.query_params.get("sortingWeight")))
        except (InvalidOperation, TypeError):
            return fail("وزن نامعتبر است", 400)
        if weight == s.sorting_weight:
            return ok({"result": True})
        if weight <= 0:
            return ok({"result": False})
        agg = SelectedProduct.objects.filter(is_deleted=False).aggregate(lo=Min("sorting_weight"), hi=Max("sorting_weight"))
        if agg["lo"] is not None and weight < agg["lo"]:
            weight = agg["lo"] / 2
        if agg["hi"] is not None and weight > agg["hi"]:
            weight = agg["hi"] + WEIGHT_STEP
        s.sorting_weight = weight
        s.save(update_fields=["sorting_weight"])
        index.clear()
        return ok({"result": True})


class SelectedClearView(AdminView):
    def post(self, request):
        qs = SelectedProduct.objects.filter(is_deleted=False)
        if not qs.exists():
            return fail("لیست قبلا خالی شده است.", 404)
        qs.delete()
        index.clear()
        return ok({"result": True})


class BriefProductsView(AdminView):
    """
    GET Products/GetBriefProducts?Search=&CategoryIds=&FeatureValueIds=&pageNumber=&pageSize=
    Products shown on the site (the ones worth selecting), as storefront cards.
    """

    def get(self, request):
        q = request.query_params
        payload = {
            "search": q.get("Search") or "",
            "filteredCategoryIds": int_list(q.getlist("CategoryIds")),
            "filteredFeatureId": int_list(q.getlist("FeatureValueIds")),
            "sortCriteriaId": 2,
        }
        rows = catalog.filter_rows(payload)
        page = paginated(rows, to_int(q.get("pageNumber"), 1), to_int(q.get("pageSize"), 10))
        page["items"] = _cards([r.id for r in page["items"]], _selections())
        return ok({"result": page})
