"""
URLs for the storefront API (samian.mong.ir/api/v1/...), mirroring api.mong.ir.
SearchEngine/* lived on adminapi.mong.ir in the legacy system; both frontend
base URLs point here for now.
"""
from django.urls import path, re_path

from . import blog
from . import views as v

urlpatterns = [
    # Configs, company, theme
    path("PrimaryConfig/GetConfig/<str:key>", v.PrimaryConfigGetConfigView.as_view()),
    path("PrimaryConfig/Get", v.PrimaryConfigGetConfigView.as_view()),
    path("CompanyInfo/GetCompanyInfo", v.CompanyInfoView.as_view()),
    path("Setting/GetDefaultTheme", v.SettingGetDefaultThemeView.as_view()),
    path("SortCriteria/GetAll", v.SortCriteriaGetAllView.as_view()),

    # Blog
    path("Article/GetRecentArticles", blog.RecentView.as_view()),
    path("Article/GetArticleByUniqUrl", blog.ByUniqUrlView.as_view()),
    path("Article/GetAllCategoryArticle", blog.CategoriesView.as_view()),
    path("Article/GetArticleByCategoryId", blog.ByCategoryView.as_view()),
    path("Article/GetSuggestedArticles", blog.SuggestedView.as_view()),
    path("Article/GetAllArticleComments", blog.CommentsView.as_view()),

    # Categories
    path("Category/GetAll", v.CategoryGetAllView.as_view()),
    path("Category/GetById/<int:category_id>", v.CategoryGetByIdView.as_view()),
    path("Category/GetBreadCrumbs/<int:category_id>", v.CategoryGetBreadCrumbsView.as_view()),
    path("Category/GetSliderBannerSummaries", v.CategoryGetSliderBannerSummariesView.as_view()),
    path("Category/GetCategorySummaries", v.CategoryGetCategorySummariesView.as_view()),

    # Collections and outfits
    path("Collection/GetCollectionSummaries", v.CollectionGetCollectionSummariesView.as_view()),
    path("Collection/GetAll", v.CollectionGetAllView.as_view()),
    path("Collection/GetById/<int:collection_id>", v.CollectionGetByIdView.as_view()),
    path("Outfit/GetOutfitSummaries", v.OutfitGetOutfitSummariesView.as_view()),
    path("Outfit/GetAll", v.OutfitGetAllView.as_view()),
    path("Outfit/GetById/<int:outfit_id>", v.OutfitGetByIdView.as_view()),
    path("Outfit/GetProductsById/<int:outfit_id>", v.OutfitGetProductsByIdView.as_view()),

    # Products
    path("Product/GetAll", v.ProductGetAllView.as_view()),
    path("Product/Search", v.ProductSearchView.as_view()),
    path("Product/GetSelectedProducts", v.ProductGetSelectedProductsView.as_view()),
    path("Product/GetById/<int:product_id>", v.ProductGetByIdView.as_view()),
    path("Product/SuggestProduct", v.ProductSuggestView.as_view()),
    path("Product/GetFilterByCategoryId", v.ProductGetFilterByCategoryView.as_view()),
    path("Comment/GetByProductId/<int:product_id>", v.CommentGetByProductIdView.as_view()),

    # Locations
    path("ProvinceCity/GetAllProvince", v.ProvinceGetAllView.as_view()),
    path("ProvinceCity/GetAllCity/<int:province_id>", v.CityGetAllView.as_view()),

    # SEO
    path("SearchEngine/SiteMaps", v.SearchEngineSiteMapsView.as_view()),
    re_path(r"^SearchEngine/(?P<entity_type>[^/]+)/(?P<slug>.+)/meta$", v.SearchEngineMetaView.as_view()),
    re_path(r"^SearchEngine/(?P<entity_type>[^/]+)/(?P<slug>.+)/breadcrumbs$", v.SearchEngineBreadcrumbsView.as_view()),
    re_path(r"^SearchEngine/(?P<entity_type>[^/]+)/(?P<slug>.+)/index$", v.SearchEngineIndexView.as_view()),
]
