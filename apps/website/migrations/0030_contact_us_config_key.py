"""
The admin's contact-us form saved to PrimaryConfig "contactUsConfig" while the site (contact page, about-us,
JSON-LD) reads "contactUsConfig2", so an edited address or map location never reached the site. The form now
uses "contactUsConfig2". What it already saved under the old key (recognised by the form's own fields, such as
"lat"; the legacy rows use "location") is copied over, so nothing the admin entered is lost.
"""
import json

from django.db import migrations

FORM_FIELDS = {"lat", "lng", "phones", "socials", "featuredImage", "enabled"}


def _load(raw):
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def copy_forward(apps, schema_editor):
    PrimaryConfig = apps.get_model("website", "PrimaryConfig")
    old = PrimaryConfig.objects.filter(key="contactUsConfig", is_deleted=False).first()
    saved = _load(old.value) if old else None
    if not saved or not FORM_FIELDS & saved.keys():
        return  # only the legacy shape: nothing the new form wrote
    new = PrimaryConfig.objects.filter(key="contactUsConfig2").first()  # key is unique, deleted rows included
    if new is None:
        PrimaryConfig.objects.create(key="contactUsConfig2", value=json.dumps(saved, ensure_ascii=False))
        return
    merged = {**((_load(new.value) or {}) if not new.is_deleted else {}), **saved}
    new.value = json.dumps(merged, ensure_ascii=False)
    new.is_deleted = False
    new.save(update_fields=["value", "is_deleted"])


class Migration(migrations.Migration):
    dependencies = [("website", "0029_fix_sequences")]
    operations = [migrations.RunPython(copy_forward, migrations.RunPython.noop)]
