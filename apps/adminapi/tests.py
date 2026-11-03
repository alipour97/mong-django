import io
import tempfile
import zipfile
from unittest import mock

from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from apps.adminapi.models import AdminUser
from apps.storefront import blog
from apps.website import article_html
from apps.website.models import Article, ArticleTag, BlogCategory, FileFormat, FileMedia, Product


def photo(color="red", size=(1200, 800), fmt="JPEG") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, fmt)
    return out.getvalue()


PAGE = """<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<title>راهنمای انتخاب مانتو اداری</title>
<meta name="description" content="چطور مانتو اداری مناسب انتخاب کنیم؟">
<meta name="slug" content="راهنمای مانتو اداری">
<meta name="cover" content="images/cover.jpg">
<meta name="cover-alt" content="سه مانتو اداری روی رگال">
<meta name="categories" content="راهنمای استایل">
<meta name="tags" content="مانتو, استایل اداری">
</head><body>
<h1>راهنمای انتخاب مانتو اداری</h1>
<p class="lead" style="color:red">مقدمه</p>
<h2 style="color:#711f7e">رنگ مناسب</h2>
<figure><img src="images/a.jpg" alt="مانتو سرمه‌ای"><figcaption>سرمه‌ای</figcaption></figure>
<div data-product="{product}">ignored</div>
<a class="button big" href="https://new.mong.ir/products-category/manto" style="color:black">همه مانتوها</a>
<script>alert(1)</script>
<section class="faq"><h2>سوالات متداول</h2>
<details><summary>چه رنگی؟</summary><p>سرمه‌ای</p></details></section>
</body></html>"""


def package(page=PAGE, files=None, product="") -> io.BytesIO:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("article.html", page.replace("{product}", product))
        for name, data in (files if files is not None else {"images/cover.jpg": photo(), "images/a.jpg": photo("blue")}).items():
            zf.writestr(name, data)
    out.seek(0)
    out.name = "article.zip"
    return out


class ArticleHtmlTests(TestCase):
    def test_clean_keeps_structure_and_drops_styles(self):
        html = article_html.clean(
            '<div class="x" style="a"><p style="color:red"><span style="font-family:x">متن</span></p>'
            '<h1>تیتر</h1><aside class="tip other">نکته</aside><a href="javascript:x()">بد</a>'
            '<img src="x" onerror="y"><iframe src="z"></iframe><p></p></div>'
        )
        self.assertEqual(html, '<p>متن</p><h2>تیتر</h2><aside class="tip">نکته</aside>بد')

    def test_prepare_adds_toc_faq_and_lazy_photos(self):
        out = article_html.prepare(
            '<h2>اول</h2><img src="/img/u/abc" alt="x"><h3>دوم</h3><h2>اول</h2>'
            '<section class="faq"><details><summary>سوال؟</summary><p>جواب</p></details></section>'
            '<table><tr><td>1</td></tr></table>', lambda refs, single: "",
        )
        self.assertEqual([t["id"] for t in out.toc], ["اول", "دوم", "اول-2"])
        self.assertEqual(out.faq, [{"question": "سوال؟", "answer": "جواب"}])
        self.assertIn('loading="lazy"', out.html)
        self.assertIn("/img/u/abc?w=640 640w", out.html)
        self.assertIn('<div class="table-wrap"><table>', out.html)


