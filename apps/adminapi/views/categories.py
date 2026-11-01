"""
Category/* — the admin's category pages, as the old CategoryController.

Categories are Samian departments (sync_site_catalog); here the admin edits
what only the site has: descriptions (and, from the gallery step, images and
size guides). Switching a category on or off on the site is in the Django
admin for now, since the old panel never had that (the ERP did it).

    POST Category/GetParents   {search, isActive, pageNumber, pageSize}       -> roots
    POST Category/GetChildren  {... hasLongDescription, hasShortDescription}  -> every non-root
    GET  Category/GetCatgoryById?id=
    GET  Category/{id}/descriptions,  POST Category/{id}/descriptions {longDescriptionHtml, shortDescriptionHtml}
"""
from __future__ import annotations

from collections import defaultdict

from apps.storefront import catalog
from apps.website import images as site_images
from apps.website.models import Category, CategoryTag, FileMedia, MediaAttachment, Product

from ..envelope import fail, ok
from ..paging import paginated, to_bool, to_int
from .auth import AdminView

NOT_FOUND = "شناسه دسته‌بندی نامعتبر است"


def _on_site(c: Category, by_id: dict[int, Category]) -> bool:
    """The category and every parent are live and switched on."""
    seen = set()
    while c is not None and c.id not in seen:
        if c.is_deleted or not c.is_online_active:
            return False
        seen.add(c.id)
        c = by_id.get(c.parent_id)
    return True


class _Tree:
    def __init__(self):
        self.by_id = {c.id: c for c in Category.objects.all()}
        self.children: dict[int | None, list[int]] = defaultdict(list)
        for c in self.by_id.values():
            if not c.is_deleted:
                self.children[c.parent_id].append(c.id)

    def depth(self, c: Category) -> int:
        parent = self.by_id.get(c.parent_id)
        return 1 if parent is None else (2 if parent.parent_id is None else 3)

    def descendants(self, cid: int) -> list[int]:
        out, stack = [], list(self.children.get(cid, []))
        while stack:
            x = stack.pop()
            out.append(x)
            stack.extend(self.children.get(x, []))
        return out


def _rows(tree: _Tree, cats: list[Category], with_descriptions: bool) -> list[dict]:
    ids = [c.id for c in cats]
    counts: dict[int, int] = defaultdict(int)
    for cid in catalog.in_erp(Product.objects.filter(is_deleted=False)).values_list("category_id", flat=True):
        counts[cid] += 1
    media: dict[int, list[dict]] = defaultdict(list)
    atts = list(MediaAttachment.objects.filter(
        table=MediaAttachment.Table.CATEGORIES, record_id__in=ids, is_deleted=False, is_product_guid=False,
    ).order_by("id"))
    files = FileMedia.objects.in_bulk([int(a.map_id) for a in atts if a.map_id.isdigit()])
    for a in atts:
        f = files.get(int(a.map_id)) if a.map_id.isdigit() else None
        media[a.record_id].append({
            "fileMediaId": f.id if f else 0, "mediaId": a.id, "isVideo": a.is_video,
            "mediaUrl": catalog.absolute_url(site_images.site_media_url(a.media_url)),
            "alternative": a.alternative or (f.alternative if f else ""),
            "tooltipTitle": a.tooltip_title or (f.tooltip_title if f else ""),
        })
    tags: dict[int, list[dict]] = defaultdict(list)
    for link in CategoryTag.objects.filter(category_id__in=ids, is_deleted=False, tag__is_deleted=False).select_related("tag"):
        tags[link.category_id].append({"id": link.tag.id, "parentId": link.tag.parent_id, "title": link.tag.title})

    out = []
    for c in cats:
        below = tree.descendants(c.id)
        parent = tree.by_id.get(c.parent_id)
        row = {
            "id": c.id, "parentId": c.parent_id, "title": c.title, "parentTitle": parent.title if parent else None,
            "productCounts": counts[c.id] + sum(counts[x] for x in below),
            "totalChildrenCount": len(below),
            "totalLeafChildrenCount": sum(1 for x in below if not tree.children.get(x)),
            "isOnlineActive": c.is_online_active, "inMainPage": c.in_main_page, "depthLevel": tree.depth(c),
            "fileMedias": media[c.id], "tags": tags[c.id],
        }
        if with_descriptions:
            row["hasLongDescription"] = bool(c.long_description_html)
            row["hasShortDescription"] = bool(c.short_description_html)
        out.append(row)
    return out


