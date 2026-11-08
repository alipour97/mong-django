"""
The customize page: PrimaryConfig/*, Setting/*, Cdn/upload, RedirectManager/*.

PrimaryConfig values are JSON the panel builds (footer, about us, FAQ, home
page rows, ...). "businessDepartments" is special: its departmentList is the
Branch table, so saving it updates the branches (title, address, location,
phones, order) and reading it lists them. A branch removed in the panel is
hidden from the branches page, not deleted, since it may also be a selling
warehouse; which branches sell online stays a Django-admin setting.

    GET  PrimaryConfig/Get?key=          POST PrimaryConfig {key, value}
    POST PrimaryConfig/Update/<id> {key, value}                GET PrimaryConfig/SoftDelete/<id>
    GET  Setting/GetSetting   POST Setting/ChangeMinQty?qty=   POST Setting/ToggleHasMediaProducts?toggle=
    POST Setting/UpdateShowCategoryTopProduct?show=            POST Setting/SetDefaultTheme {isCustomTheme, defaultId}
    GET  Setting/GetCompanyInfo          POST Setting/UpdateCompanyInfo {name, description, address, phoneNumbers, postalCode, keywords}
    GET  Setting/GetPaymentConnections   POST Setting/UpdatePaymentConnections {hasConnectionWithTorob, ...}
    POST Cdn/upload?isVideo= (multipart "file") -> {id, url}
    POST RedirectManager/GetAll {search, isActive, pageNumber, pageSize}    GET RedirectManager/GetRedirect/<id>
    POST RedirectManager/AddOrUpdateRedirect {...}   POST RedirectManager/AddOrUpdateRedirects [...]   (+ BulkAddOrUpdateRedirects)
    POST RedirectManager/DeleteRedirect/<id>
    GET  RedirectManager/Redirect?sourceUrl=&origin=   (public: 301/302 to the destination, else back to the site)
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

from django.conf import settings
from django.db import transaction
from django.http import HttpResponsePermanentRedirect, HttpResponseRedirect
from django.utils import timezone
from rest_framework.response import Response

from apps.storefront import catalog
from apps.storefront.views import PublicView, _company_media, _config_value
from apps.website import images as site_images
from apps.website.models import Branch, CompanyInfo, MediaAttachment, PrimaryConfig, Redirect, SiteSetting

from .. import products as index
from .. import uploads
from ..envelope import fail, ok
from ..paging import paginated, to_bool, to_int
from .auth import AdminView
from .gallery import _url

CONFIG_NOT_FOUND = "کانفیگ مورد نظر یافت نشد."
NO_SETTING = "تنظیمات اولیه سایت وجود ندارد لطفا با پشتیبانی تماس بگیرید."
NO_COMPANY = "اطلاعات شرکت ثبت نشده است"
BUSINESS_DEPARTMENTS = "businessDepartments"


# -----------------------------------------------------------------------------
# PrimaryConfig
# -----------------------------------------------------------------------------
def _save_branches(value: str) -> None:
    """Make the Branch table match businessDepartments.departmentList."""
    try:
        deps = json.loads(value or "{}").get("departmentList")
    except (ValueError, AttributeError):
        return
    if not isinstance(deps, list):
        return
    branches = list(Branch.objects.all())
    by_front = {b.front_id: b for b in branches if b.front_id}
    by_id = {b.id: b for b in branches}
    kept = set()
    for order, dep in enumerate(d for d in deps if isinstance(d, dict)):
        dep_id = to_int(dep.get("id"))
        b = by_front.get(dep_id) or by_id.get(dep_id) or Branch(front_id=dep_id if dep_id and dep_id not in by_id else None)
        loc = dep.get("location") or {}
        b.title = (dep.get("depTitle") or "").strip() or b.title or "شعبه"
        b.address = dep.get("address") or ""
        b.latitude, b.longitude = loc.get("lat"), loc.get("lng")
        b.phones = "\n".join(
            str(p.get("phoneNumber")).strip() for p in dep.get("phoneNumbers") or []
            if isinstance(p, dict) and str(p.get("phoneNumber") or "").strip()
        )
        b.display_order, b.show_on_site = order, True
        b.save()
        kept.add(b.id)
    Branch.objects.exclude(id__in=kept).update(show_on_site=False)


def _stored_value(value) -> str:
    """The panel sends back the public URLs it was shown; ours are kept as paths (the API adds the host)."""
    return site_images.strip_domains_in_text(str(value or ""))


def _config_dto(pc: PrimaryConfig) -> dict:
    return {"id": pc.id, "key": pc.key, "value": _config_value(pc)}


class ConfigGetView(AdminView):
    def get(self, request):
        qs = PrimaryConfig.objects.filter(is_deleted=False).order_by("id")
        key = (request.query_params.get("key") or "").strip()
        if key:
            qs = qs.filter(key=key)
        return ok({"result": [_config_dto(pc) for pc in qs]})


class ConfigAddView(AdminView):
    def post(self, request):
        key = (request.data.get("key") or "").strip()
        if not key:
            return fail("کلید الزامی است", 400)
        pc = PrimaryConfig.objects.filter(key=key).first()
        if pc and not pc.is_deleted:
            return fail("این کلید وجود دارد", 400)
        pc = pc or PrimaryConfig(key=key, created=timezone.now())
        pc.value, pc.is_deleted, pc.last_modified = _stored_value(request.data.get("value")), False, timezone.now()
        with transaction.atomic():
            pc.save()
            if key == BUSINESS_DEPARTMENTS:
                _save_branches(pc.value)
        return ok({"result": pc.id})


class ConfigUpdateView(AdminView):
    def post(self, request, config_id: int):
        pc = PrimaryConfig.objects.filter(id=config_id, is_deleted=False).first()
        if not pc:
            return fail(CONFIG_NOT_FOUND, 404)
        key = (request.data.get("key") or pc.key).strip()
        if key != pc.key and PrimaryConfig.objects.filter(key=key).exclude(id=pc.id).exists():
            return fail("این کلید وجود دارد", 400)
        pc.key, pc.value, pc.last_modified = key, _stored_value(request.data.get("value")), timezone.now()
        with transaction.atomic():
            pc.save()
            if key == BUSINESS_DEPARTMENTS:
                _save_branches(pc.value)
        if key in ("sortRowsConfig", "webSortOrder"):
            catalog.clear_caches()
        return ok({"result": True})


class ConfigDeleteView(AdminView):
    def get(self, request, config_id: int):
        n = PrimaryConfig.objects.filter(id=config_id, is_deleted=False).update(is_deleted=True, last_modified=timezone.now())
        return ok({"result": True}) if n else fail(CONFIG_NOT_FOUND, 404)


# -----------------------------------------------------------------------------
# Setting
# -----------------------------------------------------------------------------
def _setting() -> SiteSetting | None:
    return SiteSetting.objects.filter(is_deleted=False).first()


def _setting_or_new() -> SiteSetting:
    return _setting() or SiteSetting(created=timezone.now())


class SettingView(AdminView):
    def get(self, request):
        s = _setting()
        result = None if s is None else {
            "showAllCategory": s.show_all_category, "webSiteTitle": s.website_title,
            "minQty": float(s.min_qty), "onlyHasMediaProducts": s.only_has_media_products,
        }
        return Response({"result": result})


class MinQtyView(AdminView):
    def post(self, request):
        try:
            qty = Decimal(str(request.query_params.get("qty")))
        except InvalidOperation:
            return fail("حداقل موجودی نامعتبر است", 400)
        if qty < 0:
            return fail("حداقل موجودی نمی‌تواند منفی باشد", 400)
        s = _setting_or_new()
        s.min_qty, s.last_modified = qty, timezone.now()
        s.save()
        index.clear()
        return ok({"result": True})


class HasMediaView(AdminView):
    def post(self, request):
        s = _setting_or_new()
        s.only_has_media_products, s.last_modified = bool(to_bool(request.query_params.get("toggle"))), timezone.now()
        s.save()
        index.clear()
        return ok({"result": True})


class ShowCategoryTopProductView(AdminView):
    def post(self, request):
        s = _setting()
        if s:
            s.show_all_category, s.last_modified = bool(to_bool(request.query_params.get("show"))), timezone.now()
            s.save(update_fields=["show_all_category", "last_modified"])
        return Response({"isUpdated": bool(s)})


class DefaultThemeView(AdminView):
    def post(self, request):
        s = _setting()
        if not s:
            return fail(NO_SETTING, 500)
        s.is_custom_theme = bool(to_bool(request.data.get("isCustomTheme")))
        s.default_theme_id = to_int(request.data.get("defaultId"))
        s.last_modified = timezone.now()
        s.save(update_fields=["is_custom_theme", "default_theme_id", "last_modified"])
        return ok({"result": True})


CONNECTIONS = {
    "hasConnectionWithTorob": "has_connection_with_torob",
    "hasConnectionWithSnappPay": "has_connection_with_snapp_pay",
    "hasConnectionWithSnappExpress": "has_connection_with_snapp_express",
}


class PaymentConnectionsView(AdminView):
    def get(self, request):
        s = _setting()
        return ok({"result": None if s is None else {k: getattr(s, f) for k, f in CONNECTIONS.items()}})


class UpdatePaymentConnectionsView(AdminView):
    def post(self, request):
        s = _setting()
        if s:
            for k, f in CONNECTIONS.items():
                setattr(s, f, bool(to_bool(request.data.get(k))))
            s.last_modified = timezone.now()
            s.save()
        return Response({"isUpdated": bool(s)})


def _split(text: str) -> list[str]:
    return [x for x in (text or "").split(",") if x.strip()]


def _join(values) -> str:
    return ",".join(str(v).strip() for v in values or [] if str(v).strip())


class CompanyInfoView(AdminView):
    def get(self, request):
        info = CompanyInfo.objects.filter(is_deleted=False).first()
        if not info:
            return fail(NO_COMPANY, 404)

        def media(record_id: int) -> dict | None:
            m = _company_media(record_id)
            return m and {
                "fileMediaId": m["fileMediaId"] or 0, "mediaId": m["mediaId"], "url": catalog.absolute_url(m["url"]),
                "alternative": m["alternative"], "tooltipTitle": m["tooltipTitle"],
            }

        return ok({"result": {
            "name": info.name, "description": info.description, "address": info.address,
            "phoneNumbers": _split(info.phone_numbers), "postalCode": info.postal_code, "keywords": _split(info.keywords),
            "webSiteLogo": media(1), "favicon": media(2),
        }})


class UpdateCompanyInfoView(AdminView):
    def post(self, request):
        info = CompanyInfo.objects.filter(is_deleted=False).first()
        if not info:
            return fail(NO_COMPANY, 404)
        d = request.data
        for field, key in (("name", "name"), ("description", "description"), ("address", "address"), ("postal_code", "postalCode")):
            if d.get(key) is not None:
                setattr(info, field, d[key])
        if d.get("phoneNumbers") is not None:
            info.phone_numbers = _join(d["phoneNumbers"])
        if d.get("keywords") is not None:
            info.keywords = _join(d["keywords"])
        info.last_modified = timezone.now()
        info.save()
        return ok({"result": True})


# -----------------------------------------------------------------------------
# Cdn/upload: a file for a config (images in about us, shipping icons, ...)
# -----------------------------------------------------------------------------
class UploadView(AdminView):
    writer_ok = True  # the blog editor's images and an author's photo

    def post(self, request):
        f = request.FILES.get("file")
        if not f or not f.size:
            return fail("فایل نمیتواند خالی باشد.", 400)
        try:
            saved = uploads.save(f)
        except uploads.UploadError as exc:
            return fail(str(exc), 400)
        att = MediaAttachment.objects.create(
            table=MediaAttachment.Table.MEDIA_ATTACHMENTS, record_id=0, media_url=saved["url"],
            is_video=bool(to_bool(request.query_params.get("isVideo"))), created=timezone.now(),
        )
        return ok({"id": att.id, "url": _url(att.media_url)})


# -----------------------------------------------------------------------------
# RedirectManager
# -----------------------------------------------------------------------------
BAD_URL = "آدرس دارای کاراکترهای غیر مجاز می‌باشد"
DUPLICATE = "پارامتر تکراری"


def _source(url: str) -> str:
    url = (url or "").strip()
    if not url.startswith("/"):
        url = "/" + url
    return url.rstrip("/") or "/"


def _bad(url: str) -> bool:
    return any(c.isspace() or not c.isprintable() or c in "<>" for c in url)


def _redirect_dto(r: Redirect) -> dict:
    return {
        "id": r.id, "sourceUrl": r.source_url, "destinationUrl": r.destination_url, "redirectPermanent": r.permanent,
        "title": r.title, "description": r.description, "isActive": r.is_active,
    }


def _apply(r: Redirect, d: dict, source: str) -> None:
    r.source_url, r.destination_url = source, (d.get("destinationUrl") or "").strip()
    perm, active = to_bool(d.get("redirectPermanent")), to_bool(d.get("isActive"))
    r.permanent = True if perm is None else perm
    r.is_active = True if active is None else active
    r.title, r.description = d.get("title") or "", d.get("description") or ""
    r.last_modified = timezone.now()


def _live():
    return Redirect.objects.filter(is_deleted=False)


class RedirectListView(AdminView):
    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        qs = _live()
        active = to_bool(d["isActive"]) if "isActive" in d else True
        if active is not None:
            qs = qs.filter(is_active=active)
        search = catalog.norm(d.get("search") or "")
        rows = [r for r in qs.order_by("id") if not search or search in catalog.norm(f"{r.source_url} {r.destination_url} {r.title}")]
        size, number = to_int(d.get("pageSize"), 1000), to_int(d.get("pageNumber"), 1)
        if size < 1 or number < 1:
            return fail("اندازه و شماره صفحه باید بیشتر از 0 باشد", 400)
        return ok({"result": paginated(rows, number, size, _redirect_dto)})


class RedirectByIdView(AdminView):
    def get(self, request, redirect_id: int):
        r = _live().filter(id=redirect_id).first()
        return ok({"result": _redirect_dto(r)}) if r else fail("انتقالی با این شناسه وجود ندارد", 404)


class RedirectSaveView(AdminView):
    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        source = _source(d.get("sourceUrl"))
        if _bad(source):
            return fail(BAD_URL, 400)
        if not (d.get("destinationUrl") or "").strip():
            return fail("آدرس مقصد الزامی است", 400)
        rid = to_int(d.get("id"))
        if _live().filter(source_url=source).exclude(id=rid).exists():
            return fail(DUPLICATE, 400)
        r = Redirect(created=timezone.now())
        if rid:
            r = _live().filter(id=rid).first()
            if not r:
                return ok({"result": None})
        _apply(r, d, source)
        r.save()
        return ok({"result": r.id})


class RedirectBulkView(AdminView):
    def post(self, request):
        items = request.data if isinstance(request.data, list) else []
        if not items:
            return fail("لیست نمی‌تواند خالی باشد", 400)
        for x in items:
            x["sourceUrl"] = _source(x.get("sourceUrl"))
        ids = [to_int(x.get("id")) for x in items if to_int(x.get("id"))]
        if len(ids) != len(set(ids)):
            return fail("شناسه تکراری در ورودی شما وجود دارد", 400)
        if len({x["sourceUrl"] for x in items}) != len(items):
            return fail("آدرس تکراری در ورودی شما وجود دارد", 400)

        taken = dict(_live().filter(source_url__in=[x["sourceUrl"] for x in items]).values_list("source_url", "id"))
        existing = _live().in_bulk(ids)
        results = []

        def result(x, status, success, rid=None):
            results.append({"id": rid if rid is not None else to_int(x.get("id")), "sourceUrl": x["sourceUrl"], "resultStatus": status, "success": success})

        with transaction.atomic():
            for x in items:
                rid = to_int(x.get("id"))
                if x["sourceUrl"] in taken and taken[x["sourceUrl"]] != rid:
                    result(x, f"[SourceUrl]: {DUPLICATE}", False)
                elif _bad(x["sourceUrl"]):
                    result(x, BAD_URL, False)
                elif rid and rid not in existing:
                    result(x, "با این شناسه یافت نشد", False)
                else:
                    r = existing.get(rid) or Redirect(created=timezone.now())
                    _apply(r, x, x["sourceUrl"])
                    r.save()
                    result(x, "با موفقیت تغییر یافت" if rid else "با موفقیت ثبت شد", True, r.id)
        return ok({"result": {"addOrUpdateRedirectsResults": results}})


class RedirectDeleteView(AdminView):
    def post(self, request, redirect_id: int):
        n, _ = Redirect.objects.filter(id=redirect_id).delete()
        return ok({"result": True}) if n else fail("شناسه مورد نظر یافت نشد", 404)


def _with_query(url: str, params: dict) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.update({k: v for k, v in params.items() if v})
    return urlunsplit(parts._replace(query=urlencode(query)))


class RedirectGoView(PublicView):
    """For the web server's 404 handler: send an old address to its new one."""

    def get(self, request):
        source = request.query_params.get("sourceUrl")
        if not source:
            return fail("sourceUrl is required.", 400)
        source = _source(source)
        r = _live().filter(source_url=source, is_active=True).first()
        if r:
            url = _with_query(r.destination_url, {"utm_title": r.title, "utm_desc": r.description, "utm_redirect": "true"})
            return HttpResponsePermanentRedirect(url) if r.permanent else HttpResponseRedirect(url)
        # No redirect: back to the same address on the site (utm_redirect stops the web server from asking again).
        # Only hosts of this site, so the endpoint cannot be used to send visitors elsewhere.
        origin = (request.query_params.get("origin") or "").strip().lower()
        base = f"https://{origin}" if origin in settings.ALLOWED_HOSTS else settings.PUBLIC_BASE_URL.rstrip("/")
        return HttpResponseRedirect(_with_query(base + source, {"utm_redirect": "true"}))
