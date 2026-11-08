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

    def test_the_same_address_updates_the_article(self):
        first = self.upload(package(product="0730000197")).json()["data"]["result"]
        Article.objects.filter(id=first["id"]).update(view_count=7)
        r = self.upload(package(product=str(self.product.id)))
        self.assertEqual(r.status_code, 200, r.content.decode())
        result = r.json()["data"]["result"]
        self.assertEqual((result["id"], result["created"]), (first["id"], False))
        a = Article.objects.get()
        self.assertEqual((a.view_count, a.show_on_page), (7, True))
        self.assertEqual(BlogCategory.objects.count(), 1)
        self.assertEqual(ArticleTag.objects.count(), 2)

        self.upload(package(product=str(self.product.id)), publish="false")
        self.assertFalse(Article.objects.get().show_on_page)

        Article.objects.update(is_deleted=True)
        r = self.upload(package(product=str(self.product.id)))
        self.assertEqual(r.json()["data"]["result"]["id"], first["id"])
        self.assertTrue(r.json()["data"]["result"]["warnings"])
        self.assertFalse(Article.objects.get().is_deleted)

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


class AdminUserPasswordTests(TestCase):
    """A new password for a site admin, set from /django-admin/."""

    def setUp(self):
        from django.contrib.auth.models import User

        self.client.force_login(User.objects.create_superuser("root", password="x"))
        self.admin = AdminUser.objects.create(username="ali", cellphone="09121111111", first_name="علی",
                                              legacy_password="old", refresh_token_hash="abc")
        self.url = f"/django-admin/adminapi/adminuser/{self.admin.pk}/change/"

    def post(self, p1, p2):
        a = self.admin
        return self.client.post(self.url, {
            "username": a.username, "cellphone": a.cellphone, "email": "", "first_name": a.first_name,
            "last_name": "", "role": "", "is_active": "on", "created_0": "1404-01-01", "created_1": "10:00:00",
            "new_password1": p1, "new_password2": p2,
        })

    def test_page_opens(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'name="new_password1"')
        self.assertEqual(self.client.get("/django-admin/adminapi/adminuser/").status_code, 200)

    def test_sets_password_and_clears_sessions(self):
        r = self.post("Mong-Panel-2026!", "Mong-Panel-2026!")
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["adminform"].form.errors)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("Mong-Panel-2026!"))
        self.assertEqual((self.admin.legacy_password, self.admin.refresh_token_hash), ("", ""))

    def test_blank_keeps_password(self):
        self.admin.set_password("Mong-Panel-2026!")
        self.admin.save()
        self.assertEqual(self.post("", "").status_code, 302)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("Mong-Panel-2026!"))

    def test_mismatch_and_weak_rejected(self):
        for p1, p2 in (("Mong-Panel-2026!", "other-Panel-2026!"), ("123", "123")):
            r = self.post(p1, p2)
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.context["adminform"].form.errors)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.password, "")


class ChangeOwnPasswordTests(TestCase):
    """Auth/ChangePassword: the signed-in admin's own password, from the panel."""

    url = "/api/admin/v1/Auth/ChangePassword"

    def setUp(self):
        from apps.adminapi import tokens

        self.admin = AdminUser.objects.create(username="ali", cellphone="09121111111", refresh_token_hash="abc")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + tokens.issue(self.admin)["token"])

    def change(self, current, new):
        return self.client.post(self.url, {"currentPassword": current, "newPassword": new}, format="json")

    def test_needs_sign_in(self):
        self.assertEqual(APIClient().post(self.url, {"newPassword": "Mong-Panel-2026!"}, format="json").status_code, 401)

    def test_first_password_without_current(self):
        self.assertFalse(self.client.post("/api/admin/v1/Auth/GetProfile").json()["data"]["result"]["hasPassword"])
        r = self.change("", "Mong-Panel-2026!")
        self.assertEqual(r.status_code, 200, r.json())
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("Mong-Panel-2026!"))
        self.assertEqual(self.admin.refresh_token_hash, "")

    def test_current_password_required(self):
        self.admin.set_password("Old-Panel-2025!")
        self.admin.save()
        r = self.change("wrong", "Mong-Panel-2026!")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["message"], "رمز عبور فعلی اشتباه است.")
        self.assertEqual(self.change("Old-Panel-2025!", "Mong-Panel-2026!").status_code, 200)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("Mong-Panel-2026!"))

    def test_weak_password_rejected(self):
        for weak, message in (("38194726", "رمز عبور نباید فقط عدد باشد."), ("abc", "رمز عبور باید حداقل ۸ کاراکتر باشد.")):
            r = self.change("", weak)
            self.assertEqual((r.status_code, r.json()["message"]), (400, message))
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.has_password)
