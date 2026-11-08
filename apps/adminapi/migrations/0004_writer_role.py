"""The «نویسنده بلاگ» role, so a writer account can be made in the panel's user page."""
from django.db import migrations
from django.db.models import Max

WRITER = 3
TITLE = "نویسنده بلاگ"


def add_role(apps, schema_editor):
    AdminRole = apps.get_model("adminapi", "AdminRole")
    if AdminRole.objects.filter(role_type=WRITER, is_deleted=False).exists():
        return
    next_id = (AdminRole.objects.aggregate(m=Max("id"))["m"] or 0) + 1
    AdminRole.objects.create(id=next_id, title=TITLE, role_type=WRITER)


class Migration(migrations.Migration):
    dependencies = [("adminapi", "0003_blog_author_profile")]

    operations = [migrations.RunPython(add_role, migrations.RunPython.noop)]
