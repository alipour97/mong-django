"""
Files uploaded in the admin gallery.

The original is kept under MEDIA_ROOT/uploads/<year>/<month>/<id>.<ext>.
Photos (jpg, png, webp, bmp, tiff) also get the site's WebP versions at
/img/u/<id> right away (images.build), like the old panel converted uploads
to WebP; gif, svg, ico are served as uploaded from /media/.
Videos (mov, mp4, etc.) are automatically transcoded to web-optimized MP4
with H.264 codec and FastStart (moov atom at byte 0) for zero-latency streaming.
The URL stored on FileMedia is public (PUBLIC_MEDIA_BASE_URL), so moving to a
CDN works as for every other image.
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
from apps.website.models import FileFormat

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

        # Generate lightweight desktop WebP poster (1280px) and mobile WebP poster (640px, ~18KB)
        poster_path = output_path.with_name(f"{output_path.stem}_poster.webp")
        poster_m_path = output_path.with_name(f"{output_path.stem}_poster_mobile.webp")
        poster_cmd = [
            ffmpeg_bin,
            "-y",
            "-ss", "00:00:00.000",
            "-i", str(output_path),
            "-vframes", "1",
            "-vf", "scale='min(1280,iw)':-1",
            "-q:v", "75",
            str(poster_path),
        ]
        poster_m_cmd = [
            ffmpeg_bin,
            "-y",
            "-ss", "00:00:00.000",
            "-i", str(output_path),
            "-vframes", "1",
            "-vf", "scale='min(640,iw)':-1",
            "-q:v", "75",
            str(poster_m_path),
        ]
        try:
            subprocess.run(poster_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
            subprocess.run(poster_m_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        except Exception as poster_exc:
            logger.warning("Could not generate poster thumbnail for %s: %s", output_path, poster_exc)

        # Generate lightweight mobile MP4 (640px wide, ~1MB) for seamless mobile playback
        mobile_path = output_path.with_name(f"{output_path.stem}_mobile.mp4")
        mobile_cmd = [
            ffmpeg_bin,
            "-y",
            "-i", str(output_path),
            "-vf", "scale='min(640,iw)':-2",
            "-c:v", "libx264",
            "-crf", "26",
            "-preset", "slow",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-an",
            str(mobile_path),
        ]
        try:
            subprocess.run(mobile_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        except Exception as mobile_exc:
            logger.warning("Could not generate mobile video for %s: %s", output_path, mobile_exc)

        return output_path
    except Exception as exc:
        temp_output.unlink(missing_ok=True)
        logger.exception("Failed to transcode video %s, keeping original: %s", target_path, exc)
        return target_path


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
        url = images.public_url(key)
        fmt = FileFormat.objects.filter(extension="webp").first() or fmt

    elif ext in CONVERT_VIDEOS:
        optimized_target = optimize_video(target)
        if optimized_target != target or ext != "mp4":
            target = optimized_target
            ext = "mp4"
            relative = target.relative_to(settings.MEDIA_ROOT)
            url = f"{settings.PUBLIC_MEDIA_BASE_URL.rstrip('/')}{settings.MEDIA_URL}{relative.as_posix()}"
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

