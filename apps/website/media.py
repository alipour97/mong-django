"""
The media the old CDN served, from this service's own disk, under the same paths:
https://cdn.mong.ir/9/a.webp -> /cdn/9/a.webp. A file that is not here yet (one added
in the old panel after the pack was built) goes to the old CDN, so nothing breaks.
"""
from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.views.decorators.http import require_safe

from apps.website import images

OLD_CDN = "https://cdn.mong.ir/"
YEAR = "public, max-age=31536000, immutable"
# Under ASGI a file response is read whole into memory, so video goes out in slices.
SLICE = 4 * 1024 * 1024
RANGE = re.compile(r"bytes=(\d*)-(\d*)$")

mimetypes.add_type("video/mp4", ".mov")


def _inside(root: Path, path: str) -> Path:
    root = root.resolve()
    target = (root / path).resolve()
    if root not in target.parents:
        raise Http404
    return target


def _built(path: str, width: str | None) -> Path | None:
    if Path(path).suffix.lower() not in images.IMAGE_EXT:
        return None
    folder = _inside(images.img_root(), "c/" + str(Path(path).with_suffix("")))
    name = "full"
    if width and width.isdigit() and int(width) > 0:
        name = next((str(w) for w in images.WIDTHS if int(width) <= w), "full")
    for candidate in (folder / f"{name}.webp", folder / "full.webp"):
        if candidate.is_file():
            return candidate
    return None


def _read(file: Path, start: int, length: int) -> bytes:
    with file.open("rb") as stream:
        stream.seek(start)
        return stream.read(length)


def _whole(file: Path, content_type: str) -> HttpResponse:
    response = HttpResponse(file.read_bytes(), content_type=content_type)
    response["Cache-Control"] = YEAR
    response["Accept-Ranges"] = "bytes"
    return response


def _ranged(file: Path, content_type: str, header: str) -> HttpResponse:
    size = file.stat().st_size
    match = RANGE.match(header.strip())
    if not match or not (match.group(1) or match.group(2)):
        return _whole(file, content_type)
    first, last = match.groups()
    if first:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
    else:
        start = max(size - int(last), 0)
        end = size - 1
    if start >= size or start > end:
        response = HttpResponse(status=416)
        response["Content-Range"] = f"bytes */{size}"
        return response
    end = min(end, start + SLICE - 1)
    response = HttpResponse(_read(file, start, end - start + 1), content_type=content_type, status=206)
    response["Content-Range"] = f"bytes {start}-{end}/{size}"
    response["Cache-Control"] = YEAR
    response["Accept-Ranges"] = "bytes"
    return response


@require_safe
def cdn_file(request, path: str):
    built = _built(path, request.GET.get("w"))
    if built:
        return _whole(built, "image/webp")
    raw = _inside(Path(settings.LEGACY_CDN_ROOT), path)
    if raw.is_file():
        content_type = mimetypes.guess_type(raw.name)[0] or "application/octet-stream"
        header = request.headers.get("Range")
        return _ranged(raw, content_type, header) if header else _whole(raw, content_type)
    query = request.META.get("QUERY_STRING")
    return HttpResponseRedirect(f"{OLD_CDN}{path}" + (f"?{query}" if query else ""))
