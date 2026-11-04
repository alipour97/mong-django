from django.db import migrations


def fix_sequences(apps, schema_editor):
    # Imported rows left some id counters behind (FileMedia's at 5), so new rows collided.
    from apps.website.sequences import move_past_ids

    move_past_ids(apps.get_models())


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0028_invoice_names'),
    ]

    operations = [
        migrations.RunPython(fix_sequences, migrations.RunPython.noop),
    ]
