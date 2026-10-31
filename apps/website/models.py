"""
Website layer models (what used to live in DadehfaOnlineShop).

Samian ERP owns products, barcodes, prices and stock. Everything the website
adds on top of that lives here: the online category tree and slugs, product
pages (titles, descriptions, images per color), home page configs, banners,
collections, outfits, themes, comments and so on.

Primary keys keep the legacy DadehfaOnlineShop ids so the ids stored inside
configs (sortRowsConfig, webSortOrder), URLs, carts and favorites stay valid.
"""
from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


def validate_slug(value: str) -> None:
    from django.core.exceptions import ValidationError

    from .slugs import is_valid

    if value and not is_valid(value):
        raise ValidationError(_("آدرس فقط حروف فارسی یا انگلیسی، عدد، - و _ می‌تواند داشته باشد (بدون فاصله و /)."))


class SlugKeyMixin(models.Model):
    """Keeps slug_key in step with slug on save (bulk writes: manage.py fix_slugs)."""

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        from .slugs import slug_key

        self.slug_key = slug_key(self.slug)
        if kwargs.get("update_fields") is not None and "slug" in kwargs["update_fields"]:
            kwargs["update_fields"] = {*kwargs["update_fields"], "slug_key"}
        super().save(*args, **kwargs)


class LegacyMixin(models.Model):
    """Fields every imported row carries over from DadehfaOnlineShop."""

    map_id = models.CharField(_("MapId (کد در سیستم مبدا)"), max_length=64, blank=True, default="", db_index=True)
    is_deleted = models.BooleanField(_("حذف شده"), default=False, db_index=True)
    created = models.DateTimeField(_("ایجاد"), null=True, blank=True)
    last_modified = models.DateTimeField(_("آخرین تغییر"), null=True, blank=True)

    class Meta:
        abstract = True


# -----------------------------------------------------------------------------
# Catalog
# -----------------------------------------------------------------------------
class Brand(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    title = models.CharField(_("عنوان"), max_length=255)
    group_name = models.CharField(_("گروه برند"), max_length=255, blank=True, default="")

    class Meta:
        verbose_name = _("برند")
        verbose_name_plural = _("برندها")

    def __str__(self):
        return self.title


class Category(SlugKeyMixin, LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")
    title = models.CharField(_("عنوان"), max_length=255)
    slug = models.CharField(_("اسلاگ"), max_length=255, blank=True, default="", db_index=True, validators=[validate_slug])
    has_manual_slug = models.BooleanField(default=False)
    # slugs.slug_key(slug): how addresses are looked up (ي/ی, invisible marks, encoding)
    slug_key = models.CharField(max_length=512, blank=True, default="", db_index=True, editable=False)
    group_level = models.IntegerField(_("سطح"), null=True, blank=True)
    display_priority = models.IntegerField(_("اولویت نمایش"), default=0)
    in_main_page = models.BooleanField(_("نمایش در صفحه اصلی"), default=False)
    is_online_active = models.BooleanField(_("فعال در سایت"), default=False, db_index=True)
    discount = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    short_description_html = models.TextField(blank=True, default="")
    long_description_html = models.TextField(blank=True, default="")
    base_category_type_id = models.IntegerField(null=True, blank=True)
    base_category_type_title = models.CharField(max_length=255, blank=True, default="")
    # ERP department code; PTC/Samian department this online category maps to
    parent_map_id = models.CharField(max_length=64, blank=True, default="")
    # The Samian department (codingdepartment_id) this category stands for; see sync_site_catalog.
    samian_department_id = models.BigIntegerField(_("دپارتمان سامیان"), null=True, blank=True, unique=True)

    class Meta:
        verbose_name = _("دسته‌بندی سایت")
        verbose_name_plural = _("دسته‌بندی‌های سایت")
        ordering = ["display_priority", "id"]

    def __str__(self):
        return self.title


class Tag(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    title = models.CharField(max_length=255)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")

    class Meta:
        verbose_name = _("برچسب")
        verbose_name_plural = _("برچسب‌ها")

    def __str__(self):
        return self.title


class CategoryTag(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="tag_links")
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, related_name="category_links")

    class Meta:
        verbose_name = _("برچسب دسته")
        verbose_name_plural = _("برچسب‌های دسته")

    def __str__(self) -> str:
        return f"{self.category_id} ← {self.tag_id}"


class Feature(LegacyMixin):
    """رنگ (1) و سایز (2)."""

    COLOR = 1
    SIZE = 2

    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=128)
    display_priority = models.IntegerField(default=0)

    class Meta:
        verbose_name = _("ویژگی")
        verbose_name_plural = _("ویژگی‌ها")

    def __str__(self):
        return self.name


class FeatureValue(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    feature = models.ForeignKey(Feature, on_delete=models.CASCADE, related_name="values")
    name = models.CharField(max_length=255)
    value = models.CharField(_("مقدار (کد رنگ / سایز)"), max_length=255, blank=True, default="")
    display_priority = models.IntegerField(default=0)

    class Meta:
        verbose_name = _("مقدار ویژگی")
        verbose_name_plural = _("مقادیر ویژگی")

    def __str__(self):
        return f"{self.feature_id}:{self.name}"


class Product(SlugKeyMixin, LegacyMixin):
    """Product page on the website. Pricing and stock come from Samian once linked."""

    id = models.BigAutoField(primary_key=True)
    title = models.CharField(_("عنوان"), max_length=512)
    slug = models.CharField(_("اسلاگ"), max_length=512, blank=True, default="", db_index=True, validators=[validate_slug])
    has_manual_slug = models.BooleanField(default=False)
    # slugs.slug_key(slug): how addresses are looked up (ي/ی, invisible marks, encoding)
    slug_key = models.CharField(max_length=512, blank=True, default="", db_index=True, editable=False)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="products")
    brand = models.ForeignKey(Brand, null=True, blank=True, on_delete=models.SET_NULL, related_name="products")
    barcode = models.CharField(_("کد کالا"), max_length=64, blank=True, default="", db_index=True)

    price = models.DecimalField(_("قیمت (ریال)"), max_digits=18, decimal_places=3, default=0)
    reduction = models.DecimalField(_("درصد تخفیف"), max_digits=18, decimal_places=3, default=0)
    discount = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    tax = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    vat = models.DecimalField(max_digits=18, decimal_places=3, default=0)

    description = models.TextField(blank=True, default="")
    short_desc = models.TextField(blank=True, default="")
    short_description_html = models.TextField(blank=True, default="")
    long_description_html = models.TextField(blank=True, default="")
    size_guide = models.TextField(blank=True, default="")

    is_active = models.BooleanField(default=True, db_index=True)
    is_saleable = models.BooleanField(default=True)
    show_torob = models.BooleanField(default=False)
    show_snapp = models.BooleanField(default=False)
    shipping_time = models.IntegerField(null=True, blank=True)
    sales_count = models.IntegerField(default=0)
    view_count = models.IntegerField(default=0)
    buyer_score_average = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    overall_score_average = models.DecimalField(max_digits=10, decimal_places=3, default=0)

    product_category_title = models.CharField(max_length=255, blank=True, default="")
    product_gender_title = models.CharField(max_length=255, blank=True, default="")
    product_season_title = models.CharField(max_length=255, blank=True, default="")
    product_style_title = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = _("محصول سایت")
        verbose_name_plural = _("محصولات سایت")

    def __str__(self):
        return self.title


class ProductTag(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="tag_links")
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, related_name="product_links")

    class Meta:
        verbose_name = _("برچسب محصول")
        verbose_name_plural = _("برچسب‌های محصول")

    def __str__(self) -> str:
        return f"{self.product_id} ← {self.tag_id}"