@override_settings(OWN_HOSTS={"new.mong.ir", "localhost"})
class ArticlePackageTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        override = override_settings(MEDIA_ROOT=self.media.name)
        override.enable()
        self.addCleanup(override.disable)
        for ext in ("jpg", "jpeg", "png", "webp"):
            FileFormat.objects.create(type="Image", extension=ext)
        self.product = Product.objects.create(title="لينن 4", slug="شلوار-لینن", barcode="0730000197", on_sale=True,
                                              price=20_000_000, sale_price=15_000_000)
        self.client = APIClient()
        self.client.force_authenticate(AdminUser.objects.create(username="a", cellphone="09120000000"))
        auth = mock.patch("apps.adminapi.views.auth.AdminView.authentication_classes", [])
        auth.start()
        self.addCleanup(auth.stop)

    def upload(self, data, **extra):
        return self.client.post("/api/admin/v1/Article/Import", {"file": data, **extra}, format="multipart")

    def test_a_package_becomes_an_article(self):
        r = self.upload(package(product="/products-item/شلوار-لینن"))
        self.assertEqual(r.status_code, 200, r.content.decode())
        a = Article.objects.get(id=r.json()["data"]["result"]["id"])
        self.assertEqual((a.title, a.uniq_url, a.show_on_page), ("راهنمای انتخاب مانتو اداری", "راهنمای-مانتو-اداری", True))
        self.assertEqual(FileMedia.objects.count(), 2)
        self.assertTrue(a.thumbnail.startswith("/img/u/"))
        self.assertEqual(FileMedia.objects.get(url=a.thumbnail).alternative, "سه مانتو اداری روی رگال")
        self.assertNotIn("<h1", a.content)
        self.assertNotIn("style=", a.content)
        self.assertNotIn("script", a.content)
        self.assertIn(f'<div data-product="{self.product.id}"></div>', a.content)
        self.assertIn('<a class="button" href="/products-category/manto">', a.content)
        self.assertRegex(a.content, r'<img alt="مانتو سرمه‌ای" height="800" src="/img/u/\w+" width="1200"/>')
        self.assertEqual(list(a.categories.values_list("title", flat=True)), ["راهنمای استایل"])
        self.assertEqual(sorted(a.tags.values_list("name", flat=True)), ["استایل اداری", "مانتو"])

        page = blog.page_data(a)
        self.assertIn('href="/products-item/شلوار-لینن"', page["articleContent"])
        self.assertIn("ناموجود", page["articleContent"])
        with mock.patch("apps.storefront.catalog.ProductBundle.in_stock", return_value=True):
            card = blog.page_data(a)["articleContent"]
        self.assertIn("<del>۲٬۰۰۰٬۰۰۰</del>", card)
        self.assertIn("۱٬۵۰۰٬۰۰۰ <small>تومان</small>", card)
        self.assertIn("٪۲۵", card)
        self.assertEqual(page["faq"], [{"question": "چه رنگی؟", "answer": "سرمه‌ای"}])
        meta = self.client.get(f"/api/v1/SearchEngine/blog/{a.uniq_url}/meta").json()
        self.assertEqual((meta["type"], meta["canonical"]), ("BlogPosting", f"/blog/{a.uniq_url}"))

    def test_the_same_address_needs_replace(self):
        self.upload(package(product="0730000197"))
        r = self.upload(package(product="0730000197"))
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.json()["data"]["slugTaken"])
        r = self.upload(package(product=str(self.product.id)), replace="true", publish="false")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Article.objects.count(), 1)
        self.assertFalse(Article.objects.get().show_on_page)
        self.assertEqual(BlogCategory.objects.count(), 1)
        self.assertEqual(ArticleTag.objects.count(), 2)

    def test_problems_are_listed_and_nothing_is_kept(self):
        r = self.upload(package(product="نیست", files={"images/cover.jpg": photo()}))
        self.assertEqual(r.status_code, 400)
        problems = r.json()["data"]["problems"]
        self.assertTrue(any("images/a.jpg" in p for p in problems))
        self.assertTrue(any("نیست" in p for p in problems))
        self.assertEqual(Article.objects.count(), 0)
        self.assertEqual(FileMedia.objects.count(), 0)

    def test_editor_saves_are_cleaned_too(self):
        r = self.upload(package(product="لینن 4"))
        a = Article.objects.get(id=r.json()["data"]["result"]["id"])
        self.assertIn(f'data-product="{self.product.id}"', a.content)
        r = self.client.get(f"/api/admin/v1/Article/{a.id}/Preview")
        self.assertIn("blog-product", r.json()["data"]["result"]["articleContent"])
