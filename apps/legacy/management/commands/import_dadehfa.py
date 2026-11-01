"""
Management command: import the website layer from DadehfaOnlineShop (read only).

Every table is fully refreshed inside one transaction, in dependency order.
Legacy ids are kept as primary keys. Rows soft-deleted in the source are
imported too (with is_deleted=True) so references between tables resolve.

    python manage.py import_dadehfa                    # everything except customers
    python manage.py import_dadehfa --only catalog     # one group
    python manage.py import_dadehfa --only customers   # site accounts, addresses, favorites (explicit only)
    python manage.py import_dadehfa --only catalog --upsert   # update in place, delete nothing

--upsert updates rows and keeps everything else, which is how the Dadehfa connector
refreshes the catalog group (brands, categories, tags, features, products). Prefer it
for any run after the first: without it, products are deleted and their AI profiles go too.
"""
from __future__ import annotations

import base64
import time
from datetime import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connection, transaction
from django.utils import timezone

from apps.legacy.db import iter_rows
from apps.website import models as m

BATCH = 2000


def _s(v) -> str:
    return "" if v is None else str(v)


def _d(v) -> Decimal:
    return Decimal(0) if v is None else Decimal(v)


def _b(v) -> bool:
    return bool(v)


def _dt(v: datetime | None) -> datetime | None:
    """SQL Server uses 0001-01-01 / 9999-12-31 as empty dates; naive values are Tehran time."""
    if v is None or v.year <= 1 or v.year >= 9999:
        return None
    return timezone.make_aware(v) if timezone.is_naive(v) else v


def legacy(row: dict) -> dict:
    return {
        "map_id": _s(row.get("MapId")),
        "is_deleted": _b(row.get("IsDeleted")),
        "created": row.get("Created"),
        "last_modified": row.get("LastModified"),
    }


@dataclass
class Spec:
    model: type
    sql: str
    build: Callable[[dict], dict]
    group: str
    # field name -> model whose ids must contain the value (else nulled, or row skipped if required)
    fks: dict[str, tuple[type, bool]] = field(default_factory=dict)


# The account a row belongs to after duplicate mobiles are merged.
_OLDEST_CUSTOMER = (
    "(SELECT MIN(c2.Id) FROM Customers c1 JOIN Customers c2 ON c2.CellPhone = c1.CellPhone WHERE c1.Id = a.CustomerId)"
)

