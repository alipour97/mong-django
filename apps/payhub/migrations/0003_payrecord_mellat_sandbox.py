from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("payhub", "0002_snapp_log")]

    operations = [migrations.AddField(
        model_name="payrecord", name="mellat_sandbox", field=models.BooleanField(default=True),
    )]
