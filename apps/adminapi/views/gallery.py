"""
FileMedia/* — the admin's media gallery, as the old FileMediaController.

A file lives once in the gallery (FileMedia); using it somewhere (a category
image, a size guide, a collection banner ...) adds a MediaAttachment that
points back to it by map_id. Product photos are not attached here any more:
they come from Samian.

    POST FileMedia/UploadFile (multipart "file")          -> {result: {id, url}}
    POST FileMedia/GetFilteredMedia {fileTags, fileFormatTypes, fileFormatExtensions, used, favorite, search, pageNumber, pageSize}
    GET  FileMedia/GetFileMediaById/{id}                   -> file + entities using it
    GET  FileMedia/GetAllTags?search=,  POST FileMedia/AddTag {title}
    POST FileMedia/AddTagsToFile {fileMediaId, tagIds},  FileMedia/AddTagsToFiles {files: [...]}
    POST FileMedia/AddFilesToEntity {entityKey, entityIds, fileMediaIds}
    POST FileMedia/RemoveFiles {fileMediaIds, verified}
    POST FileMedia/DetachMedia/{id},  FileMedia/DetachMedias {mediaIds}
    POST FileMedia/UpdateAttributesToFile(s), FileMedia/UpdateAttributesToMedia(s) {alternative, tooltipTitle}
    GET  FileMedia/GetAllFormats, GetAllFormatTypes, GetAllFormatExtensions
"""
from __future__ import annotations

from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from apps.storefront import catalog
from apps.website import images as site_images
from apps.website.models import FileFormat, FileMedia, FileMediaTag, FileTag, MediaAttachment

from .. import products as index
from .. import uploads
from ..envelope import fail, ok
from ..paging import paginated, to_bool, to_int
from .auth import AdminView

NO_TAG = "بدون تگ"
NOT_FOUND = "فایل مورد نظر یافت نشد"

# entityKey -> MediaAttachment.table (Dadehfa's TableTitles ids, which the imported rows use)
ENTITY_TABLES = {
    "Products": 14, "Categories": 38, "Collections": 12, "Outfits": 19, "Articles": 32, "Article": 32,
    "CompanyInfos": 46, "Banners": 5, "Themes": 7, "Brands": 34, "CooperationRequests": 100,
}
TABLE_NAMES = {v: k for k, v in ENTITY_TABLES.items() if k != "Article"}
GUIDE_KEYS = {"ProductGuides": "Products", "CategoryGuides": "Categories"}


def _url(file_url: str) -> str:
    return catalog.absolute_url(site_images.site_media_url(file_url))


def _dto(f: FileMedia, formats: dict[int, FileFormat], tags: dict[int, list[dict]]) -> dict:
    fmt = formats.get(f.format_id)
    return {
        "id": f.id, "fileName": f.file_name, "url": _url(f.url), "format": fmt.extension if fmt else "",
        "favorite": f.favorite, "used": f.used, "alternative": f.alternative, "tooltipTitle": f.tooltip_title,
        "tags": tags.get(f.id, []),
    }


def _tags_of(ids) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = defaultdict(list)
    for link in FileMediaTag.objects.filter(file_media_id__in=list(ids), is_deleted=False).select_related("tag"):
        out[link.file_media_id].append({"id": link.tag_id, "title": link.tag.title})
    return out


