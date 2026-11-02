"""
Apart from the schema change in 0022: PostgreSQL refuses the indexes that change builds
at its end while the foreign keys of rows inserted in the same transaction are unchecked.
"""
from django.core.management.color import no_style
from django.db import migrations


def copy_from_connector_tables(apps, schema_editor):
    """What the sync wrote to the erp tables moves onto the site's own products, so the site is whole before the next sync."""
    Product = apps.get_model("website", "Product")
    Variant = apps.get_model("website", "ProductVariant")
    Stock = apps.get_model("website", "VariantStock")
    ErpProduct = apps.get_model("erp", "ErpProduct")
    ErpVariant = apps.get_model("erp", "ErpVariant")
    ErpStock = apps.get_model("erp", "ErpStock")
    products = []
    for row in ErpProduct.objects.all().iterator():
        products.append(Product(
            id=row.product_id, on_sale=True, erp_id=row.erp_id, price=row.base_price, reduction=row.reduction, sale_price=row.sale_price,
            name_en=row.name_en, attributes=row.attributes, size_guide_key=row.size_guide_key, sold=row.sold,
        ))
    known = set(Product.objects.filter(id__in=[p.id for p in products]).values_list("id", flat=True))
    Product.objects.bulk_update([p for p in products if p.id in known], ["on_sale", "erp_id", "price", "reduction", "sale_price", "name_en",
                                                                         "attributes", "size_guide_key", "sold"], batch_size=500)
    columns = ("id", "product_id", "erp_ref", "barcode", "color_id", "color_name", "color_value", "color_priority", "color_family",
               "size_id", "size_name", "size_value", "size_priority")
    Variant.objects.bulk_create([Variant(**row) for row in ErpVariant.objects.filter(product_id__in=known).values(*columns)], batch_size=2000)
    Stock.objects.bulk_create([
        Stock(**row) for row in ErpStock.objects.filter(variant__product_id__in=known).values("variant_id", "warehouse_id", "warehouse_title", "qty")
    ], batch_size=2000)
    with schema_editor.connection.cursor() as cursor:
        for statement in schema_editor.connection.ops.sequence_reset_sql(no_style(), [Variant, Stock]):
            cursor.execute(statement)


class Migration(migrations.Migration):

    dependencies = [
        ('erp', '0003_site_vouchers_manual_photos'),
        ('website', '0022_site_owns_catalog'),
    ]

    operations = [
        migrations.RunPython(copy_from_connector_tables, migrations.RunPython.noop),
    ]