SPECS: list[Spec] = [
    # ------------------------------------------------------------------ catalog
    Spec(m.Brand, "SELECT * FROM Brands", lambda r: {
        "id": r["Id"], "title": _s(r["Title"]), "group_name": _s(r["BrandGroupName"]), **legacy(r),
    }, "catalog"),
    Spec(m.Category, "SELECT * FROM Categories1", lambda r: {
        "id": r["Id"], "parent_id": r["ParentId"], "title": _s(r["Title"]), "slug": _s(r["Slug"]),
        "has_manual_slug": _b(r["HasManualSlug"]), "group_level": r["GroupLevel"],
        "display_priority": r["DisplayPriority"] or 0, "in_main_page": _b(r["InMainPage"]),
        "is_online_active": _b(r["IsOnlineActive"]), "discount": _d(r["Discount"]),
        "short_description_html": _s(r["ShortDescriptionHtml"]), "long_description_html": _s(r["LongDescriptionHtml"]),
        "base_category_type_id": r["BaseCategoryTypeId"], "base_category_type_title": _s(r["BaseCategoryTypeTitle"]),
        "parent_map_id": _s(r["ParentMapId"]), **legacy(r),
    }, "catalog", {"parent_id": (m.Category, False)}),
    Spec(m.Tag, "SELECT * FROM Tags", lambda r: {
        "id": r["Id"], "title": _s(r["Title"]), "parent_id": r["ParentId"], **legacy(r),
    }, "catalog", {"parent_id": (m.Tag, False)}),
    Spec(m.CategoryTag, "SELECT * FROM CategoryTags", lambda r: {
        "id": r["Id"], "category_id": r["CategoryId"], "tag_id": r["TagId"], **legacy(r),
    }, "catalog", {"category_id": (m.Category, True), "tag_id": (m.Tag, True)}),
    Spec(m.Feature, "SELECT * FROM Features", lambda r: {
        "id": r["Id"], "name": _s(r["Name"]), "display_priority": r["DisplayPriority"] or 0, **legacy(r),
    }, "catalog"),
    Spec(m.FeatureValue, "SELECT * FROM FeatureValues", lambda r: {
        "id": r["Id"], "feature_id": r["FeatureId"], "name": _s(r["Name"]), "value": _s(r["Value"]),
        "display_priority": r["DisplayPriority"] or 0, **legacy(r),
    }, "catalog", {"feature_id": (m.Feature, True)}),
    Spec(m.Product, "SELECT * FROM Products", lambda r: {
        "id": r["Id"], "title": _s(r["Title"]), "slug": _s(r["Slug"]), "has_manual_slug": _b(r["HasManualSlug"]),
        "category_id": r["CategoryId"], "brand_id": r["BrandId"], "barcode": _s(r["Barcode"]).strip(),
        "price": _d(r["Price"]), "reduction": _d(r["Reduction"]), "discount": _d(r["Discount"]),
        "tax": _d(r["Tax"]), "vat": _d(r["VAT"]),
        "description": _s(r["Description"]), "short_desc": _s(r["ShortDesc"]),
        "short_description_html": _s(r["ShortDescriptionHtml"]), "long_description_html": _s(r["LongDescriptionHtml"]),
        "size_guide": _s(r["SizeGuide"]), "is_active": _b(r["IsActive"]), "is_saleable": _b(r["IsSaleable"]),
        "show_torob": _b(r["ShowTorob"]), "show_snapp": _b(r["ShowSnapp"]), "shipping_time": r["ShippingTime"],
        "sales_count": r["SalesCount"] or 0, "view_count": r["ViewCount"] or 0,
        "buyer_score_average": _d(r["BuyerScoreAverage"]), "overall_score_average": _d(r["OverallScoreAverage"]),
        "product_category_title": _s(r["ProductCategoryTitle"]), "product_gender_title": _s(r["ProductGenderTitle"]),
        "product_season_title": _s(r["ProductSeasonTitle"]), "product_style_title": _s(r["ProductStyleTitle"]),
        **legacy(r),
    }, "catalog", {"category_id": (m.Category, False), "brand_id": (m.Brand, False)}),
    Spec(m.ProductTag, "SELECT * FROM ProductTags", lambda r: {
        "id": r["Id"], "product_id": r["ProductId"], "tag_id": r["TagId"], **legacy(r),
    }, "catalog", {"product_id": (m.Product, True), "tag_id": (m.Tag, True)}),
    # ------------------------------------------------------------------ content
    # Site images only: product photos come from the sales connector, not from here.
    Spec(m.MediaAttachment, """
        SELECT * FROM MediaAttachments
        WHERE TableNameId <> 27 AND NOT (TableNameId = 14 AND IsProductGuid = 0)
    """, lambda r: {
        "id": r["Id"], "table": r["TableNameId"], "record_id": r["RecordId"], "media_url": _s(r["MediaUrl"]),
        "is_video": _b(r["IsVideo"]), "alternative": _s(r["Alternative"]), "tooltip_title": _s(r["TooltipTitle"]),
        "hash_code": _s(r["HashCode"]), "is_product_guid": _b(r["IsProductGuid"]), **legacy(r),
    }, "content"),
    Spec(m.PrimaryConfig, "SELECT * FROM PrimaryConfigs", lambda r: {
        "id": r["Id"], "key": _s(r["Key"]), "value": _s(r["Value"]), **legacy(r),
    }, "content"),
    Spec(m.Banner, "SELECT * FROM Banners", lambda r: {
        "id": r["Id"], "media_url": _s(r["MediaUrl"]), "link": _s(r["Link"]), "is_active": _b(r["IsActive"]),
        "is_banner": _b(r["IsBanner"]), "display_priority": r["DisplayPriority"] or 0, **legacy(r),
    }, "content"),
    Spec(m.Collection, "SELECT * FROM Collections", lambda r: {
        "id": r["Id"], "title": _s(r["Title"]), "parent_id": r["ParentId"], "in_main_page": _b(r["InMainPage"]),
        "display_priority": r["DisplayPriority"] or 0, "is_active": _b(r["IsActive"]),
        "beginning_date": r["BeginningDate"], "end_date": r["EndDate"], "reduction": _d(r["Reduction"]), **legacy(r),
    }, "content", {"parent_id": (m.Collection, False)}),
    Spec(m.CollectionCategory, "SELECT * FROM CollectionCategories", lambda r: {
        "id": r["Id"], "collection_id": r["CollectionId"], "category_id": r["CategoryId"], **legacy(r),
    }, "content", {"collection_id": (m.Collection, True), "category_id": (m.Category, True)}),
    Spec(m.ProductCollection, "SELECT * FROM ProductCollections", lambda r: {
        "id": r["Id"], "collection_id": r["CollectionId"], "product_id": r["ProductId"], "brand_id": r["BrandId"],
        **legacy(r),
    }, "content", {"collection_id": (m.Collection, True), "product_id": (m.Product, False), "brand_id": (m.Brand, False)}),
    Spec(m.Outfit, "SELECT * FROM Outfits", lambda r: {
        "id": r["Id"], "title": _s(r["Title"]), "label_title": _s(r["LabelTitle"]), "description": _s(r["Description"]),
        "category_id": r["CategoryId"], "is_active": _b(r["IsActive"]), "start_date": r["StartDate"],
        "expiration_date": r["ExpirationDate"], **legacy(r),
    }, "content", {"category_id": (m.Category, False)}),
    Spec(m.OutfitProduct, "SELECT * FROM OutfitProducts", lambda r: {
        "id": r["Id"], "outfit_id": r["OutfitId"], "product_id": r["ProductId"], "feature_value_id": r["FeatureValueId"],
        **legacy(r),
    }, "content", {"outfit_id": (m.Outfit, True), "product_id": (m.Product, True), "feature_value_id": (m.FeatureValue, False)}),
    Spec(m.SelectedProduct, "SELECT * FROM SelectedProducts", lambda r: {
        "id": r["Id"], "product_id": r["ProductId"], "feature_value_id": r["FeatureValueId"],
        "sorting_weight": _d(r["SortingWeight"]), **legacy(r),
    }, "content", {"product_id": (m.Product, True), "feature_value_id": (m.FeatureValue, False)}),
    Spec(m.ProductComment, "SELECT * FROM ProductComments", lambda r: {
        "id": r["Id"], "product_id": r["ProductId"], "parent_id": r["ParentId"], "commenter_id": r["CommenterId"],
        "feature_value_id": r["FeatureValueId"], "invoice_id": r["InvoiceId"], "title": _s(r["Title"]),
        "comment": _s(r["Comment"]), "score": _d(r["Score"]), "is_admin_comment": _b(r["IsAdminComment"]),
        "is_buyer": _b(r["IsBuyer"]), "is_anonymous": _b(r["IsAnonymous"]), "is_active": _b(r["IsActive"]),
        "status": r["Status"] or 0, "status_description": _s(r["CommentStatusDescription"]),
        "verified_by_user_id": r["VerifiedByUserId"], **legacy(r),
    }, "content", {"product_id": (m.Product, True), "parent_id": (m.ProductComment, False), "feature_value_id": (m.FeatureValue, False)}),
    Spec(m.Redirect, "SELECT * FROM RedirectDictionaries", lambda r: {
        "id": r["Id"], "source_url": _s(r["SourceUrl"]), "destination_url": _s(r["DestinationUrl"]),
        "permanent": _b(r["RedirectPermanent"]), "title": _s(r["Title"]), "description": _s(r["Description"]),
        "is_active": _b(r["IsActive"]), **legacy(r),
    }, "content"),
    # ------------------------------------------------------------------ settings
    Spec(m.CompanyInfo, "SELECT * FROM CompanyInfos", lambda r: {
        "id": r["Id"], "name": _s(r["Name"]), "description": _s(r["Description"]), "address": _s(r["Address"]),
        "postal_code": _s(r["PostalCode"]), "phone_numbers": _s(r["PhoneNumbers"]),
        "website_logo_address": _s(r["WebSiteLogoAddress"]), "keywords": _s(r["Keywords"]), **legacy(r),
    }, "settings"),
    Spec(m.CompanyBranch, "SELECT * FROM CompanyBranches", lambda r: {
        "id": r["Id"], "name": _s(r["Name"]), "address": _s(r["Address"]), "phone": _s(r["Phone"]),
        "province_id": r["ProvinceId"], "province_title": _s(r["ProvinceTitle"]), "city_id": r["CityId"],
        "city_title": _s(r["CityTitle"]), "zip_code": _s(r["ZipCode"]), "latitude": r["Latitude"],
        "longitude": r["Longitude"], "is_active": _b(r["IsActive"]), **legacy(r),
    }, "settings"),
    Spec(m.SiteSetting, "SELECT * FROM Settings", lambda r: {
        "id": r["Id"], "website_title": _s(r["WebSiteTitle"]), "description": _s(r["Description"]),
        "is_payment": _b(r["IsPayment"]), "payment_bank": r["PaymentBank"], "online_branch_id": r["OnlineBranchId"],
        "default_sms_panel_id": r["DefaultSmsPanelId"],
        "has_connection_with_snapp_express": _b(r["HasConnectionWithSnappExpress"]),
        "has_connection_with_snapp_pay": _b(r["HasConnectionWithSnappPay"]),
        "has_connection_with_torob": _b(r["HasConnectionWithTorob"]), "show_all_category": _b(r["ShowAllCategory"]),
        "default_theme_id": r["DefaultThemeId"], "is_custom_theme": _b(r["IsCustomTheme"]),
        "has_bulletin": _b(r["HasBulletin"]), "has_cooperation": _b(r["HasCooperation"]), "min_qty": _d(r["MinQty"]),
        "only_has_media_products": _b(r["OnlyHasMediaProducts"]),
        "coupon_calculation_type": r["CouponCalculationType"], "gift_card_use_type": r["GiftCardUseType"], **legacy(r),
    }, "settings"),
]