class ProductVariant(LegacyMixin):
    """One color/size combination of a product (one barcode)."""

    id = models.BigAutoField(primary_key=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    barcode = models.CharField(max_length=64, blank=True, default="", db_index=True)
    color = models.ForeignKey(FeatureValue, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    size = models.ForeignKey(FeatureValue, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    price = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    reduction = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    discount = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    legacy_qty = models.DecimalField(_("موجودی در سیستم قبلی"), max_digits=18, decimal_places=3, default=0)

    class Meta:
        verbose_name = _("تنوع محصول")
        verbose_name_plural = _("تنوع‌های محصول")

    def __str__(self) -> str:
        return f"{self.barcode} ({self.color_id}/{self.size_id})"


class ProductAIProfile(models.Model):
    """AI product profile generated by LEBAZAI (display_copy, SEO metadata, FAB, style tags)."""

    id = models.BigAutoField(primary_key=True)
    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name="ai_profile", verbose_name=_("محصول متناظر"))
    subcode = models.CharField(_("کد فرعی (subcode / بارکد)"), max_length=64, blank=True, default="", db_index=True)

    title = models.CharField(_("عنوان هوش مصنوعی"), max_length=512, blank=True, default="")
    seo_title = models.CharField(_("عنوان سئو"), max_length=512, blank=True, default="")
    description = models.TextField(_("توضیحات هوش مصنوعی"), blank=True, default="")
    summary_bullets = models.JSONField(_("بولت‌های خلاصه"), default=list, blank=True)
    fab = models.TextField(_("متن FAB"), blank=True, default="")
    meta_description = models.TextField(_("توضیحات متای سئو"), blank=True, default="")
    search_keywords = models.JSONField(_("کلمات کلیدی جستجو"), default=list, blank=True)
    stylist_note = models.TextField(_("یادداشت استایلیست"), blank=True, default="")
    tags = models.JSONField(_("برچسب‌ها و مشخصات سبک"), default=list, blank=True)
    attributes = models.JSONField(_("ویژگی‌های فنی سبک"), default=dict, blank=True)

    model_name = models.CharField(_("نام مدل هوش مصنوعی"), max_length=64, blank=True, default="")
    prompt_version = models.CharField(_("نسخه پرامپت"), max_length=16, blank=True, default="")
    source = models.CharField(_("منبع متادیتا"), max_length=32, blank=True, default="ai")
    ai_updated_at = models.DateTimeField(_("تاریخ به‌روزرسانی در مدل"), null=True, blank=True)
    synced_at = models.DateTimeField(_("تاریخ آخرین همگام‌سازی"), auto_now=True)

    class Meta:
        verbose_name = _("پروفایل هوش مصنوعی محصول")
        verbose_name_plural = _("پروفایل‌های هوش مصنوعی محصولات")

    def __str__(self) -> str:
        return f"{self.subcode}: {self.title or self.product.title}"


class ProductColorMedia(LegacyMixin):
    """A product's gallery for one color (legacy FeatureValueMedias)."""

    id = models.BigAutoField(primary_key=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="color_medias")
    feature_value = models.ForeignKey(FeatureValue, on_delete=models.CASCADE, related_name="+")

    class Meta:
        verbose_name = _("گالری رنگ")
        verbose_name_plural = _("گالری‌های رنگ")

    def __str__(self) -> str:
        return f"{self.product_id} / {self.feature_value_id}"


class MediaAttachment(LegacyMixin):
    """Image/video attached to any record (generic, as in the legacy schema)."""

    class Table(models.IntegerChoices):
        COLLECTIONS = 12, "Collections"
        PRODUCTS = 14, "Products"
        OUTFITS = 19, "Outfits"
        FEATURE_VALUE_MEDIAS = 27, "FeatureValueMedias"
        ARTICLES = 32, "Articles"
        CATEGORIES = 38, "Categories"
        MEDIA_ATTACHMENTS = 45, "MediaAttachments"
        COMPANY_INFOS = 46, "CompanyInfos"
        COOPERATION_REQUESTS = 100, "CooperationRequests"

    id = models.BigAutoField(primary_key=True)
    table = models.IntegerField(choices=Table.choices, db_index=True)
    record_id = models.BigIntegerField(db_index=True)
    media_url = models.CharField(max_length=1024)
    is_video = models.BooleanField(default=False)
    alternative = models.CharField(max_length=512, blank=True, default="")
    tooltip_title = models.CharField(max_length=512, blank=True, default="")
    hash_code = models.CharField(max_length=255, blank=True, default="")
    is_product_guid = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("مدیای الصاقی")
        verbose_name_plural = _("مدیاهای الصاقی")
        indexes = [models.Index(fields=["table", "record_id"])]

    def __str__(self) -> str:
        return self.media_url


class FileFormat(LegacyMixin):
    """File types the gallery accepts (FileFormats)."""

    id = models.BigAutoField(primary_key=True)
    type = models.CharField(max_length=64)          # Image, Video, ...
    extension = models.CharField(max_length=32)     # jpg, webp, mp4, ...
    mime_type = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        verbose_name = _("فرمت فایل")
        verbose_name_plural = _("فرمت‌های فایل")

    def __str__(self) -> str:
        return self.extension


class FileTag(LegacyMixin):
    """A gallery tag (separate from product/category tags)."""

    id = models.BigAutoField(primary_key=True)
    title = models.CharField(max_length=255)

    class Meta:
        verbose_name = _("تگ گالری")
        verbose_name_plural = _("تگ‌های گالری")

    def __str__(self) -> str:
        return self.title


class FileMedia(LegacyMixin):
    """Uploaded file in the admin media gallery."""

    id = models.BigAutoField(primary_key=True)
    file_name = models.CharField(max_length=512, blank=True, default="")
    url = models.CharField(max_length=1024)
    format_id = models.IntegerField(null=True, blank=True)
    upload_time = models.DateTimeField(null=True, blank=True)
    content_hash = models.CharField(max_length=255, blank=True, default="")
    domain = models.CharField(max_length=255, blank=True, default="")
    size = models.BigIntegerField(null=True, blank=True)
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)
    used = models.BooleanField(default=False)
    favorite = models.BooleanField(default=False)
    alternative = models.CharField(max_length=512, blank=True, default="")
    tooltip_title = models.CharField(max_length=512, blank=True, default="")

    class Meta:
        verbose_name = _("فایل گالری")
        verbose_name_plural = _("گالری فایل‌ها")

    def __str__(self) -> str:
        return self.file_name or self.url


class ProductSamianLink(models.Model):
    """Which Samian productmain a website product corresponds to."""

    class Method(models.TextChoices):
        EXACT_CODE = "exact_code", _("کد کالا یکسان")
        MANUAL = "manual", _("دستی")
        AUTO = "auto", _("ساخته‌شده از کالای سامیان")

    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name="samian_link")
    samian_product_id = models.BigIntegerField(_("productmain_id سامیان"), db_index=True)
    method = models.CharField(max_length=32, choices=Method.choices)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("اتصال محصول به سامیان")
        verbose_name_plural = _("اتصال محصولات به سامیان")

    def __str__(self) -> str:
        return f"{self.product_id} → {self.samian_product_id}"


