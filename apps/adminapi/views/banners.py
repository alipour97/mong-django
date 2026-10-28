"""
Banner/* — the home page banners, as the old Banner controller.

The panel shows public image URLs and sends them back on save; a URL of a
gallery file is stored as that file's own URL, so banners keep following the
gallery (a relative path, made absolute when answering) like the imported ones.

    GET  Banner/GetBannerById?id=
    POST Banner/GetAllBanners {search, isActive, pageNumber, pageSize}   isActive missing = active only
    POST Banner/AddOrUpdateBanner {id, mediaUrl, isActive, link, displayPriority, isBanner}
    POST Banner/DeleteBanner?id=
    POST Banner/ToggleBannerActivation?id=&isActive=
"""
from __future__ import annotations

from django.utils import timezone

from apps.storefront import catalog
from apps.website import images as site_images
from apps.website.models import Banner, FileMedia

from ..envelope import fail, ok
from ..paging import paginated, to_bool, to_int
from .auth import AdminView
from .gallery import _url

NOT_FOUND = "بنر با این شناسه وجود ندارد."


def _dto(b: Banner) -> dict:
    return {
        "id": b.id, "mediaUrl": _url(b.media_url), "isActive": b.is_active, "link": b.link,
        "displayPriority": b.display_priority, "isBanner": b.is_banner,
    }


def _stored_url(url: str, current: Banner | None) -> str:
    """The URL to keep for a public URL the panel sent back."""
    if current and url == _url(current.media_url):
        return current.media_url
    for f in FileMedia.objects.filter(is_deleted=False).only("url"):
        if _url(f.url) == url:
            return f.url
    return site_images.strip_domain(url)  # a URL of ours is kept as a path


def _banner(request) -> Banner | None:
    return Banner.objects.filter(id=to_int(request.query_params.get("id")), is_deleted=False).first()


class ByIdView(AdminView):
    def get(self, request):
        b = _banner(request)
        return ok({"result": _dto(b)}) if b else fail(NOT_FOUND, 404)


class AllView(AdminView):
    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        qs = Banner.objects.filter(is_deleted=False)
        active = to_bool(d["isActive"]) if "isActive" in d else True
        if active is not None:
            qs = qs.filter(is_active=active)
        search = catalog.norm(d.get("search") or "")
        banners = [b for b in qs.order_by("id") if not search or search in catalog.norm(b.link)]
        size, number = to_int(d.get("pageSize"), 1000), to_int(d.get("pageNumber"), 1)
        if size < 1 or number < 1:
            return fail("اندازه و شماره صفحه باید بیشتر از 0 باشد", 400)
        return ok({"result": paginated(banners, number, size, _dto)})


class SaveView(AdminView):
    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        media_url = (d.get("mediaUrl") or "").strip()
        if not media_url:
            return fail("تصویر بنر الزامی است", 400)
        bid = to_int(d.get("id"))
        b = Banner(created=timezone.now())
        if bid:
            b = Banner.objects.filter(id=bid, is_deleted=False).first()
            if not b:
                return fail(NOT_FOUND, 404)
        b.media_url = _stored_url(media_url, b if bid else None)
        b.is_active = bool(to_bool(d.get("isActive")))
        b.link = (d.get("link") or "").strip()
        b.display_priority = to_int(d.get("displayPriority"), 0)
        b.is_banner = bool(to_bool(d.get("isBanner")))
        b.last_modified = timezone.now()
        b.save()
        return ok({"result": b.id})


class DeleteView(AdminView):
    def post(self, request):
        b = _banner(request)
        if not b:
            return fail(NOT_FOUND, 404)
        b.is_deleted, b.last_modified = True, timezone.now()
        b.save(update_fields=["is_deleted", "last_modified"])
        return ok({"result": True})


class ToggleView(AdminView):
    def post(self, request):
        b = _banner(request)
        if not b:
            return fail(NOT_FOUND, 404)
        active = to_bool(request.query_params.get("isActive"))
        b.is_active = (not b.is_active) if active is None else active
        b.last_modified = timezone.now()
        b.save(update_fields=["is_active", "last_modified"])
        return ok({"result": True})
