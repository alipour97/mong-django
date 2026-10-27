"""
TagControllers/* — product and category tags, as the old TagControllers.

The AddTagsTo* calls set the full tag list of a product or category (tags not
in the list are removed). The panel sends the bulk ones as a bare list; the
old API's {products: [...]} / {categories: [...]} is accepted too.

    POST TagControllers/GetAllTags {search, pageNumber, pageSize}
    POST TagControllers/AddTag {title, parentId}
    POST TagControllers/AddTagsToProduct {productId, tagIds},   AddTagsToProducts [...]
    POST TagControllers/AddTagsToCategory {categoryId, tagIds}, AddTagsToCategories [...]
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.storefront import catalog
from apps.website.models import CategoryTag, ProductTag, Tag

from .. import products as index
from ..envelope import fail, ok
from ..paging import paginated, to_int
from .auth import AdminView


class AllView(AdminView):
    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        tags = list(Tag.objects.filter(is_deleted=False).order_by("-id"))
        search = catalog.norm(d.get("search") or "")
        if search:
            tags = [t for t in tags if search in catalog.norm(t.title)]
        page = paginated(tags, to_int(d.get("pageNumber"), 1), to_int(d.get("pageSize"), 1000))
        page["items"] = [{"id": t.id, "parentId": t.parent_id, "title": t.title} for t in page["items"]]
        return ok({"result": page})


class AddView(AdminView):
    def post(self, request):
        title = (request.data.get("title") or "").strip()
        if not title:
            return fail("عنوان تگ الزامی است", 400)
        parent = to_int(request.data.get("parentId"))
        same = [t for t in Tag.objects.filter(is_deleted=False) if catalog.norm(t.title) == catalog.norm(title)]
        if any(parent is None or t.parent_id == parent for t in same):
            return fail("عنوان تگ تکراری است", 400)
        tag = Tag.objects.create(title=title, parent_id=parent, created=timezone.now())
        return ok({"result": {"id": tag.id}})


def _set_tags(model, owner_field: str, owner_id: int, tag_ids: list[int]) -> None:
    """Make tag_ids the owner's tags: others removed, soft-deleted ones revived, missing ones added."""
    if 0 in tag_ids:
        raise ValueError("شناسه تگ انتخابی غیر مجاز می\u200cباشد")
    links = model.objects.filter(**{owner_field: owner_id})
    links.exclude(tag_id__in=tag_ids).delete()
    links.filter(is_deleted=True).update(is_deleted=False)
    have = set(links.values_list("tag_id", flat=True))
    model.objects.bulk_create(
        model(**{owner_field: owner_id, "tag_id": t, "created": timezone.now()}) for t in set(tag_ids) - have
    )


def _apply(request, model, owner_field: str, owner_key: str, bulk_key: str | None):
    data = request.data
    items = (data if isinstance(data, list) else data.get(bulk_key) or []) if bulk_key else [data]
    owners = [x.get(owner_key) for x in items]
    if bulk_key and len(set(owners)) != len(owners):
        return fail("در لیست تکراری وجود دارد", 400)
    try:
        with transaction.atomic():
            for x in items:
                _set_tags(model, owner_field, int(x[owner_key]), [int(t) for t in x.get("tagIds") or []])
    except (ValueError, KeyError, TypeError) as exc:
        return fail(str(exc), 400)
    index.clear()
    return ok({"result": bool(items)})


class ToProductView(AdminView):
    def post(self, request):
        return _apply(request, ProductTag, "product_id", "productId", None)


class ToProductsView(AdminView):
    def post(self, request):
        return _apply(request, ProductTag, "product_id", "productId", "products")


class ToCategoryView(AdminView):
    def post(self, request):
        return _apply(request, CategoryTag, "category_id", "categoryId", None)


class ToCategoriesView(AdminView):
    def post(self, request):
        return _apply(request, CategoryTag, "category_id", "categoryId", "categories")
