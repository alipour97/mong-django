from django.test import TestCase

from apps.storefront.views import _product_by_slug
from apps.website import slugs
from apps.website.models import Product, ProductSlugAlias
from apps.website.services.ai_slugs import apply_ai_slug


class AiSlugTests(TestCase):
    def setUp(self):
        self.p = Product.objects.create(title="دورس 1982", slug="دورس-1982", on_sale=True)

    def test_slug_from_ai_title_keeps_old_address(self):
        self.assertEqual(apply_ai_slug(self.p, "دورس زنانه یقه گرد طرح کالج مدل 1982"), "دورس-زنانه-یقه-گرد-طرح-کالج-مدل-1982")
        self.p.refresh_from_db()
        self.assertEqual(self.p.title, "دورس 1982")
        self.assertEqual(_product_by_slug("دورس-1982"), self.p)
        self.assertEqual(apply_ai_slug(self.p, "دورس زنانه یقه گرد طرح کالج مدل 1982"), "")

    def test_back_to_an_earlier_address(self):
        apply_ai_slug(self.p, "دورس زنانه")
        apply_ai_slug(self.p, "دورس 1982")
        self.p.refresh_from_db()
        self.assertEqual(self.p.slug, "دورس-1982")
        self.assertEqual(list(ProductSlugAlias.objects.values_list("slug", flat=True)), ["دورس-زنانه"])

    def test_another_products_old_address_is_taken(self):
        other = Product.objects.create(title="x", slug="دورس-زنانه", on_sale=True)
        apply_ai_slug(other, "چیز دیگر")
        self.assertEqual(apply_ai_slug(self.p, "دورس زنانه"), "دورس-زنانه-2")

    def test_long_title_is_cut_at_a_word(self):
        base = slugs.ai_slug_base("روپوش زنانه کتان کجراه یقه مردانه دکمه‌دار با آستین کیمونو بلند آزاد و برش اورسایز قد متوسط")
        self.assertEqual(base, "روپوش-زنانه-کتان-کجراه-یقه-مردانه-دکمه-دار-با-آستین-کیمونو-بلند-آزاد")

    def test_title_punctuation_is_a_word_break(self):
        base = slugs.ai_slug_base("شومیز زنانه یقه مردانه، آستین بلند؛ دو جیب")
        self.assertEqual(base, "شومیز-زنانه-یقه-مردانه-آستین-بلند-دو-جیب")