def _entities(file_ids) -> dict[int, dict[str, list[str]]]:
    """file id -> {"Products": ["44284"], ...}: where each file is used."""
    out: dict[int, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    ids = {str(i) for i in file_ids}
    for a in MediaAttachment.objects.filter(map_id__in=ids, is_deleted=False):
        out[int(a.map_id)][TABLE_NAMES.get(a.table, str(a.table))].append(str(a.record_id))
    return out


def _refresh_used(file_ids) -> None:
    in_use = set(MediaAttachment.objects.filter(map_id__in=[str(i) for i in file_ids], is_deleted=False)
                 .values_list("map_id", flat=True))
    for f in FileMedia.objects.filter(id__in=file_ids):
        used = str(f.id) in in_use
        if f.used != used:
            f.used = used
            f.save(update_fields=["used"])


def _changed() -> None:
    """Attachments show on the site (category images, size guides ...): drop cached pages."""
    index.clear()


class UploadView(AdminView):
    def post(self, request):
        uploaded = request.FILES.get("file") or request.FILES.get("File")
        if not uploaded:
            return fail("فایلی ارسال نشده است", 400)
        try:
            f = uploads.save_media(uploaded, request.get_host())
        except uploads.UploadError as exc:
            return fail(str(exc), 400)
        return ok({"result": {"id": f.id, "url": _url(f.url)}})


class FilteredView(AdminView):
    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        qs = FileMedia.objects.filter(is_deleted=False)
        for key in ("used", "favorite"):
            want = to_bool(d.get(key))
            if want is not None:
                qs = qs.filter(**{key: want})
        tag_ids = [int(t) for t in d.get("fileTags") or []]
        if tag_ids:
            tagged = FileMediaTag.objects.filter(is_deleted=False)
            with_tags = set(tagged.filter(tag_id__in=tag_ids).values_list("file_media_id", flat=True))
            if 0 in tag_ids:
                any_tag = set(tagged.values_list("file_media_id", flat=True))
                qs = qs.filter(id__in=with_tags) | qs.exclude(id__in=any_tag)
            else:
                qs = qs.filter(id__in=with_tags)
        formats = FileFormat.objects.all()
        exts = {e.strip().lower() for e in d.get("fileFormatExtensions") or []}
        if exts:
            qs = qs.filter(format_id__in=[f.id for f in formats if f.extension in exts])
        types = {t.strip().lower() for t in d.get("fileFormatTypes") or []}
        if types:
            qs = qs.filter(format_id__in=[f.id for f in formats if f.type.lower() in types])
        search = (d.get("search") or "").strip()
        if search:
            qs = qs.filter(file_name__icontains=search)
        files = list(qs.order_by("-id"))
        page = paginated(files, to_int(d.get("pageNumber"), 1), to_int(d.get("pageSize"), 20))
        fmt = {f.id: f for f in formats}
        tags = _tags_of(f.id for f in page["items"])
        page["items"] = [_dto(f, fmt, tags) for f in page["items"]]
        return ok({"result": page})


class ByIdView(AdminView):
    def get(self, request, file_id: int):
        f = FileMedia.objects.filter(id=file_id, is_deleted=False).first()
        if not f:
            return fail(NOT_FOUND, 404)
        result = _dto(f, {x.id: x for x in FileFormat.objects.filter(id=f.format_id)}, _tags_of([f.id]))
        used_in = _entities([f.id]).get(f.id)
        if used_in:
            result["entities"] = {k: v for k, v in used_in.items()}
        return ok({"result": result})


class TagsView(AdminView):
    def get(self, request):
        qs = FileTag.objects.filter(is_deleted=False)
        search = (request.query_params.get("search") or "").strip().lower()
        if search:
            qs = qs.filter(title__icontains=search)
        return ok({"result": [{"id": t.id, "title": t.title} for t in qs.order_by("id")]})


class AddTagView(AdminView):
    def post(self, request):
        title = (request.data.get("title") or "").strip().lower()
        if not title:
            return ok({"result": False})
        if title == NO_TAG:
            return fail("انتخاب این نام غیر مجاز است", 400)
        if FileTag.objects.filter(title=title, is_deleted=False).exists():
            return ok({"result": False})
        FileTag.objects.create(title=title, created=timezone.now())
        return ok({"result": True})


def _set_file_tags(file_id: int, tag_ids: list[int]) -> None:
    if 0 in tag_ids:
        raise ValueError("شناسه تگ انتخابی غیر مجاز می‌باشد")
    FileMediaTag.objects.filter(file_media_id=file_id).exclude(tag_id__in=tag_ids).delete()
    have = set(FileMediaTag.objects.filter(file_media_id=file_id).values_list("tag_id", flat=True))
    FileMediaTag.objects.bulk_create(
        FileMediaTag(file_media_id=file_id, tag_id=t, created=timezone.now()) for t in set(tag_ids) - have
    )


class TagsToFileView(AdminView):
    def post(self, request):
        try:
            with transaction.atomic():
                _set_file_tags(int(request.data.get("fileMediaId")), [int(t) for t in request.data.get("tagIds") or []])
        except (TypeError, ValueError) as exc:
            return fail(str(exc), 400)
        return ok({"result": True})


class TagsToFilesView(AdminView):
    def post(self, request):
        files = request.data.get("files") or []
        if len({f.get("fileMediaId") for f in files}) != len(files):
            return fail("در لیست فایل تکراری وجود دارد", 400)
        try:
            with transaction.atomic():
                for f in files:
                    _set_file_tags(int(f["fileMediaId"]), [int(t) for t in f.get("tagIds") or []])
        except (TypeError, ValueError, KeyError) as exc:
            return fail(str(exc), 400)
        return ok({"result": bool(files)})


class AddToEntityView(AdminView):
    """Attach gallery files to a record. ProductGuides/CategoryGuides attach a size guide."""

    def post(self, request):
        key = request.data.get("entityKey") or ""
        entity_ids = [int(i) for i in request.data.get("entityIds") or []]
        file_ids = [int(i) for i in request.data.get("fileMediaIds") or []]
        if not file_ids:
            return ok({"result": False})
        if key == "ProductVariants":
            return fail("عکس محصولات و رنگ‌ها از سامیان خوانده می‌شود و اینجا قابل افزودن نیست.", 400)
        is_guide = key in GUIDE_KEYS
        table = ENTITY_TABLES.get(GUIDE_KEYS.get(key, key))
        if table is None:
            return fail("کلید ارسالی اشتباه است", 404)
        if len(entity_ids) != 1:
            return fail("تعداد شناسه های ارسالی با کلید انتخابی همخوانی ندارد.", 400)
        files = list(FileMedia.objects.filter(id__in=file_ids, is_deleted=False))
        if not files:
            return ok({"result": False})
        formats = {f.id: f for f in FileFormat.objects.all()}
        with transaction.atomic():
            if is_guide:  # one size guide per record: the new one replaces it
                MediaAttachment.objects.filter(table=table, record_id=entity_ids[0], is_product_guid=True).update(is_deleted=True)
            MediaAttachment.objects.bulk_create(
                MediaAttachment(
                    table=table, record_id=entity_ids[0], media_url=f.url, map_id=str(f.id),
                    is_video=bool(formats.get(f.format_id) and formats[f.format_id].type == "Video"),
                    alternative=f.alternative, tooltip_title=f.tooltip_title, is_product_guid=is_guide,
                    created=timezone.now(),
                ) for f in (files[-1:] if is_guide else files)
            )
            FileMedia.objects.filter(id__in=[f.id for f in files]).update(used=True)
        _changed()
        return ok({"result": True})


class RemoveFilesView(AdminView):
    """Unverified: report which files are in use. Verified: detach them everywhere and delete."""

    def post(self, request):
        ids = [int(i) for i in request.data.get("fileMediaIds") or []]
        if not ids:
            return fail("لیست شناسه فایلها ضروریست و نمی‌تواند خالی باشد", 400)
        if len(set(ids)) != len(ids):
            return fail("فایل تکراری انتخاب شده است", 400)
        files = list(FileMedia.objects.filter(id__in=ids, is_deleted=False))
        missing = set(ids) - {f.id for f in files}
        if missing:
            return fail(f"برخی از تصاویر وجود ندارند [{' ,'.join(map(str, sorted(missing)))}]", 404)
        used_in = _entities(ids)
        results = []
        if to_bool(request.data.get("verified")):
            with transaction.atomic():
                MediaAttachment.objects.filter(map_id__in=[str(i) for i in ids], is_deleted=False).update(is_deleted=True)
                FileMedia.objects.filter(id__in=ids).update(is_deleted=True, used=False)
            _changed()
            results = [{"fileMediaId": i, "isDeleted": True, "resultStatus": "حذف شد", "entities": None} for i in ids]
        else:
            for f in files:
                where = used_in.get(f.id)
                results.append({"fileMediaId": f.id, "isDeleted": not where,
                                "resultStatus": "در حال استفاده" if where else "قابل حذف است",
                                "entities": dict(where) if where else None})
        problems = sum(1 for r in results if not r["isDeleted"])
        return ok({"result": {"removeFilesResults": results, "hasProblems": problems > 0, "problemsCount": problems}})


def _detach(media_ids: list[int]) -> tuple[list[int], str]:
    atts = list(MediaAttachment.objects.filter(id__in=media_ids, is_deleted=False))
    missing = sorted(set(media_ids) - {a.id for a in atts})
    if missing:
        return missing, "برخی از تصاویر درخواستی وجود ندارند، پس از اصلاح دوباره تلاش فرمایید"
    file_ids = [int(a.map_id) for a in atts if a.map_id.isdigit()]
    files = FileMedia.objects.in_bulk(file_ids)
    # Only files that came from the gallery can be removed; imported ones without a gallery file stay.
    failed = [a.id for a in atts if not (a.map_id.isdigit() and int(a.map_id) in files)]
    if failed:
        return failed, "برخی از تصاویر مورد نظر از سیستم مرکزی بارگذاری شده است و امکان حذف آن از پنل ادمین نیست"
    MediaAttachment.objects.filter(id__in=media_ids).update(is_deleted=True)
    _refresh_used(file_ids)
    _changed()
    return [], "تمام تصاویر با موفقیت حذف شد"


class DetachView(AdminView):
    def post(self, request, media_id: int):
        failed, message = _detach([media_id])
        if failed:
            return fail(message, 404)
        return ok({"result": True})


class DetachManyView(AdminView):
    def post(self, request):
        ids = list(dict.fromkeys(int(i) for i in request.data.get("mediaIds") or []))
        if not ids:
            return fail("لیست درخواستی نمی‌تواند خالی باشد", 400)
        failed, message = _detach(ids)
        return ok({"result": {"faildMediaIds": failed, "resultStatus": message}})


def _attrs(items: list[dict], id_key: str, model) -> int:
    ids = [int(x[id_key]) for x in items]
    if len(set(ids)) != len(ids):
        raise ValueError("در لیست تکراری وجود دارد")
    rows = model.objects.in_bulk(ids)
    if len(rows) != len(ids):
        raise LookupError("برخی از شناسه‌های ارسالی وجود ندارند")
    for x in items:
        row = rows[int(x[id_key])]
        row.alternative, row.tooltip_title = x.get("alternative") or "", x.get("tooltipTitle") or ""
    model.objects.bulk_update(rows.values(), ["alternative", "tooltip_title"])
    return len(rows)


class AttributesView(AdminView):
    """UpdateAttributesToFile(s) and UpdateAttributesToMedia(s): alt text and tooltip."""

    many: bool = False
    media: bool = False

    def post(self, request):
        d = request.data
        items = (d.get("medias") or d.get("files") or []) if self.many else [d]
        if not items:
            return fail("وجود حداقل یک شناسه الزامی است", 400)
        try:
            _attrs(items, "mediaId" if self.media else "fileMediaId", MediaAttachment if self.media else FileMedia)
        except (ValueError, KeyError, TypeError) as exc:
            return fail(str(exc), 400)
        except LookupError as exc:
            return fail(str(exc), 404)
        if self.media:
            _changed()
        return ok({"result": True})


class FormatsView(AdminView):
    """GetAllFormats -> {type: [extensions]}; GetAllFormatTypes / GetAllFormatExtensions -> lists."""

    what: str = "all"

    def get(self, request):
        search = (request.query_params.get("search") or "").strip().lower()
        formats = [f for f in FileFormat.objects.filter(is_deleted=False).order_by("id")
                   if not search or search in f.type.lower() or search in f.extension]
        if self.what == "types":
            return ok({"result": list(dict.fromkeys(f.type for f in formats))})
        if self.what == "extensions":
            return ok({"result": list(dict.fromkeys(f.extension for f in formats))})
        grouped: dict[str, list[str]] = defaultdict(list)
        for f in formats:
            grouped[f.type].append(f.extension)
        return ok({"result": grouped})
