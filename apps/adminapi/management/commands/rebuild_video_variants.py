"""
Regenerate the posters and phone videos of uploaded videos with the current
settings in apps.adminapi.uploads (make_video_variants).

    python manage.py rebuild_video_variants [--dry-run]
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.adminapi.uploads import make_video_variants


class Command(BaseCommand):
    help = "Regenerate _poster.webp, _poster_mobile.webp and _mobile.mp4 for every uploaded video."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, dry_run=False, **options):
        root = Path(settings.MEDIA_ROOT) / "uploads"
        videos = [p for p in sorted(root.rglob("*.mp4")) if not p.stem.endswith("_mobile") and not p.name.startswith("tmp_")]
        for video in videos:
            self.stdout.write(str(video.relative_to(root)))
            if not dry_run:
                make_video_variants(video)
        self.stdout.write(self.style.SUCCESS(f"{len(videos)} video(s){' (dry run)' if dry_run else ''}"))