def _filtered(request, roots: bool) -> dict:
    data = request.data if isinstance(request.data, dict) else {}
    tree = _Tree()
    only_on_site = to_bool(data.get("isActive")) is not False
    cats = [
        c for c in tree.by_id.values()
        if (c.parent_id is None) == roots and (not only_on_site or _on_site(c, tree.by_id))
    ]
    search = catalog.norm(data.get("search") or "")
    if search:
        cats = [c for c in cats if search in catalog.norm(c.title)]
    if not roots:
        for flag, field in (("hasLongDescription", "long_description_html"), ("hasShortDescription", "short_description_html")):
            want = to_bool(data.get(flag))
            if want is not None:
                cats = [c for c in cats if bool(getattr(c, field)) == want]
    cats.sort(key=lambda c: c.id)
    page_number, page_size = to_int(data.get("pageNumber"), 1), to_int(data.get("pageSize"), 1000)
    page = paginated(cats, page_number, page_size)
    page["items"] = _rows(tree, page["items"], with_descriptions=not roots)
    return {"result": page}


class ParentsView(AdminView):
    def post(self, request):
        return ok(_filtered(request, roots=True))


class ChildrenView(AdminView):
    def post(self, request):
        return ok(_filtered(request, roots=False))


class ByIdView(AdminView):
    def get(self, request):
        c = Category.objects.filter(id=to_int(request.query_params.get("id")), is_deleted=False).first()
        if not c:
            return fail(NOT_FOUND, 404)
        return ok({"result": _rows(_Tree(), [c], with_descriptions=True)[0]})


class DescriptionsView(AdminView):
    def get(self, request, category_id: int):
        c = Category.objects.filter(id=category_id).first()
        if not c:
            return fail(NOT_FOUND, 404)
        return ok({"result": {"longDescriptionHtml": c.long_description_html or None,
                              "shortDescriptionHtml": c.short_description_html or None}})

    def post(self, request, category_id: int):
        c = Category.objects.filter(id=category_id).first()
        if not c:
            return fail(NOT_FOUND, 404)
        c.long_description_html = request.data.get("longDescriptionHtml") or ""
        c.short_description_html = request.data.get("shortDescriptionHtml") or ""
        c.save(update_fields=["long_description_html", "short_description_html"])
        catalog.clear_caches()
        return ok({"result": True})


class AllView(AdminView):
    """
    GET Category/All?search=&isOnlineActive=&hasLongDescription=&hasShortDescription=
    -> roots, each with its sub-categories nested in "categories" (GetAllCategoryDto).
    """

    def get(self, request):
        q = request.query_params
        tree = _Tree()
        only_on_site = "isOnlineActive" in q
        long_wanted, short_wanted = to_bool(q.get("hasLongDescription")), to_bool(q.get("hasShortDescription"))
        guides = {
            a.record_id: {"guidId": a.id, "guidMediaUrl": catalog.absolute_url(site_images.site_media_url(a.media_url))}
            for a in MediaAttachment.objects.filter(table=MediaAttachment.Table.CATEGORIES, is_product_guid=True, is_deleted=False)
        }
        tags: dict[int, list[dict]] = defaultdict(list)
        for link in CategoryTag.objects.filter(is_deleted=False, tag__is_deleted=False).select_related("tag"):
            tags[link.category_id].append({"id": link.tag.id, "parentId": link.tag.parent_id, "title": link.tag.title})

        def keep(c: Category) -> bool:
            if only_on_site and not _on_site(c, tree.by_id):
                return False
            if long_wanted is not None and bool(c.long_description_html) != long_wanted:
                return False
            return short_wanted is None or bool(c.short_description_html) == short_wanted

        def dto(c: Category) -> dict:
            children = sorted((tree.by_id[i] for i in tree.children.get(c.id, [])), key=lambda x: (x.display_priority, x.id))
            return {
                "id": c.id, "title": c.title, "inMainPage": c.in_main_page, "parentId": c.parent_id,
                "displayPriority": c.display_priority, "isOnlineActive": c.is_online_active,
                "hasLongDescription": bool(c.long_description_html), "hasShortDescription": bool(c.short_description_html),
                "categories": [dto(x) for x in children if keep(x)],
                "productsGuid": guides.get(c.id), "tags": tags[c.id],
            }

        roots = [c for c in tree.by_id.values() if c.parent_id is None and not c.is_deleted and (not only_on_site or _on_site(c, tree.by_id))]
        search = catalog.norm(q.get("search") or "")
        if search:
            roots = [c for c in roots if search in catalog.norm(c.title)
                     or any(search in catalog.norm(tree.by_id[i].title) for i in tree.descendants(c.id))]
        return ok({"result": [dto(c) for c in sorted(roots, key=lambda c: c.id)]})
