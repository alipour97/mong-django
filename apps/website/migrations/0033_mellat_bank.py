from django.db import migrations


# Mellat logo supplied with the reference plugin; embedded so migrations are self-contained.
MELLAT_ICON = 'iVBORw0KGgoAAAANSUhEUgAAACcAAAAmCAMAAABwIXKiAAAABGdBTUEAALGPC/xhBQAAACBjSFJNAAB6JgAAgIQAAPoAAACA6AAAdTAAAOpgAAA6mAAAF3CculE8AAAAe1BMVEUAAACkFBWuHgWlFxFEKCWiEhrBNSywJQ6xLwKoHAe8IBnPiZPwyMyzHw+qHgK4VGCpJQxCMC+kGQ7+nwD/pgH/vCH4kwD/23HVM0bKISvdV2fkb3vWRVPripDvoqjRIjX1297xsrf0nJ3TIjj09Pb9z0L+0k/+1Vz///+mE6TCAAAAGHRSTlMAW7Z+Bi/8zRaQ/v3+6qX9IA1Efqv+SvcjVAgBAAAAAWJLR0QovbC1sgAAAAd0SU1FB98EChMlA9ob3ooAAAH/SURBVDjLtdRtf6IwDADwPoBtc5YrCM4K0rme+P2/4ZJW3Jzd7XcvLq8E/iZpiDL234MLWf2sarE5eMV/UNpsjuNxOoCo/6Iqrk7zaSQYQOpvS6pfr9vzW4bR23Lxqvm9/YNunuyE7hADKFdwcpq3GOdZabmZMGGIvik4cTydMeZZMeaaDboQbVty49uMcVJMcNYpH2KEwlnENJ5SKKZA1YxbX3aH44hyHNHhGRrNDIAruQnhmF3EsUhss+QiQowJnY9JFgcoAsJpstKxrsHeAhZ/enutdALncNg0ld71O6cboLkEMA8n4RaS84LthuEyDD0zniC1eV8yLSBmZ/VuuGAsCBWmy7JbGbZNLgahE7ss12HPqXJIxXOXHd7AiaLzcp/TLdel1zdHt3NzybnkUllk12tf2aJL+QzlS+zat9+7oPSwJPYy7GuI8dlZLaJXHY6F1MulZ5XEYacje5MX9OZAMi1b7HDBsbRSVjhsms0XxzWTFoR2+D72SGhunYInxzqq462pXW3oYwSl6eGj4yIXiR4Abvsiaa3vzpDz4Nfj5fBgbg3GcM8X6Wn4CNpnV8n83TWfNqnig8IJ8TwWqr9uIR3rLvMi1wpWJdvPC3hrjxqTlVsP9XVRcaHTKFJj1HLIF4W/LWfA44O8lHVDF6or/ZDw5yN49fmC/Xu8A511SpSUEWoVAAAAJXRFWHRkYXRlOmNyZWF0ZQAyMDE1LTA0LTEwVDE5OjM3OjAzLTA0OjAwVkmWnwAAACV0RVh0ZGF0ZTptb2RpZnkAMjAxNS0wNC0xMFQxOTozNzowMy0wNDowMCcULiMAAAAASUVORK5CYII='


def add_mellat(apps, schema_editor):
    # Make it available in the panel, without creating or enabling a gateway.
    apps.get_model("website", "BankInfo").objects.using(schema_editor.connection.alias).get_or_create(
        key="mellat", defaults={"name": "به‌پرداخت ملت", "icon": MELLAT_ICON},
    )


class Migration(migrations.Migration):
    dependencies = [("website", "0032_category_seo_copy")]
    operations = [migrations.RunPython(add_mellat, migrations.RunPython.noop)]
