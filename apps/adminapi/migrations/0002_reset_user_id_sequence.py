"""
Admin accounts were imported with their Dadehfa ids and PostgreSQL's counter stayed
behind them, so User/Add failed on the primary key. No schema change.
"""
from django.core.management.color import no_style
from django.db import migrations


def reset_sequence(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        for statement in connection.ops.sequence_reset_sql(no_style(), [apps.get_model("adminapi", "AdminUser")]):
            cursor.execute(statement)


class Migration(migrations.Migration):
    dependencies = [("adminapi", "0001_initial")]

    operations = [migrations.RunPython(reset_sequence, migrations.RunPython.noop)]
