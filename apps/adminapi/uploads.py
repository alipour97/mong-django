"""
Files uploaded in the admin gallery.

The original is kept under MEDIA_ROOT/uploads/<year>/<month>/<id>.<ext>.
Photos (jpg, png, webp, bmp, tiff) also get the site's WebP versions at
/img/u/<id> right away (images.build), like the old panel converted uploads
to WebP; gif, svg, ico are served as uploaded from /media/.
Videos (mov, mp4, etc.) are automatically transcoded to web-optimized MP4
with H.264 codec and FastStart (moov atom at byte 0) for zero-latency streaming.
FileMedia keeps a relative path (/media/uploads/..., /img/u/<id>); the API adds
the current PUBLIC_MEDIA_BASE_URL when answering, so a new domain or a CDN
needs no change in the data.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import uuid
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from apps.website import images
from apps.website.models import FileFormat, FileMedia

logger = logging.getLogger(__name__)

CONVERT_IMAGES = {"jpg", "jpeg", "png", "webp", "bmp", "tiff", "tif"}
CONVERT_VIDEOS = {"mov", "mp4", "m4v", "mkv", "avi", "webm", "flv", "wmv"}


class UploadError(ValueError):
    pass


def get_ffmpeg_binary() -> str | None:
    """Find system ffmpeg or fallback to imageio-ffmpeg bundled binary."""
    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        return sys_ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def optimize_video(target_path: Path) -> Path:
    """
    Transcode uploaded video to web-optimized MP4:
    - H.264 codec (universal browser compatibility)
    - CRF 23, fast preset (great quality / small file size)
    - FastStart: moves moov atom to byte 0 for instant playback start
    - AAC audio (if audio track exists)
    """
    ffmpeg_bin = get_ffmpeg_binary()
    if not ffmpeg_bin:
        logger.warning("ffmpeg binary not found; keeping original video: %s", target_path)
        return target_path

    output_path = target_path.with_suffix(".mp4")
    temp_output = target_path.parent / f"tmp_{output_path.name}"

    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", str(target_path),
        "-map", "0:v:0",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-crf", "23",
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-c:a", "aac",
        "-b:a", "96k",
        str(temp_output),
    ]

    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=180,
        )
        temp_output.replace(output_path)
        if target_path != output_path and target_path.exists():
            target_path.unlink(missing_ok=True)

        make_video_variants(output_path, ffmpeg_bin)
        return output_path
    except Exception as exc:
        temp_output.unlink(missing_ok=True)
        logger.exception("Failed to transcode video %s, keeping original: %s", target_path, exc)
        return target_path


# Phone screens are ~412 CSS px wide at 1.75-3x density, so the phone poster and
# video need ~1000 px to look sharp; 640 px was visibly soft.
POSTER_WIDTH, POSTER_MOBILE_WIDTH, POSTER_QUALITY = 1280, 1080, 80
MOBILE_VIDEO_WIDTH, MOBILE_VIDEO_CRF = 960, 25


def make_video_variants(video: Path, ffmpeg_bin: str | None = None) -> None:
    """The files the site shows next to a video: <stem>_poster.webp (desktop),
    <stem>_poster_mobile.webp and <stem>_mobile.mp4 (phones, no sound)."""
    ffmpeg_bin = ffmpeg_bin or get_ffmpeg_binary()
    if not ffmpeg_bin:
        return

    def run(args: list[str], what: str, timeout: int) -> None:
        try:
            subprocess.run([ffmpeg_bin, "-y", *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=timeout, check=True)
        except Exception as exc:
            logger.warning("Could not generate %s for %s: %s", what, video, exc)

    for width, suffix in ((POSTER_WIDTH, "_poster"), (POSTER_MOBILE_WIDTH, "_poster_mobile")):
        run(["-ss", "00:00:00.000", "-i", str(video), "-vframes", "1", "-vf", f"scale='min({width},iw)':-1",
             "-q:v", str(POSTER_QUALITY), str(video.with_name(f"{video.stem}{suffix}.webp"))], "poster", 30)
    run(["-i", str(video), "-vf", f"scale='min({MOBILE_VIDEO_WIDTH},iw)':-2", "-c:v", "libx264",
         "-crf", str(MOBILE_VIDEO_CRF), "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an",
         str(video.with_name(f"{video.stem}_mobile.mp4"))], "mobile video", 180)


def save(uploaded) -> dict:
    """Store an UploadedFile. -> {url (a relative path), format_id, width, height, size, local_path}"""
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
    url = f"{settings.MEDIA_URL}{relative.as_posix()}"

    if ext in CONVERT_IMAGES:
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
        url = images.relative_url(key)
        fmt = FileFormat.objects.filter(extension="webp").first() or fmt

    elif ext in CONVERT_VIDEOS:
        optimized_target = optimize_video(target)
        if optimized_target != target or ext != "mp4":
            target = optimized_target
            ext = "mp4"
            relative = target.relative_to(settings.MEDIA_ROOT)
            url = f"{settings.MEDIA_URL}{relative.as_posix()}"
            fmt = FileFormat.objects.filter(extension="mp4").first() or fmt

    file_size = target.stat().st_size if target.exists() else len(data)
    return {
        "url": url,
        "format_id": fmt.id,
        "width": width,
        "height": height,
        "size": file_size,
        "local_path": str(relative),
    }



def save_media(uploaded, domain: str, alternative: str = "") -> FileMedia:
    """Store an UploadedFile and add it to the gallery."""
    saved = save(uploaded)
    now = timezone.now()
    return FileMedia.objects.create(
        file_name=uploaded.name, url=saved["url"], format_id=saved["format_id"], upload_time=now,
        size=saved["size"], width=saved["width"], height=saved["height"], domain=domain,
        alternative=alternative, created=now,
    )
