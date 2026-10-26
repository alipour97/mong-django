"""
Fallback for /img/<key>?w= when a request reaches Django instead of nginx
(local runserver). Same rules as deploy/nginx/: nearest pre-built width.
"""
from django.http import FileResponse, Http404

from . import images


def image_variant(request, key: str):
    root = images.img_root().resolve()
    folder = (root / key).resolve()
    if root not in folder.parents:
        raise Http404
    try:
        w = int(request.GET.get("w", ""))
    except ValueError:
        w = None
    name = "full"
    if w:
        name = next((str(x) for x in images.WIDTHS if w <= x), str(images.WIDTHS[-1]))
    for candidate in (folder / f"{name}.webp", folder / "full.webp"):
        if candidate.exists():
            resp = FileResponse(candidate.open("rb"), content_type="image/webp")
            resp["Cache-Control"] = "public, max-age=31536000, immutable"
            return resp
    raise Http404
