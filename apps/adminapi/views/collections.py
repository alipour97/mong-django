"""
Collection/* — collections (a set of products and categories with a running
period), as the old Collection controller.

A product or category can be in only one running collection: saving one that
is already in another active, running collection is refused with the ids.
The collection's "reduction" is stored but not applied: prices are Samian's.
Images are attached through FileMedia/AddFilesToEntity (entity "Collections").

As in the old API, All, <id> and SoftDelete answer without the {data, ...}
envelope; create and update use it.

    GET  Collection/All?Search=&isActive=&BeginningDateFrom=&EndDateTo=&pageNumber=&pageSize=
    GET  Collection/<id>
    POST Collection          {title, inMainPage, isActive, displayPriority, beginningDate, endDate, reduction, categoryIds, productIds}
    POST Collection/<id>     same body
    GET  Collection/SoftDelete/<id>
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework.response import Response

from apps.storefront import catalog
from apps.storefront.envelope import jalali
from apps.website.models import Category, Collection, CollectionCategory, MediaAttachment, Product, ProductCollection

from .. import products as index
from ..envelope import fail, ok
from ..paging import int_list, paginated, to_bool, to_int
from .auth import AdminView
from .comments import _date

NOT_FOUND = "کالکشن وجود ندارد."
IN_OTHER = "برخی از دسته‌بندی‌ها یا کالاها در حال حاضر در مجموعه دیگری وجود دارند."


def _media(ids) -> dict[int, list[dict]]:
    return catalog.attachments(MediaAttachment.Table.COLLECTIONS, ids)


def _links(model, collection_ids, field: str) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for cid, oid in model.objects.filter(collection_id__in=collection_ids, is_deleted=False).exclude(**{field: None}).values_list("collection_id", field):
        out.setdefault(cid, []).append(oid)
    return out


def _summary(c: Collection, media: list, site_pids: set[int], cat_rows: dict[int, int], cats: list[int], pids: list[int]) -> dict:
    return {
        "id": c.id, "mapId": c.map_id, "title": c.title,
        "beginningDate": jalali(c.beginning_date, with_time=False), "endDate": jalali(c.end_date, with_time=False),
        "created": jalali(c.created, with_time=False), "inMainPage": c.in_main_page, "isActive": c.is_active,
        "reduction": float(c.reduction), "medias": media,
        "productCount": len(set(pids) & site_pids) + sum(cat_rows.get(cat, 0) for cat in cats),
    }


class AllView(AdminView):
    def get(self, request):
        q = request.query_params
        qs = Collection.objects.filter(is_deleted=False)
        active = to_bool(q.get("isActive", q.get("IsActive")))
        if active is not None:
            qs = qs.filter(is_active=active)
        if begin := _date(q.get("BeginningDateFrom")):
            qs = qs.filter(beginning_date__gte=begin)
        if end := _date(q.get("EndDateTo"), end=True):
            qs = qs.filter(end_date__lte=end)
        search = catalog.norm(q.get("Search") or q.get("search") or "")
        cols = [c for c in qs.order_by("-id") if not search or search in catalog.norm(c.title)]
        page = paginated(cols, to_int(q.get("pageNumber"), 1), to_int(q.get("pageSize"), 30))

        ids = [c.id for c in page["items"]]
        media, cats, prods = _media(ids), _links(CollectionCategory, ids, "category_id"), _links(ProductCollection, ids, "product_id")
        rows = index.admin_rows()
        tree = catalog.category_tree()
        per_cat: dict[int, int] = {}
        for r in rows:
            per_cat[r.category_id] = per_cat.get(r.category_id, 0) + 1
        cat_rows = {cat: sum(per_cat.get(d, 0) for d in tree.descendants(cat)) for cl in cats.values() for cat in cl}
        site_pids = {r.id for r in rows}
        page["items"] = [
            _summary(c, media.get(c.id, []), site_pids, cat_rows, cats.get(c.id, []), prods.get(c.id, [])) for c in page["items"]
        ]
        return Response({"result": page})


class DetailView(AdminView):
    def get(self, request, collection_id: int):
        c = Collection.objects.filter(id=collection_id, is_deleted=False).first()
        if not c:
            return Response({"message": NOT_FOUND}, status=404)
        return Response({"result": _detail(c)})

    def post(self, request, collection_id: int):
        c = Collection.objects.filter(id=collection_id, is_deleted=False).first()
        if not c:
            return fail("مجموعه با این شناسه یافت نشد", 404)
        return _save(request, c)


def _detail(c: Collection) -> dict:
    rows = {r.id: r for r in index.admin_rows()}
    tree = catalog.category_tree()
    pids = ProductCollection.objects.filter(collection=c, is_deleted=False).exclude(product_id=None).values_list("product_id", flat=True)
    products = [
        {"productId": p.id, "title": p.title, "categoryId": p.category_id, "isActive": p.is_active}
        for p in Product.objects.filter(id__in=[i for i in pids if i in rows]).order_by("id")
    ]
    cats = Category.objects.filter(collection_links__collection=c, collection_links__is_deleted=False, is_deleted=False).distinct()
    categories = []
    for cat in cats.order_by("id"):
        under = tree.descendants(cat.id)
        categories.append({
            "categoryId": cat.id, "categoryTitle": cat.title, "parentId": cat.parent_id,
            "productCount": sum(1 for r in rows.values() if r.category_id in under),
        })
    media = _media([c.id]).get(c.id, [])
    return {
        "id": c.id, "title": c.title, "inMainPage": c.in_main_page, "isActive": c.is_active,
        "beginningDate": jalali(c.beginning_date, with_time=False), "endDate": jalali(c.end_date, with_time=False),
        "created": jalali(c.created, with_time=False), "reduction": float(c.reduction),
        "displayPriority": c.display_priority, "products": products, "categories": categories,
        "haveMedia": bool(media), "medias": media,
    }


def _in_other(collection_id: int | None, cat_ids: list[int], pids: list[int]) -> tuple[list[int], list[int]]:
    """Categories and products already in another active collection that is running now."""
    now = timezone.now()
    running = (
        Collection.objects.filter(is_deleted=False, is_active=True)
        .exclude(id=collection_id).exclude(beginning_date__gt=now).exclude(end_date__lt=now)
    )
    cats = CollectionCategory.objects.filter(collection__in=running, is_deleted=False, category_id__in=cat_ids)
    prods = ProductCollection.objects.filter(collection__in=running, is_deleted=False, product_id__in=pids)
    return sorted(set(cats.values_list("category_id", flat=True))), sorted(set(prods.values_list("product_id", flat=True)))


def _set_links(model, field: str, collection: Collection, ids: list[int]) -> None:
    links = model.objects.filter(collection=collection)
    links.exclude(**{f"{field}__in": ids}).filter(is_deleted=False).update(is_deleted=True, last_modified=timezone.now())
    links.filter(**{f"{field}__in": ids}, is_deleted=True).update(is_deleted=False, last_modified=timezone.now())
    have = set(links.values_list(field, flat=True))
    model.objects.bulk_create(model(collection=collection, **{field: i}, created=timezone.now()) for i in ids if i not in have)


def _save(request, c: Collection | None):
    d = request.data if isinstance(request.data, dict) else {}
    title = (d.get("title") or "").strip()
    if not title:
        return fail("عنوان مجموعه الزامی است.", 400)
    if len(title) > 100:
        return fail("عنوان مجموعه نمی‌تواند بیشتر از 100 کاراکتر باشد.", 400)
    cat_ids, pids = list(dict.fromkeys(int_list(d.get("categoryIds")))), list(dict.fromkeys(int_list(d.get("productIds"))))

    bad_cats, bad_pids = _in_other(c.id if c else None, cat_ids, pids)
    if bad_cats or bad_pids:
        result = {"faildCategoryIds": bad_cats, "faildProductIds": bad_pids, "resultStatus": IN_OTHER, "statusCode": 409}
        return fail(IN_OTHER if c else "این دسته بندی یا محصول در کالکشن دیگری وجود دارد.", 409, {"result": result})
    missing_cats = set(cat_ids) - set(Category.objects.filter(id__in=cat_ids, is_deleted=False).values_list("id", flat=True))
    missing_pids = set(pids) - set(Product.objects.filter(id__in=pids, is_deleted=False).values_list("id", flat=True))
    if missing_cats or missing_pids:
        msg = "برخی از شناسه کالاها یا دسته‌بندی‌ها وجود ندارند."
        result = {"faildCategoryIds": sorted(missing_cats), "faildProductIds": sorted(missing_pids), "resultStatus": msg, "statusCode": 404}
        return fail(msg, 404, {"result": result})

    begin, end = _date(d.get("beginningDate")), _date(d.get("endDate"))
    reduction = d.get("reduction")
    with transaction.atomic():
        is_new = c is None
        c = c or Collection(created=timezone.now())
        c.title = title
        c.in_main_page = bool(to_bool(d.get("inMainPage")))
        c.is_active = bool(to_bool(d.get("isActive")))
        c.display_priority = to_int(d.get("displayPriority"), 0)
        # As before: a new collection without dates is always running; an edit keeps the old dates.
        c.beginning_date = begin if begin or is_new else c.beginning_date
        c.end_date = end if end or is_new else c.end_date
        if reduction is not None or is_new:
            c.reduction = float(reduction or 0)
        c.last_modified = timezone.now()
        c.save()
        _set_links(CollectionCategory, "category_id", c, cat_ids)
        _set_links(ProductCollection, "product_id", c, pids)
    catalog.clear_caches()
    if is_new:
        return ok({"result": c.id})
    return ok({"result": {"faildCategoryIds": [], "faildProductIds": [], "resultStatus": "تغییرات مجموعه مورد نظر با موفقیت ثبت گردید", "statusCode": 200}})


class CreateView(AdminView):
    def post(self, request):
        return _save(request, None)


class DeleteView(AdminView):
    def get(self, request, collection_id: int):
        c = Collection.objects.filter(id=collection_id, is_deleted=False).first()
        if not c:
            return Response({"message": "خطا در حذف منطقی مجموعه.", "error": NOT_FOUND}, status=500)
        c.is_deleted, c.last_modified = True, timezone.now()
        c.save(update_fields=["is_deleted", "last_modified"])
        catalog.clear_caches()
        return Response({"message": "عملیات موفقیت آمیز بود"})