# -----------------------------------------------------------------------------
# Merchandising and content
# -----------------------------------------------------------------------------
class PrimaryConfig(LegacyMixin):
    """Admin-editable JSON configs (sortRowsConfig, footerConfig, websiteMetaData, ...)."""

    id = models.BigAutoField(primary_key=True)
    key = models.CharField(max_length=128, unique=True)
    value = models.TextField(_("مقدار (JSON)"), blank=True, default="")

    class Meta:
        verbose_name = _("پیکربندی")
        verbose_name_plural = _("پیکربندی‌ها")

    def __str__(self):
        return self.key


class Banner(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    media_url = models.CharField(max_length=1024)
    link = models.CharField(max_length=1024, blank=True, default="")
    is_active = models.BooleanField(default=True)
    is_banner = models.BooleanField(default=True)
    display_priority = models.IntegerField(default=0)

    class Meta:
        verbose_name = _("بنر")
        verbose_name_plural = _("بنرها")
        ordering = ["display_priority", "id"]

    def __str__(self) -> str:
        return self.link or self.media_url


class Collection(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    title = models.CharField(max_length=255)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")
    in_main_page = models.BooleanField(default=False)
    display_priority = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    beginning_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    reduction = models.DecimalField(max_digits=18, decimal_places=3, default=0)

    class Meta:
        verbose_name = _("کالکشن")
        verbose_name_plural = _("کالکشن‌ها")

    def __str__(self) -> str:
        return self.title


class CollectionCategory(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    collection = models.ForeignKey(Collection, on_delete=models.CASCADE, related_name="category_links")
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="collection_links")

    class Meta:
        verbose_name = _("دسته‌ی کالکشن")
        verbose_name_plural = _("دسته‌های کالکشن")

    def __str__(self) -> str:
        return f"{self.collection_id} / {self.category_id}"


class ProductCollection(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    collection = models.ForeignKey(Collection, on_delete=models.CASCADE, related_name="product_links")
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.CASCADE, related_name="collection_links")
    brand = models.ForeignKey(Brand, null=True, blank=True, on_delete=models.CASCADE, related_name="collection_links")

    class Meta:
        verbose_name = _("محصول کالکشن")
        verbose_name_plural = _("محصولات کالکشن")

    def __str__(self) -> str:
        return f"{self.collection_id} / {self.product_id}"


class Outfit(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    title = models.CharField(max_length=255)
    label_title = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="outfits")
    is_active = models.BooleanField(default=True)
    start_date = models.DateTimeField(null=True, blank=True)
    expiration_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("استایل")
        verbose_name_plural = _("استایل‌ها")

    def __str__(self) -> str:
        return self.title


class OutfitProduct(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    outfit = models.ForeignKey(Outfit, on_delete=models.CASCADE, related_name="product_links")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="outfit_links")
    feature_value = models.ForeignKey(FeatureValue, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = _("محصول استایل")
        verbose_name_plural = _("محصولات استایل")

    def __str__(self) -> str:
        return f"{self.outfit_id} / {self.product_id}"


class FileMediaTag(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    file_media = models.ForeignKey(FileMedia, on_delete=models.CASCADE, related_name="tag_links")
    tag = models.ForeignKey(FileTag, on_delete=models.CASCADE, related_name="file_links")

    class Meta:
        verbose_name = _("تگ فایل")
        verbose_name_plural = _("تگ‌های فایل")

    def __str__(self) -> str:
        return f"{self.file_media_id} ← {self.tag_id}"


class SelectedProduct(LegacyMixin):
    """Products picked by the admin for the home page slider."""

    id = models.BigAutoField(primary_key=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="selections")
    feature_value = models.ForeignKey(FeatureValue, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    # The color shown first: a Samian colorinfo id (feature_value is the Dadehfa color of imported rows).
    color_id = models.BigIntegerField(null=True, blank=True)
    sorting_weight = models.DecimalField(max_digits=18, decimal_places=3, default=0)

    class Meta:
        verbose_name = _("محصول منتخب")
        verbose_name_plural = _("محصولات منتخب")
        ordering = ["-sorting_weight", "id"]

    def __str__(self) -> str:
        return f"{self.product} ({self.sorting_weight})"


class ProductComment(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="comments")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies")
    # Customers are migrated in a later phase; keep the legacy id until then.
    commenter_id = models.BigIntegerField(null=True, blank=True)
    feature_value = models.ForeignKey(FeatureValue, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    invoice_id = models.BigIntegerField(null=True, blank=True)
    title = models.CharField(max_length=512, blank=True, default="")
    comment = models.TextField(blank=True, default="")
    score = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    is_admin_comment = models.BooleanField(default=False)
    is_buyer = models.BooleanField(default=False)
    is_anonymous = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)
    status = models.IntegerField(default=0)
    status_description = models.TextField(blank=True, default="")
    verified_by_user_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = _("نظر محصول")
        verbose_name_plural = _("نظرات محصولات")

    def __str__(self) -> str:
        return self.title or self.comment[:50]


class ProductCommentLike(LegacyMixin):
    """A customer's like (liked) or dislike (not liked) of a product comment; undoing it soft-deletes the row."""

    id = models.BigAutoField(primary_key=True)
    comment = models.ForeignKey(ProductComment, on_delete=models.CASCADE, related_name="likes")
    customer_id = models.BigIntegerField(db_index=True)
    liked = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("واکنش به نظر")
        verbose_name_plural = _("واکنش‌ها به نظرها")


class ThirdPartyLog(LegacyMixin):
    """A visit that arrived from a third party (Torob) to a product page."""

    id = models.BigAutoField(primary_key=True)
    third_party_name = models.CharField(max_length=128, blank=True, default="")
    redirect_url = models.TextField(blank=True, default="")
    ip_address = models.CharField(max_length=64, blank=True, default="")
    user_agent = models.TextField(blank=True, default="")
    user_id = models.BigIntegerField(null=True, blank=True)
    product_variant_id = models.BigIntegerField(null=True, blank=True)
    price_before_reduction = models.BigIntegerField(null=True, blank=True)
    reduction = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    image_link = models.TextField(blank=True, default="")
    action_time = models.DateTimeField(auto_now_add=True, db_index=True)
    utm_source = models.CharField(max_length=255, blank=True, default="")
    utm_medium = models.CharField(max_length=255, blank=True, default="")
    utm_campaign = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = _("لاگ ورود از سایت‌های دیگر")
        verbose_name_plural = _("لاگ‌های ورود از سایت‌های دیگر")


class Redirect(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    source_url = models.CharField(max_length=1024, db_index=True)
    destination_url = models.CharField(max_length=1024)
    permanent = models.BooleanField(default=True)
    title = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("ریدایرکت")
        verbose_name_plural = _("ریدایرکت‌ها")

    def __str__(self) -> str:
        return f"{self.source_url} → {self.destination_url}"


# -----------------------------------------------------------------------------
# Site settings, company, themes
# -----------------------------------------------------------------------------
class CompanyInfo(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    address = models.TextField(blank=True, default="")
    postal_code = models.CharField(max_length=32, blank=True, default="")
    phone_numbers = models.TextField(blank=True, default="")
    website_logo_address = models.CharField(max_length=1024, blank=True, default="")
    keywords = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = _("اطلاعات شرکت")
        verbose_name_plural = _("اطلاعات شرکت")

    def __str__(self) -> str:
        return self.name


class CompanyBranch(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=255)
    address = models.TextField(blank=True, default="")
    phone = models.CharField(max_length=128, blank=True, default="")
    province_id = models.BigIntegerField(null=True, blank=True)
    province_title = models.CharField(max_length=128, blank=True, default="")
    city_id = models.BigIntegerField(null=True, blank=True)
    city_title = models.CharField(max_length=128, blank=True, default="")
    zip_code = models.CharField(max_length=32, blank=True, default="")
    latitude = models.DecimalField(max_digits=18, decimal_places=10, null=True, blank=True)
    longitude = models.DecimalField(max_digits=18, decimal_places=10, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("شعبه")
        verbose_name_plural = _("شعب")

    def __str__(self) -> str:
        return self.name


class SiteSetting(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    website_title = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    is_payment = models.BooleanField(default=True)
    payment_bank = models.IntegerField(null=True, blank=True)
    online_branch_id = models.IntegerField(null=True, blank=True)
    default_sms_panel_id = models.IntegerField(null=True, blank=True)
    has_connection_with_snapp_express = models.BooleanField(default=False)
    has_connection_with_snapp_pay = models.BooleanField(default=False)
    has_connection_with_torob = models.BooleanField(default=False)
    show_all_category = models.BooleanField(default=False)
    default_theme_id = models.IntegerField(null=True, blank=True)
    is_custom_theme = models.BooleanField(default=False)
    has_bulletin = models.BooleanField(default=False)
    has_cooperation = models.BooleanField(default=False)
    min_qty = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    only_has_media_products = models.BooleanField(default=False)
    coupon_calculation_type = models.IntegerField(null=True, blank=True)
    gift_card_use_type = models.IntegerField(null=True, blank=True)

    class Meta:
        verbose_name = _("تنظیمات سایت")
        verbose_name_plural = _("تنظیمات سایت")

    def __str__(self) -> str:
        return self.website_title or f"تنظیمات {self.id}"


class ThemeBase(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    lable_title = models.CharField(max_length=255, blank=True, default="")
    category_count = models.IntegerField(null=True, blank=True)
    description = models.TextField(blank=True, default="")
    mobile_image = models.CharField(max_length=1024, blank=True, default="")
    header_image = models.CharField(max_length=1024, blank=True, default="")
    desktop_image = models.CharField(max_length=1024, blank=True, default="")
    is_editable = models.BooleanField(default=False)
    white_color = models.CharField(max_length=32, blank=True, default="")
    white_hover_color = models.CharField(max_length=32, blank=True, default="")
    primary1_color = models.CharField(max_length=32, blank=True, default="")
    primary2_color = models.CharField(max_length=32, blank=True, default="")
    secondary_color = models.CharField(max_length=32, blank=True, default="")
    border_color = models.CharField(max_length=32, blank=True, default="")
    cta_color = models.CharField(max_length=32, blank=True, default="")
    cta_hover_color = models.CharField(max_length=32, blank=True, default="")
    cta_disabled_color = models.CharField(max_length=32, blank=True, default="")
    focus_color = models.CharField(max_length=32, blank=True, default="")
    highlight_color = models.CharField(max_length=32, blank=True, default="")
    alert_color = models.CharField(max_length=32, blank=True, default="")

    class Meta:
        abstract = True


class Theme(ThemeBase):
    theme_name = models.CharField(max_length=255)

    class Meta:
        verbose_name = _("قالب")
        verbose_name_plural = _("قالب‌ها")

    def __str__(self) -> str:
        return self.lable_title or self.theme_name


class CustomTheme(ThemeBase):
    custom_theme_name = models.CharField(max_length=255)

    class Meta:
        verbose_name = _("قالب سفارشی")
        verbose_name_plural = _("قالب‌های سفارشی")

    def __str__(self) -> str:
        return self.lable_title or self.custom_theme_name


class Page(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=255)
    key = models.CharField(max_length=255, blank=True, default="")
    type = models.CharField(max_length=128, blank=True, default="")
    image_url = models.CharField(max_length=1024, blank=True, default="")
    is_landing_page = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("صفحه‌ی قالب")
        verbose_name_plural = _("صفحه‌های قالب")

    def __str__(self) -> str:
        return f"{self.name} ({self.type})"


class ThemePage(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    theme = models.ForeignKey(Theme, on_delete=models.CASCADE, related_name="page_links")
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name="theme_links")

    class Meta:
        verbose_name = _("صفحه‌ی قالب")
        verbose_name_plural = _("صفحه‌های قالب")

    def __str__(self) -> str:
        return f"{self.theme_id} / {self.page_id}"


class CustomThemePage(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    custom_theme = models.ForeignKey(CustomTheme, on_delete=models.CASCADE, related_name="page_links")
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name="custom_theme_links")

    class Meta:
        verbose_name = _("صفحه‌ی قالب سفارشی")
        verbose_name_plural = _("صفحه‌های قالب سفارشی")

    def __str__(self) -> str:
        return f"{self.custom_theme_id} / {self.page_id}"


# -----------------------------------------------------------------------------
# Shipping and locations
# -----------------------------------------------------------------------------
class Province(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=128)
    country_id = models.IntegerField(null=True, blank=True)
    latitude = models.DecimalField(max_digits=18, decimal_places=10, null=True, blank=True)
    longitude = models.DecimalField(max_digits=18, decimal_places=10, null=True, blank=True)

    class Meta:
        verbose_name = _("استان")
        verbose_name_plural = _("استان‌ها")

    def __str__(self) -> str:
        return self.name


class City(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    province = models.ForeignKey(Province, on_delete=models.CASCADE, related_name="cities")
    name = models.CharField(max_length=128)
    latitude = models.DecimalField(max_digits=18, decimal_places=10, null=True, blank=True)
    longitude = models.DecimalField(max_digits=18, decimal_places=10, null=True, blank=True)

    class Meta:
        verbose_name = _("شهر")
        verbose_name_plural = _("شهرها")

    def __str__(self) -> str:
        return self.name


class ShippingMethodType(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=255)
    key = models.CharField(max_length=128, blank=True, default="")
    include_costs = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("نوع روش ارسال")
        verbose_name_plural = _("انواع روش ارسال")

    def __str__(self) -> str:
        return self.name


class ShippingMethod(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=255)
    type = models.ForeignKey(ShippingMethodType, null=True, blank=True, on_delete=models.SET_NULL, related_name="methods")
    description = models.TextField(blank=True, default="")
    icon = models.CharField(max_length=1024, blank=True, default="")
    fixed_cost = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    variable_fee = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    is_dynamic_pricing = models.BooleanField(default=False)
    requires_insurance = models.BooleanField(default=False)
    insurance_cost = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    insurance_percentage = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    tax_percentage = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    source_dependent = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("روش ارسال")
        verbose_name_plural = _("روش‌های ارسال")

    def __str__(self) -> str:
        return self.name


class ShippingMethodLocation(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    shipping_method = models.ForeignKey(ShippingMethod, on_delete=models.CASCADE, related_name="locations")
    province_id = models.BigIntegerField(null=True, blank=True)
    city_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = _("محدوده‌ی روش ارسال")
        verbose_name_plural = _("محدوده‌های روش ارسال")

    def __str__(self) -> str:
        return f"{self.province_id}/{self.city_id}"


# -----------------------------------------------------------------------------
# Branches (ours: edited in the admin, never imported)
# -----------------------------------------------------------------------------
class Branch(models.Model):
    """
    A shop on the branches page and, when sells_online, a warehouse whose stock
    is offered on the site. Seeded once from the businessDepartments config
    (seed_branches); from then on this table is the source and the config's
    departmentList is generated from it.
    """

    title = models.CharField(_("عنوان"), max_length=255)
    address = models.TextField(_("آدرس"), blank=True, default="")
    phones = models.TextField(_("تلفن‌ها"), blank=True, default="", help_text=_("هر شماره در یک خط"))
    latitude = models.FloatField(_("عرض جغرافیایی"), null=True, blank=True)
    longitude = models.FloatField(_("طول جغرافیایی"), null=True, blank=True)
    warehouse = models.ForeignKey(
        "samian.SamianWarehouse", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="branches", verbose_name=_("انبار سامیان"),
    )
    show_on_site = models.BooleanField(_("نمایش در صفحه‌ی شعب"), default=True)
    sells_online = models.BooleanField(
        _("موجودی در فروش آنلاین"), default=False,
        help_text=_("موجودی انبار این شعبه در سایت قابل خرید است"),
    )
    display_order = models.PositiveIntegerField(_("ترتیب نمایش"), default=0)
    front_id = models.BigIntegerField(_("شناسه در فرانت"), null=True, blank=True, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("شعبه")
        verbose_name_plural = _("شعبه‌ها")
        ordering = ("display_order", "id")

    def __str__(self) -> str:
        return self.title

    def phone_list(self) -> list[str]:
        return [p.strip() for p in self.phones.splitlines() if p.strip()]

    def as_department(self) -> dict:
        """One item of businessDepartments.departmentList, as the frontend reads it."""
        return {
            "depTitle": self.title,
            "address": self.address,
            "location": {"lat": self.latitude, "lng": self.longitude},
            "phoneNumbers": [{"phoneNumber": p} for p in self.phone_list()],
            "id": self.front_id or self.id,
        }


def online_warehouse_ids() -> list[int]:
    """Samian warehouses whose stock is sold online: branches marked sells_online, else the setting."""
    from django.conf import settings

    ids = list(
        Branch.objects.filter(sells_online=True, warehouse__isnull=False)
        .values_list("warehouse__samian_id", flat=True)
        .distinct()
    )
    return ids or list(settings.STOREFRONT_STOCK_WAREHOUSE_IDS)


# -----------------------------------------------------------------------------
# Customers
# -----------------------------------------------------------------------------
# Site accounts. Name, national code, birth date and addresses that Samian also
# keeps are read from Samian (samian.SamianCustomer, SamianCustomerAddress) and
# linked by mobile; what Samian does not have (favorites, newsletter, site
# addresses with map points) lives here. Legacy ids are kept so imported
# favorites and addresses stay attached.
class Job(LegacyMixin):
    """Occupations a customer can pick in their profile."""

    id = models.BigAutoField(primary_key=True)
    title = models.CharField(_("عنوان"), max_length=255)

    class Meta:
        verbose_name = _("شغل")
        verbose_name_plural = _("شغل‌ها")
        ordering = ("id",)

    def __str__(self) -> str:
        return self.title


class Customer(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    first_name = models.CharField(_("نام"), max_length=150, blank=True, default="")
    last_name = models.CharField(_("نام خانوادگی"), max_length=150, blank=True, default="")
    cellphone = models.CharField(_("موبایل"), max_length=20, unique=True)
    email = models.CharField(_("ایمیل"), max_length=254, blank=True, default="")
    national_code = models.CharField(_("کد ملی"), max_length=32, blank=True, default="")
    birth_date = models.DateField(_("تاریخ تولد"), null=True, blank=True)
    job_id = models.IntegerField(_("شغل"), null=True, blank=True)
    is_active = models.BooleanField(_("فعال"), default=True)
    is_bulletin_enabled = models.BooleanField(_("عضو خبرنامه"), default=False)
    bulletin_subscription_date = models.DateTimeField(_("تاریخ عضویت خبرنامه"), null=True, blank=True)
    samian_customer = models.ForeignKey(
        "samian.SamianCustomer", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="site_customers", verbose_name=_("مشتری سامیان"),
    )
    samian_checked_at = models.DateTimeField(_("آخرین جستجو در سامیان"), null=True, blank=True)
    # A Django password hash; empty until the customer sets one (sign-in is by SMS code otherwise).
    # Dadehfa's own hashes were not carried over.
    password = models.CharField(_("رمز عبور"), max_length=256, blank=True, default="")

    class Meta:
        verbose_name = _("مشتری سایت")
        verbose_name_plural = _("مشتریان سایت")
        ordering = ("-id",)

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name} ({self.cellphone})".strip()

    def set_password(self, raw: str) -> None:
        from django.contrib.auth.hashers import make_password
        self.password = make_password(raw)

    def check_password(self, raw: str) -> bool:
        from django.contrib.auth.hashers import check_password
        return bool(self.password) and check_password(raw, self.password)


class CustomerOtp(models.Model):
    """A sign-in code sent to a mobile by SMS (also before the customer has an account). Only its hash is stored."""

    cellphone = models.CharField(max_length=20, db_index=True)
    code_hash = models.CharField(max_length=256)
    created = models.DateTimeField(auto_now_add=True)
    expires = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("کد ورود مشتری")
        verbose_name_plural = _("کدهای ورود مشتری")
        ordering = ("-created",)


class CustomerAddress(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="addresses")
    title = models.CharField(_("عنوان"), max_length=255, blank=True, default="")
    is_default = models.BooleanField(_("پیش‌فرض"), default=False)
    address = models.TextField(_("آدرس"), blank=True, default="")
    # No db constraint: import_dadehfa refreshes provinces and products by
    # deleting and re-inserting them with the same ids.
    province = models.ForeignKey(
        Province, null=True, blank=True, on_delete=models.DO_NOTHING, db_constraint=False, related_name="+"
    )
    city = models.ForeignKey(City, null=True, blank=True, on_delete=models.DO_NOTHING, db_constraint=False, related_name="+")
    zip_code = models.CharField(_("کد پستی"), max_length=32, blank=True, default="")
    latitude = models.DecimalField(max_digits=18, decimal_places=10, null=True, blank=True)
    longitude = models.DecimalField(max_digits=18, decimal_places=10, null=True, blank=True)
    first_name = models.CharField(_("نام گیرنده"), max_length=150, blank=True, default="")
    last_name = models.CharField(_("نام خانوادگی گیرنده"), max_length=150, blank=True, default="")
    mobile = models.CharField(_("موبایل گیرنده"), max_length=20, blank=True, default="")
    is_myself_recipient = models.BooleanField(_("گیرنده خودم هستم"), default=True)
    # Samian contactinfo row this address was written to (set by the order flow).
    samian_contact_id = models.BigIntegerField(_("شناسه آدرس در سامیان"), null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = _("آدرس مشتری سایت")
        verbose_name_plural = _("آدرس‌های مشتریان سایت")

    def __str__(self) -> str:
        return self.title or self.address[:50]


class CustomerFavoriteProduct(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="favorites")
    product = models.ForeignKey(Product, on_delete=models.DO_NOTHING, db_constraint=False, related_name="+")
    color_id = models.BigIntegerField(null=True, blank=True)
    size_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = _("علاقه‌مندی")
        verbose_name_plural = _("علاقه‌مندی‌ها")


    def __str__(self) -> str:
        return f"{self.customer_id} ♥ {self.product_id}"

class HiddenImage(models.Model):
    """
    A Samian photo the admin chose not to show on the site (bad shot, wrong
    color...). Keyed like the built images (images.samian_key), so it stays
    hidden however often the gallery is synced.
    """

    key = models.CharField(max_length=255, unique=True)
    hidden_by = models.CharField(_("پنهان‌شده توسط"), max_length=150, blank=True, default="")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("عکس پنهان")
        verbose_name_plural = _("عکس‌های پنهان")

    def __str__(self) -> str:
        return self.key


class CooperationRequest(LegacyMixin):
    """A job application sent from the cooperation page; the resume is a MediaAttachment (table 100)."""

    class State(models.IntegerChoices):
        NEW = 0, _("جدید")
        SEEN = 1, _("مشاهده شده")
        PICK = 2, _("باز شده")
        IN_PROGRESS = 3, _("در حال بررسی")
        ACCEPT = 4, _("پذیرفته شده")
        REJECT = 5, _("رد شده")

    id = models.BigAutoField(primary_key=True)
    first_name = models.CharField(_("نام"), max_length=150, blank=True, default="")
    last_name = models.CharField(_("نام خانوادگی"), max_length=150, blank=True, default="")
    cellphone = models.CharField(_("موبایل"), max_length=20, blank=True, default="")
    email = models.CharField(_("ایمیل"), max_length=254, blank=True, default="")
    address = models.TextField(_("آدرس"), blank=True, default="")
    additional_info = models.TextField(_("توضیحات"), blank=True, default="")
    job_position_title = models.CharField(_("موقعیت شغلی"), max_length=255, blank=True, default="")
    state = models.IntegerField(_("وضعیت"), choices=State.choices, default=State.NEW)
    reason = models.TextField(_("یادداشت‌ها"), blank=True, default="")
    last_time_action = models.DateTimeField(_("آخرین اقدام"), null=True, blank=True)

    class Meta:
        verbose_name = _("درخواست همکاری")
        verbose_name_plural = _("درخواست‌های همکاری")
        ordering = ("-id",)

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name} ({self.job_position_title})".strip()


# -----------------------------------------------------------------------------
# Blog
# -----------------------------------------------------------------------------
class BlogCategory(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    title = models.CharField(_("عنوان"), max_length=255)
    in_main_page = models.BooleanField(_("در صفحه اصلی"), default=False)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")

    class Meta:
        verbose_name = _("دسته‌ی بلاگ")
        verbose_name_plural = _("دسته‌های بلاگ")
        ordering = ("id",)

    def __str__(self) -> str:
        return self.title


class ArticleTag(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(_("نام"), max_length=255)

    class Meta:
        verbose_name = _("تگ بلاگ")
        verbose_name_plural = _("تگ‌های بلاگ")
        ordering = ("id",)

    def __str__(self) -> str:
        return self.name


class Article(LegacyMixin):
    """A blog post. On the site while show_on_page, published and not expired."""

    id = models.BigAutoField(primary_key=True)
    title = models.CharField(_("عنوان"), max_length=512)
    content = models.TextField(_("متن (HTML)"), blank=True, default="")
    description = models.TextField(_("خلاصه"), blank=True, default="")
    thumbnail = models.CharField(_("تصویر شاخص"), max_length=1024, blank=True, default="")
    uniq_url = models.CharField(_("آدرس یکتا"), max_length=512, unique=True)
    author_id = models.BigIntegerField(_("نویسنده (کاربر ادمین)"), null=True, blank=True)
    publish_date = models.DateTimeField(_("تاریخ انتشار"), null=True, blank=True)
    expiration_date = models.DateTimeField(_("تاریخ انقضا"), null=True, blank=True)
    show_on_page = models.BooleanField(_("نمایش در سایت"), default=True)
    view_count = models.IntegerField(_("بازدید"), default=0)
    categories = models.ManyToManyField(BlogCategory, through="ArticleBlogCategory", related_name="articles")
    tags = models.ManyToManyField(ArticleTag, through="ArticleTagRelation", related_name="articles")

    class Meta:
        verbose_name = _("مقاله")
        verbose_name_plural = _("مقاله‌ها")
        ordering = ("-id",)

    def __str__(self) -> str:
        return self.title


class ArticleBlogCategory(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="category_links")
    category = models.ForeignKey(BlogCategory, on_delete=models.CASCADE, related_name="article_links")

    class Meta:
        verbose_name = _("دسته‌ی مقاله")
        verbose_name_plural = _("دسته‌های مقاله")

    def __str__(self) -> str:
        return f"{self.article_id} / {self.category_id}"


class ArticleTagRelation(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="tag_links")
    tag = models.ForeignKey(ArticleTag, on_delete=models.CASCADE, related_name="article_links")

    class Meta:
        verbose_name = _("تگ مقاله")
        verbose_name_plural = _("تگ‌های مقاله")

    def __str__(self) -> str:
        return f"{self.article_id} / {self.tag_id}"


class ArticleComment(LegacyMixin):
    """Statuses as product comments: 0 pending, 1 approved, 2 rejected, 3 viewed."""

    id = models.BigAutoField(primary_key=True)
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="comments")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies")
    commenter_id = models.BigIntegerField(null=True, blank=True)
    title = models.CharField(max_length=512, blank=True, default="")
    comment = models.TextField(blank=True, default="")
    score = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    is_admin_comment = models.BooleanField(default=False)
    is_buyer = models.BooleanField(default=False)
    is_anonymous = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)
    status = models.IntegerField(default=0)
    status_description = models.TextField(blank=True, default="")
    verified_by_user_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = _("نظر مقاله")
        verbose_name_plural = _("نظرات مقاله‌ها")

    def __str__(self) -> str:
        return self.title or self.comment[:50]


class ArticleLike(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="likes")
    customer_id = models.BigIntegerField(null=True, blank=True)
    liked = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("پسند مقاله")
        verbose_name_plural = _("پسندهای مقاله")

    def __str__(self) -> str:
        return f"{self.article_id} / {self.customer_id}"


# -----------------------------------------------------------------------------
# Site orders (cart -> pre-invoice -> paid). Sending a paid order to Samian is
# the write phase; until then samian_transaction_id stays empty.
# -----------------------------------------------------------------------------
class Invoice(models.Model):
    class State(models.IntegerChoices):
        PRE_INVOICE = 1, _("پیش‌فاکتور")
        SUSPENDED = 2, _("معلق")
        SUCCESSFUL = 3, _("موفق")
        CANCELLED = 4, _("لغو شده")

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="invoices", verbose_name=_("مشتری"))
    state = models.IntegerField(_("وضعیت"), choices=State.choices, default=State.PRE_INVOICE, db_index=True)
    shipping_method = models.ForeignKey(ShippingMethod, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                                        verbose_name=_("روش ارسال"))
    address = models.ForeignKey("CustomerAddress", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                                verbose_name=_("آدرس"))
    recipient_name = models.CharField(_("نام گیرنده"), max_length=255, blank=True, default="")
    recipient_mobile = models.CharField(_("موبایل گیرنده"), max_length=20, blank=True, default="")
    full_address = models.TextField(_("نشانی کامل"), blank=True, default="")
    postal_code = models.CharField(_("کد پستی"), max_length=32, blank=True, default="")
    province_name = models.CharField(_("استان"), max_length=128, blank=True, default="")
    city_name = models.CharField(_("شهر"), max_length=128, blank=True, default="")
    amount = models.BigIntegerField(_("مبلغ کل (ریال)"), default=0)
    reduction_amount = models.BigIntegerField(_("تخفیف کالاها (ریال)"), default=0)
    delivery_amount = models.BigIntegerField(_("هزینه ارسال (ریال)"), default=0)
    deduction_amount = models.BigIntegerField(_("کسر کارت هدیه یا کوپن (ریال)"), default=0)
    payable_amount = models.BigIntegerField(_("قابل پرداخت (ریال)"), default=0)
    description = models.TextField(_("توضیحات"), blank=True, default="")
    gift_card_number = models.CharField(_("کارت هدیه"), max_length=100, blank=True, default="")
    coupon_serial = models.CharField(_("کوپن"), max_length=250, blank=True, default="")
    paid_at = models.DateTimeField(_("زمان پرداخت"), null=True, blank=True)
    # Given when paid: Persian year (3 digits) + month + a sequence from 101 in that month, e.g. 40508101.
    number = models.CharField(_("شماره فاکتور"), max_length=20, null=True, blank=True, unique=True)
    samian_transaction_id = models.BigIntegerField(_("شناسه رسید در سامیان"), null=True, blank=True, db_index=True)
    is_deleted = models.BooleanField(_("حذف شده"), default=False, db_index=True)
    created = models.DateTimeField(_("ایجاد"), auto_now_add=True)
    last_modified = models.DateTimeField(_("آخرین تغییر"), auto_now=True)

    class Meta:
        verbose_name = _("سفارش سایت")
        verbose_name_plural = _("سفارش‌های سایت")
        ordering = ("-id",)

    def __str__(self) -> str:
        return f"#{self.number or self.id} {self.customer_id} ({self.get_state_display()})"


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.DO_NOTHING, db_constraint=False, related_name="+")
    variant_id = models.BigIntegerField(_("شناسه بارکد سامیان (productVariantId)"))
    barcode = models.CharField(max_length=255, blank=True, default="")
    name = models.CharField(max_length=512, blank=True, default="")
    color_id = models.BigIntegerField(null=True, blank=True)
    color_name = models.CharField(max_length=128, blank=True, default="")
    color_value = models.CharField(max_length=32, blank=True, default="")
    size_name = models.CharField(max_length=64, blank=True, default="")
    qty = models.DecimalField(max_digits=12, decimal_places=2, default=1)
    price = models.BigIntegerField(_("قیمت واحد (ریال)"), default=0)
    reduction = models.DecimalField(_("درصد تخفیف"), max_digits=8, decimal_places=3, default=0)
    price_after_reduction = models.BigIntegerField(_("قیمت واحد بعد از تخفیف (ریال)"), default=0)

    class Meta:
        verbose_name = _("ردیف سفارش")
        verbose_name_plural = _("ردیف‌های سفارش")
        ordering = ("id",)


class InvoicePayment(models.Model):
    """One attempt to pay an invoice through a gateway."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="payments")
    gateway = models.CharField(max_length=32)               # zarinpal, snapppay
    amount = models.BigIntegerField(default=0)              # rial
    authority = models.CharField(max_length=255, blank=True, default="", db_index=True)   # Zarinpal authority / SnappPay payment token
    transaction_id = models.CharField(max_length=64, blank=True, default="", db_index=True)  # our id sent to the gateway (SnappPay)
    reference = models.CharField(max_length=255, blank=True, default="")  # Zarinpal ref_id / SnappPay transactionId
    card_pan = models.CharField(max_length=64, blank=True, default="")
    is_success = models.BooleanField(default=False)
    error_message = models.TextField(blank=True, default="")
    created = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("پرداخت سفارش")
        verbose_name_plural = _("پرداخت‌های سفارش")
        ordering = ("-id",)


# -----------------------------------------------------------------------------
# Payment gateways (configs page in the panel). The site offers the active ones
# it can talk to (zarinpal, snapppay).
# -----------------------------------------------------------------------------
class BankInfo(LegacyMixin):
    id = models.BigAutoField(primary_key=True)
    name = models.CharField(_("نام"), max_length=128)
    key = models.CharField(_("کلید"), max_length=64, unique=True)   # zarinpal, snapppay, saman, ...
    icon = models.TextField(_("لوگو (base64)"), blank=True, default="")

    class Meta:
        verbose_name = _("بانک / درگاه")
        verbose_name_plural = _("بانک‌ها و درگاه‌ها")
        ordering = ("id",)

    def __str__(self) -> str:
        return self.name


class BankGateway(LegacyMixin):
    """A configured gateway; is_deleted means switched off in the panel."""

    id = models.BigAutoField(primary_key=True)
    bank = models.ForeignKey(BankInfo, on_delete=models.PROTECT, related_name="gateways", verbose_name=_("بانک"))
    merchant = models.CharField(_("مرچنت"), max_length=255, blank=True, default="")
    terminal_id = models.CharField(_("ترمینال"), max_length=255, blank=True, default="")
    merchant_key = models.CharField(_("کلید مرچنت"), max_length=255, blank=True, default="")

    class Meta:
        verbose_name = _("درگاه پرداخت")
        verbose_name_plural = _("درگاه‌های پرداخت")
        ordering = ("id",)

    def __str__(self) -> str:
        return f"{self.bank.name} #{self.id}"
