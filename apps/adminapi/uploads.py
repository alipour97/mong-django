"""
Files uploaded in the admin gallery.

The original is kept under MEDIA_ROOT/uploads/<year>/<month>/<id>.<ext>.
Photos (jpg, png, webp, bmp, tiff) also get the site's WebP versions at
/img/u/<id> right away (images.build), like the old panel converted uploads
to WebP; gif, svg, ico and videos are served as uploaded from /media/.
The URL stored on FileMedia is public (PUBLIC_MEDIA_BASE_URL), so moving to a
CDN works as for every other image.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from apps.website import images
from apps.website.models import FileFormat

CONVERT = {"jpg", "jpeg", "png", "webp", "bmp", "tiff", "tif"}


class UploadError(ValueError):
    pass


def save(uploaded) -> dict:
    """Store an UploadedFile. -> {url, format_id, width, height, size, local_path}"""
    ext = Path(uploaded.name or "").suffix.lower().lstrip(".")
    fmt = FileFormat.objects.filter(extension=ext, is_deleted=False).first()
    if fmt is None:
        raise UploadError("فرمت فایل مورد نظر معتبر نیست")
    data = uploaded.read()
    file_id = uuid.uuid4().hex
    now = timezone.localtime()
    relative = Path("uploads") / f"{now:%Y}" / f"{now:%m}" / f"{file_id}.{ext}"
    target = Path(settings.MEDIA_ROOT) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)

    width = height = None
    url = f"{settings.PUBLIC_MEDIA_BASE_URL.rstrip('/')}{settings.MEDIA_URL}{relative.as_posix()}"
    if ext in CONVERT:
        from PIL import Image

        try:
            import io

            with Image.open(io.BytesIO(data)) as im:
                width, height = im.size
        except Exception as exc:
            target.unlink(missing_ok=True)
            raise UploadError("فایل تصویر معتبر نیست") from exc
        key = f"u/{file_id}"
        images.build(key, data)
        url = images.public_url(key)
        fmt = FileFormat.objects.filter(extension="webp").first() or fmt
    return {"url": url, "format_id": fmt.id, "width": width, "height": height, "size": len(data),
            "local_path": str(relative)}