_THEME_COLORS = [
    ("white_color", "WhiteColor"), ("white_hover_color", "WhiteHoverColor"), ("primary1_color", "Primary1Color"),
    ("primary2_color", "Primary2Color"), ("secondary_color", "SecondaryColor"), ("border_color", "BorderColor"),
    ("cta_color", "CtaColor"), ("cta_hover_color", "CtaHoverColor"), ("cta_disabled_color", "CtaDisabledColor"),
    ("focus_color", "FocusColor"), ("highlight_color", "HighlightColor"), ("alert_color", "AlertColor"),
]


def _theme(r: dict) -> dict:
    return {
        "id": r["Id"], "lable_title": _s(r["LableTitle"]), "category_count": r["CategoryCount"],
        "description": _s(r["Description"]), "mobile_image": _s(r["MobileImage"]), "header_image": _s(r["HeaderImage"]),
        "desktop_image": _s(r["DesktopImage"]), "is_editable": _b(r["IsEditable"]),
        **{f: _s(r[c]) for f, c in _THEME_COLORS}, **legacy(r),
    }


SPECS += [
    Spec(m.Theme, "SELECT * FROM Themes", lambda r: {**_theme(r), "theme_name": _s(r["ThemeName"])}, "settings"),
    Spec(m.CustomTheme, "SELECT * FROM CustomThemes", lambda r: {**_theme(r), "custom_theme_name": _s(r["CustomThemeName"])}, "settings"),
    Spec(m.Page, "SELECT * FROM Pages", lambda r: {
        "id": r["Id"], "name": _s(r["Name"]), "key": _s(r["Key"]), "type": _s(r["Type"]),
        "image_url": _s(r["ImageUrl"]), "is_landing_page": _b(r["IsLandingPage"]), **legacy(r),
    }, "settings"),
    Spec(m.ThemePage, "SELECT * FROM ThemePages", lambda r: {
        "id": r["Id"], "theme_id": r["ThemeId"], "page_id": r["PageId"], **legacy(r),
    }, "settings", {"theme_id": (m.Theme, True), "page_id": (m.Page, True)}),
    Spec(m.CustomThemePage, "SELECT * FROM CustomThemePages", lambda r: {
        "id": r["Id"], "custom_theme_id": r["CustomThemeId"], "page_id": r["PageId"], **legacy(r),
    }, "settings", {"custom_theme_id": (m.CustomTheme, True), "page_id": (m.Page, True)}),
    # ------------------------------------------------------------------ shipping
    Spec(m.Province, "SELECT * FROM Provinces", lambda r: {
        "id": r["Id"], "name": _s(r["Name"]), "country_id": r["CountryId"], "latitude": r["Latitude"],
        "longitude": r["Longitude"], **legacy(r),
    }, "shipping"),
    Spec(m.City, "SELECT * FROM Cities", lambda r: {
        "id": r["Id"], "province_id": r["ProvinceId"], "name": _s(r["Name"]), "latitude": r["Latitude"],
        "longitude": r["Longitude"], **legacy(r),
    }, "shipping", {"province_id": (m.Province, True)}),
    Spec(m.ShippingMethodType, "SELECT * FROM ShippingMethodTypes", lambda r: {
        "id": r["Id"], "name": _s(r["Name"]), "key": _s(r["Key"]), "include_costs": _b(r["IncludeCosts"]), **legacy(r),
    }, "shipping"),
    Spec(m.ShippingMethod, "SELECT * FROM ShippingMethods", lambda r: {
        "id": r["Id"], "name": _s(r["Name"]), "type_id": r["ShippingMethodTypeId"], "description": _s(r["Description"]),
        "icon": _s(r["Icon"]), "fixed_cost": _d(r["FixedCost"]), "variable_fee": _d(r["VariableFee"]),
        "is_dynamic_pricing": _b(r["IsDynamicPricing"]), "requires_insurance": _b(r["RequiresInsurance"]),
        "insurance_cost": _d(r["InsuranceCost"]), "insurance_percentage": _d(r["InsurancePercentage"]),
        "tax_percentage": _d(r["TaxPercentage"]), "tax_amount": _d(r["TaxAmount"]),
        "source_dependent": _b(r["SourceDependent"]), **legacy(r),
    }, "shipping", {"type_id": (m.ShippingMethodType, False)}),
    Spec(m.ShippingMethodLocation, "SELECT * FROM ShippingMethodLocations", lambda r: {
        "id": r["Id"], "shipping_method_id": r["ShippingMethodId"], "province_id": r["ProvinceId"],
        "city_id": r["CityId"], **legacy(r),
    }, "shipping", {"shipping_method_id": (m.ShippingMethod, True)}),
    # ---------------------------------------------------------------- gallery
    Spec(m.FileFormat, "SELECT * FROM FileFormats", lambda r: {
        "id": r["Id"], "type": _s(r["Type"]), "extension": _s(r["Extension"]).lower(), "mime_type": _s(r["MimeType"]),
        **legacy(r),
    }, "gallery"),
    Spec(m.FileMedia, "SELECT * FROM FileMedias", lambda r: {
        "id": r["Id"], "file_name": _s(r["FileName"]), "url": _s(r["Url"]), "format_id": r["FormatId"],
        "upload_time": r["UploadTime"], "content_hash": _s(r["ContentHash"]), "domain": _s(r["Domain"]),
        "size": r["Size"], "width": r["Width"], "height": r["Height"], "used": _b(r["Used"]),
        "favorite": _b(r["Favorite"]), "alternative": _s(r["Alternative"]), "tooltip_title": _s(r["TooltipTitle"]),
        **legacy(r),
    }, "files"),
    Spec(m.FileTag, "SELECT * FROM FileTags", lambda r: {
        "id": r["Id"], "title": _s(r["Title"]), **legacy(r),
    }, "files"),
    Spec(m.FileMediaTag, "SELECT * FROM FileMediaTags", lambda r: {
        "id": r["Id"], "file_media_id": r["FileMediaId"], "tag_id": r["TagId"], **legacy(r),
    }, "files", {"file_media_id": (m.FileMedia, True), "tag_id": (m.FileTag, True)}),
    Spec(m.Job, "SELECT * FROM Jobs", lambda r: {
        "id": r["Id"], "title": _s(r["Title"]), **legacy(r),
    }, "jobs"),
    # ---------------------------------------------------------------- blog
    # Not in the default run: articles are written in the new admin from now on.
    Spec(m.BlogCategory, "SELECT * FROM BlogCategories", lambda r: {
        "id": r["Id"], "title": _s(r["Title"]), "in_main_page": _b(r["InMainPage"]), "parent_id": r["ParentId"], **legacy(r),
    }, "blog", {"parent_id": (m.BlogCategory, False)}),
    Spec(m.ArticleTag, "SELECT * FROM ArticleTags", lambda r: {
        "id": r["Id"], "name": _s(r["Name"]), **legacy(r),
    }, "blog"),
    Spec(m.Article, "SELECT * FROM Articles", lambda r: {
        "id": r["Id"], "title": _s(r["ArticleTitle"]), "content": _s(r["ArticleContent"]),
        "description": _s(r["ArticleDescription"]), "thumbnail": _s(r["ArticleThumbnail"]),
        "uniq_url": _s(r["ArticleUniqUrl"]) or f"article-{r['Id']}", "author_id": r["AuthorId"],
        "publish_date": r["PublishDate"], "expiration_date": r["ExpirationDate"],
        "show_on_page": _b(r["ShowOnPage"]), "view_count": r["ViewCount"] or 0, **legacy(r),
    }, "blog"),
    Spec(m.ArticleBlogCategory, "SELECT * FROM ArticleBlogCategories", lambda r: {
        "id": r["Id"], "article_id": r["ArticleId"], "category_id": r["CategoryId"], **legacy(r),
    }, "blog", {"article_id": (m.Article, True), "category_id": (m.BlogCategory, True)}),
    Spec(m.ArticleTagRelation, "SELECT * FROM ArticleTagRelations", lambda r: {
        "id": r["Id"], "article_id": r["ArticleId"], "tag_id": r["ArticleTagId"], **legacy(r),
    }, "blog", {"article_id": (m.Article, True), "tag_id": (m.ArticleTag, True)}),
    Spec(m.ArticleComment, "SELECT * FROM ArticleComments", lambda r: {
        "id": r["Id"], "article_id": r["ArticleId"], "parent_id": r["ParentId"], "commenter_id": r["CommenterId"],
        "title": _s(r["Title"]), "comment": _s(r["Comment"]), "score": r["Score"] or 0,
        "is_admin_comment": _b(r["IsAdminComment"]), "is_buyer": _b(r["IsBuyer"]), "is_anonymous": _b(r["IsAnonymous"]),
        "is_active": _b(r["IsActive"]), "status": r["Status"] or 0, "status_description": _s(r["CommentStatusDescription"]),
        "verified_by_user_id": r["VerifiedByUserId"], **legacy(r),
    }, "blog", {"article_id": (m.Article, True), "parent_id": (m.ArticleComment, False)}),
    Spec(m.ArticleLike, "SELECT * FROM ArticleLikes", lambda r: {
        "id": r["Id"], "article_id": r["ArticleId"], "customer_id": r["CustomerId"], "liked": _b(r["Liked"]), **legacy(r),
    }, "blog", {"article_id": (m.Article, True)}),
    # Not in the default run: the site takes new reactions.
    Spec(m.ProductCommentLike, "SELECT * FROM ProductCommentLikes", lambda r: {
        "id": r["Id"], "comment_id": r["CommentId"], "customer_id": r["CustomerId"], "liked": _b(r["Liked"]), **legacy(r),
    }, "likes", {"comment_id": (m.ProductComment, True)}),
    # Not in the default run: gateways are managed in the panel afterwards.
    Spec(m.BankInfo, "SELECT * FROM BankInfos", lambda r: {
        "id": r["Id"], "name": _s(r["BankName"]), "key": _s(r["BankWebSite"]),
        "icon": base64.b64encode(r["Icon"]).decode() if r["Icon"] else "", **legacy(r),
    }, "banks"),
    Spec(m.BankGateway, "SELECT * FROM BankGateways", lambda r: {
        "id": r["Id"], "bank_id": r["BankId"], "merchant": _s(r["Merchant"]), "terminal_id": _s(r["TerminalId"]),
        "merchant_key": _s(r["MerchantKey"]), **legacy(r),
    }, "banks", {"bank_id": (m.BankInfo, True)}),
    # ---------------------------------------------------------------- cooperation
    # Not part of the default run either: the site will take new requests.
    Spec(m.CooperationRequest, "SELECT * FROM CooperationRequests", lambda r: {
        "id": r["Id"], "first_name": _s(r["FirstName"]), "last_name": _s(r["LastName"]),
        "cellphone": _s(r["CellPhone"]), "email": _s(r["Email"]), "address": _s(r["Address"]),
        "additional_info": _s(r["AdditionalInfo"]), "job_position_title": _s(r["JobPositionTitle"]),
        "state": r["State"] or 0, "reason": _s(r["Reason"]), "last_time_action": r["LastTimeAction"], **legacy(r),
    }, "cooperation"),
    # ---------------------------------------------------------------- customers
    # Not part of the default run: once the new site takes sign-ups, a refresh
    # would delete them. Duplicate mobiles are merged into the oldest account.
    Spec(m.Customer, "SELECT * FROM Customers WHERE Id IN (SELECT MIN(Id) FROM Customers GROUP BY CellPhone)", lambda r: {
        "id": r["Id"], "first_name": _s(r["FirstName"]), "last_name": _s(r["LastName"]),
        "cellphone": _s(r["CellPhone"]).strip(), "email": _s(r["Email"]), "national_code": _s(r["NationalCode"]),
        "birth_date": r["BirthDate"] if r["BirthDate"] and r["BirthDate"].year > 1 else None,
        "job_id": r["JobId"], "is_active": _b(r["IsActive"]), "is_bulletin_enabled": _b(r["IsBulletinEnable"]),
        "bulletin_subscription_date": r["BulletinSubscriptionDate"], **legacy(r),
    }, "customers"),
    Spec(m.CustomerAddress, f"SELECT a.*, {_OLDEST_CUSTOMER} AS OwnerId FROM CustomerAddresses a", lambda r: {
        "id": r["Id"], "customer_id": r["OwnerId"], "title": _s(r["Title"]), "is_default": _b(r["IsDefault"]),
        "address": _s(r["Address"]), "province_id": r["ProvinceId"], "city_id": r["CityId"],
        "zip_code": _s(r["ZipCode"]), "latitude": r["Latitude"], "longitude": r["Longitude"],
        "first_name": _s(r["FirstName"]), "last_name": _s(r["LastName"]), "mobile": _s(r["Mobile"]),
        "is_myself_recipient": _b(r["IsMyselfRecipient"]), **legacy(r),
    }, "customers", {"customer_id": (m.Customer, True)}),
    Spec(m.CustomerFavoriteProduct, f"SELECT a.*, {_OLDEST_CUSTOMER} AS OwnerId FROM CustomerFavoriteProducts a", lambda r: {
        "id": r["Id"], "customer_id": r["OwnerId"], "product_id": r["ProductId"], "color_id": r["ColerId"],
        "size_id": r["SizeId"], **legacy(r),
    }, "customers", {"customer_id": (m.Customer, True), "product_id": (m.Product, True)}),
]

