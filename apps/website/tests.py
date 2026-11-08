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


class SeoCleanupTests(TestCase):
    def test_test_texts_tags_and_alts_go_and_real_ones_stay(self):
        import io

        from django.core.management import call_command

        from apps.website.models import Category, MediaAttachment, Tag

        Category.objects.create(id=1, title="شلوار", slug="s", short_description_html="تست شلوار")
        Category.objects.create(id=2, title="مانتو", slug="m", short_description_html="مانتو تست‌شده با پارچه‌ی کرپ")
        Tag.objects.create(id=1, title="تگ تست ۲")
        Tag.objects.create(id=2, title="تست 2")
        Tag.objects.create(id=3, title="مانتو اداری")
        MediaAttachment.objects.create(table=MediaAttachment.Table.CATEGORIES, record_id=1, alternative="تست", tooltip_title="زنانه")
        call_command("seo_cleanup", apply=True, stdout=io.StringIO())
        self.assertEqual(Category.objects.get(id=1).short_description_html, "")
        self.assertEqual(Category.objects.get(id=2).short_description_html, "مانتو تست‌شده با پارچه‌ی کرپ")
        self.assertEqual(list(Tag.objects.filter(is_deleted=False).values_list("id", flat=True)), [3])
        self.assertEqual(MediaAttachment.objects.get().alternative, "زنانه")


class BranchHoursTests(TestCase):
    def test_hours_text_and_schema(self):
        import datetime as dt
        from apps.website.models import Branch

        b = Branch(title="شعبه", opens=dt.time(10), closes=dt.time(22, 30))
        self.assertEqual(b.hours_text(), "شنبه تا پنج‌شنبه ۱۰ تا ۲۲:۳۰، جمعه تعطیل")
        self.assertEqual(len(b.opening_hours()), 1)
        b.friday_opens, b.friday_closes = dt.time(16), dt.time(22)
        self.assertTrue(b.hours_text().endswith("جمعه ۱۶ تا ۲۲"))
        self.assertEqual(b.opening_hours()[1], {"days": ["Friday"], "opens": "16:00", "closes": "22:00"})
        self.assertEqual(Branch(title="x").as_department()["hours"], "")
