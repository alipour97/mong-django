"""
URLs for Storefront API (samian.mong.ir / api/v1/...)
"""
from django.urls import path, re_path
from .views import (
    PrimaryConfigGetConfigView,
    CompanyInfoView,
    CategoryGetAllView,
    CategoryGetByIdView,
    ProductGetAllView,
    ProductGetSelectedProductsView,
    ProductGetByIdView,
    SettingGetSettingView,
    SliderGetAllView,
    BannerGetAllView,
    SearchEngineMetaView,
    SearchEngineBreadcrumbsView,
    SearchEngineIndexView,
    SearchEngineSiteMapsView,
    CategoryGetSliderBannerSummariesView,
    CategoryGetCategorySummariesView,
    CollectionGetCollectionSummariesView,
    OutfitGetOutfitSummariesView,
)

urlpatterns = [
    # Primary Configs (Layout, Metadata, Section Sort Orders)
    path("PrimaryConfig/GetConfig/<str:key>", PrimaryConfigGetConfigView.as_view(), name="primary-config-get"),
    path("PrimaryConfig/Get", PrimaryConfigGetConfigView.as_view(), name="primary-config-get-post"),

    # Company Info & Settings
    path("CompanyInfo/GetCompanyInfo", CompanyInfoView.as_view(), name="company-info"),
    path("Setting/GetSetting", SettingGetSettingView.as_view(), name="setting-get"),

    # Catalog & Products
    path("Category/GetAll", CategoryGetAllView.as_view(), name="category-get-all"),
    path("Category/GetById/<int:category_id>", CategoryGetByIdView.as_view(), name="category-get-by-id"),
    path("Category/GetSliderBannerSummaries", CategoryGetSliderBannerSummariesView.as_view(), name="category-get-slider-banner-summaries"),
    path("Category/GetCategorySummaries", CategoryGetCategorySummariesView.as_view(), name="category-get-category-summaries"),
    path("Collection/GetCollectionSummaries", CollectionGetCollectionSummariesView.as_view(), name="collection-get-collection-summaries"),
    path("Outfit/GetOutfitSummaries", OutfitGetOutfitSummariesView.as_view(), name="outfit-get-outfit-summaries"),
    path("Product/GetAll", ProductGetAllView.as_view(), name="product-get-all"),
    path("Product/GetSelectedProducts", ProductGetSelectedProductsView.as_view(), name="product-get-selected"),
    path("Product/GetById/<int:product_id>", ProductGetByIdView.as_view(), name="product-get-by-id"),

    # Media Banners & Sliders
    path("Slider/GetAll", SliderGetAllView.as_view(), name="slider-get-all"),
    path("Banner/GetAll", BannerGetAllView.as_view(), name="banner-get-all"),

    # SEO & SearchEngine
    path("SearchEngine/SiteMaps", SearchEngineSiteMapsView.as_view(), name="searchengine-sitemaps"),
    re_path(r"^SearchEngine/(?P<entity_type>[^/]+)/(?P<slug>.+)/meta$", SearchEngineMetaView.as_view(), name="searchengine-meta"),
    re_path(r"^SearchEngine/(?P<entity_type>[^/]+)/(?P<slug>.+)/breadcrumbs$", SearchEngineBreadcrumbsView.as_view(), name="searchengine-breadcrumbs"),
    re_path(r"^SearchEngine/(?P<entity_type>[^/]+)/(?P<slug>.+)/index$", SearchEngineIndexView.as_view(), name="searchengine-index"),
]
