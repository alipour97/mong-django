from django.db import migrations

from apps.smsir import normalize_mobile


def normalize_gift_card_details(apps, schema_editor):
    cards = apps.get_model("erp", "ErpGiftCard").objects.using(schema_editor.connection.alias)
    changed = []
    for card in cards.only("id", "number", "mobile").iterator():
        number, mobile = card.number.strip(), normalize_mobile(card.mobile)
        if (number, mobile) != (card.number, card.mobile):
            card.number, card.mobile = number, mobile
            changed.append(card)
    cards.bulk_update(changed, ["number", "mobile"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [("erp", "0007_sync_runs")]

    operations = [migrations.RunPython(normalize_gift_card_details, migrations.RunPython.noop)]