GROUPS = sorted({s.group for s in SPECS})
DEFAULT_GROUPS = [g for g in GROUPS if g not in ("customers", "cooperation", "blog", "likes", "banks", "files")]

# Rows that point at their own table (parent_id) are inserted with the link
# empty first and patched afterwards, so insert order does not matter.
_SELF_REF = "parent_id"


class Command(BaseCommand):
    help = "ورود داده‌های لایه وب از DadehfaOnlineShop (فقط خواندنی)"

    def add_arguments(self, parser):
        parser.add_argument("--only", choices=GROUPS, action="append", help="فقط این گروه(ها)")
        parser.add_argument("--tables", nargs="+", help="فقط این مدل‌ها، با نام کلاس")
        parser.add_argument("--upsert", action="store_true", help="به‌روزرسانی در جا، بدون حذف")

    def handle(self, *args, **options):
        only = set(options.get("only") or DEFAULT_GROUPS)
        tables = set(options.get("tables") or [])
        specs = [s for s in SPECS if s.model.__name__ in tables] if tables else [s for s in SPECS if s.group in only]
        if not specs:
            raise CommandError("هیچ جدولی انتخاب نشد")

        self.upsert = options.get("upsert", False)
        self.quiet = options.get("verbosity", 1) == 0
        t0 = time.time()
        with transaction.atomic():
            if not self.upsert:
                for spec in reversed(specs):
                    spec.model.objects.all().delete()
            known: dict[type, set] = {}
            for spec in specs:
                known[spec.model] = self._import(spec, known)
            self._reset_sequences([spec.model for spec in specs])
        if any(s.model in (m.Product, m.Category) for s in specs):
            call_command("fix_slugs", verbosity=options.get("verbosity", 1), stdout=self.stdout)
        if not self.quiet:
            self.stdout.write(self.style.SUCCESS(f"تمام شد در {time.time() - t0:.1f} ثانیه"))

    def _reset_sequences(self, models: list) -> None:
        """Rows came with their own ids, so PostgreSQL's counters must move past them or the next new row collides."""
        with connection.cursor() as cursor:
            for statement in connection.ops.sequence_reset_sql(no_style(), models):
                cursor.execute(statement)

    def _write(self, model, rows: list, columns: list[str]) -> None:
        if self.upsert:
            model.objects.bulk_create(rows, update_conflicts=True, unique_fields=["id"], update_fields=columns)
        else:
            model.objects.bulk_create(rows)

    def _ids_of(self, model, known):
        if model not in known:
            known[model] = set(model.objects.values_list("id", flat=True))
        return known[model]

    def _import(self, spec: Spec, known: dict) -> set:
        model = spec.model
        started = time.time()
        self_ref = _SELF_REF in spec.fks and spec.fks[_SELF_REF][0] is model
        ids, batch, parents, skipped, nulled, columns = set(), [], {}, 0, 0, None

        for row in iter_rows(spec.sql):
            data = {k: _dt(v) if isinstance(v, datetime) else v for k, v in spec.build(row).items()}
            drop = False
            for fk, (target, required) in spec.fks.items():
                value = data.get(fk)
                if value is None or (self_ref and fk == _SELF_REF):
                    continue
                if value not in self._ids_of(target, known):
                    if required:
                        drop = True
                        break
                    data[fk] = None
                    nulled += 1
            if drop:
                skipped += 1
                continue
            if self_ref and data.get(_SELF_REF) is not None:
                parents[data["id"]] = data.pop(_SELF_REF)
            ids.add(data["id"])
            batch.append(model(**data))
            columns = columns or [k for k in data if k != "id"]
            if len(batch) >= BATCH:
                self._write(model, batch, columns)
                batch = []
        if batch:
            self._write(model, batch, columns)

        if parents:
            fixed = {}
            for child, parent in parents.items():
                if parent in ids:
                    fixed.setdefault(parent, []).append(child)
                else:
                    nulled += 1
            for parent, children in fixed.items():
                model.objects.filter(id__in=children).update(parent_id=parent)

        if self.quiet:
            return ids
        note = []
        if skipped:
            note.append(f"{skipped} رد شد (مرجع ناموجود)")
        if nulled:
            note.append(f"{nulled} ارجاع خالی شد")
        self.stdout.write(
            f"  {model.__name__:<24} {len(ids):>8}  ({time.time() - started:.1f}s)"
            + (f"  — {', '.join(note)}" if note else "")
        )
        return ids
