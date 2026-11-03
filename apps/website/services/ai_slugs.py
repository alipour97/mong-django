"""
Product addresses from LEBAZAI's AI title: /products-item/دورس-زنانه-یقه-گرد-طرح-کالج-مدل-1982
instead of the sales software's short name (دورس-1982).

The product name itself is not touched. The address it had before is kept as a
ProductSlugAlias, so links and search results that use it get a 301 to the new one.
"""
from __future__ import annotations

from django.db import transaction

from apps.website import slugs
from apps.website.models import Product, ProductSlugAlias


def _taken(key: str, product_id: int) -> bool:
    """Whether key is another product's address, now or before."""
    return (
        Product.objects.filter(slug_key=key).exclude(pk=product_id).exists()
        or ProductSlugAlias.objects.filter(slug_key=key).exclude(product_id=product_id).exists()
    )


def ai_slug_for(product: Product, ai_title: str) -> str:
    """The address product should have for ai_title ("" for no change)."""
    base = slugs.ai_slug_base(ai_title)
    if not base:
        return ""
    current = product.slug_key or slugs.slug_key(product.slug)
    slug, n = base, 1
    while _taken(slug, product.id):
        n += 1
        slug = f"{base}-{n}"
    return "" if slug == current else slug


@transaction.atomic
def apply_ai_slug(product: Product, ai_title: str) -> str:
    """Moves product to its AI-title address; returns the new slug, or "" when it already has it."""
    slug = ai_slug_for(product, ai_title)
    if not slug:
        return ""
    if product.slug:
        ProductSlugAlias.objects.update_or_create(
            slug_key=product.slug_key or slugs.slug_key(product.slug),
            defaults={"product": product, "slug": product.slug},
        )
    # Back to an address it had before: that one is current again, not an alias.
    ProductSlugAlias.objects.filter(product=product, slug_key=slugs.slug_key(slug)).delete()
    product.slug = slug
    product.save(update_fields=["slug"])
    return slug
