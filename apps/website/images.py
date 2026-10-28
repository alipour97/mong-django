"""
Pre-built, compressed product/site images.

Every source image is stored once as WebP (quality 80, original dimensions)
plus a few narrower versions, under MEDIA_ROOT/img/<key>/:

    full.webp  384.webp  640.webp  828.webp  1080.webp  1920.webp

(narrower files only when the original is wider). The frontend asks for
`<url>?w=<width>&q=..`; nginx maps w to the nearest file (deploy/nginx/).
Nothing is generated per request: build_images runs nightly.

Sources:
- Samian galleries:  key "s/<productmain_id>/<file id>", fetched from Samian.
- Legacy site media: key "c/<path on cdn.mong.ir without extension>", read
  from the local mirror of cdn.mong.ir (fetched from cdn.mong.ir if missing).

Public URLs are <PUBLIC_MEDIA_BASE_URL>/img/<key>, so moving images to a CDN
means uploading MEDIA_ROOT/img and changing that one setting.
"""
from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

from django.conf import settings

QUALITY = 75
WIDTHS = (384, 640, 828, 1080, 1920)
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
LEGACY_CDN = re.compile(r"https?://cdn\.mong\.ir/([^?\"'\s]+)")


def img_root() -> Path:
    return Path(settings.MEDIA_ROOT) / "img"


def relative_url(key: str) -> str:
    """What the database keeps for a built image: a path, never a domain."""
    return f"{settings.PUBLIC_IMG_PATH}/{key}"


def public_url(key: str) -> str:
    return f"{settings.PUBLIC_MEDIA_BASE_URL.rstrip('/')}{relative_url(key)}"


OWN_URL = re.compile(r"(?i)\bhttps?://([a-z0-9.-]+)(?::\d+)?(?=/)")
LOCAL_PATHS = ("/media/", "/img/", "/cdn/", "/api/img/", "/api/cdn/")


def _own(m: re.Match) -> str:
    return "" if m.group(1).lower() in settings.OWN_HOSTS else m.group(0)


def strip_domain(url: str) -> str:
    """Our own absolute URL -> its path (https://site/media/x.webp -> /media/x.webp); others unchanged."""
    m = OWN_URL.match(url or "")
    return url[m.end():] if m and m.group(1).lower() in settings.OWN_HOSTS else url


def strip_domains_in_text(text: str) -> str:
    """strip_domain for every URL inside a JSON/HTML string (PrimaryConfig values)."""
    return OWN_URL.sub(_own, text) if text else text


def absolute_media(path: str) -> str:
    """A stored local path (/media/..., /img/...) as a URL on the current media host."""
    return f"{settings.PUBLIC_MEDIA_BASE_URL.rstrip('/')}{path}"


def is_built(key: str) -> bool:
    return (img_root() / key / "full.webp").exists()


# -----------------------------------------------------------------------------
# Keys
# -----------------------------------------------------------------------------
def samian_key(productmain_id: int, file_path: str) -> str:
    """Samian names files ..._<32 hex id>.<ext>; that id is stable per file."""
    stem = Path(file_path).stem
    file_id = stem.rsplit("_", 1)[-1]
    if not re.fullmatch(r"[0-9A-Fa-f]{16,}", file_id):
        file_id = hashlib.sha1(file_path.encode()).hexdigest()
    return f"s/{productmain_id}/{file_id.lower()}"


def legacy_key(url: str) -> str | None:
    """Key for an image on cdn.mong.ir, or None when it is not a convertible image."""
    m = LEGACY_CDN.match(url or "")
    if not m:
        return None
    path = Path(m.group(1))
    if path.suffix.lower() not in IMAGE_EXT:
        return None
    return "c/" + str(path.with_suffix(""))


def legacy_local_path(url: str) -> Path | None:
    m = LEGACY_CDN.match(url or "")
    return Path(settings.LEGACY_CDN_ROOT) / m.group(1) if m else None


# -----------------------------------------------------------------------------
# URL rewriting used by the API
# -----------------------------------------------------------------------------
def site_media_url(url: str) -> str:
    """
    Public URL for a media URL stored in the site data.
    Built images -> /img/<key>; other files on cdn.mong.ir (video, ico, not yet
    built) -> the local mirror under /cdn/; everything else unchanged.
    """
    if not url:
        return url
    url = strip_domain(url)  # rows saved before paths were relative
    if url.startswith(LOCAL_PATHS):
        return absolute_media(url)
    key = legacy_key(url)
    if key and is_built(key):
        return public_url(key)
    m = LEGACY_CDN.match(url)
    if m and legacy_local_path(url).exists():
        return f"{settings.PUBLIC_MEDIA_BASE_URL.rstrip('/')}/cdn/{m.group(1)}"
    return url


LOCAL_IN_TEXT = re.compile(r"""(?<=["'(=])(/(?:media|img|cdn|api/img|api/cdn)/)""")


def rewrite_media_in_text(text: str) -> str:
    """Public URLs inside a JSON/HTML string (PrimaryConfig values): local paths on the current
    media host, cdn.mong.ir files on our copy."""
    if not text:
        return text
    text = LOCAL_IN_TEXT.sub(lambda m: absolute_media(m.group(1)), strip_domains_in_text(text))
    return LEGACY_CDN.sub(lambda m: site_media_url(m.group(0)), text) if "cdn.mong.ir" in text else text


# -----------------------------------------------------------------------------
# Building
# -----------------------------------------------------------------------------
def build(key: str, data: bytes) -> int:
    """Write full.webp and the narrower versions for one image. Returns bytes written."""
    from PIL import Image, ImageOps

    out = img_root() / key
    out.mkdir(parents=True, exist_ok=True)
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
        written = 0
        # full.webp last: its presence marks the image as complete (is_built)
        targets = [(str(w), w) for w in WIDTHS if w < im.width] + [("full", None)]
        for name, width in targets:
            frame = im if width is None else im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
            tmp = out / f".{name}.webp.tmp"
            frame.save(tmp, "WEBP", quality=QUALITY, method=6)
            tmp.replace(out / f"{name}.webp")
            written += (out / f"{name}.webp").stat().st_size
    return written
