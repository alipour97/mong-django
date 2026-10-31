"""
URL patterns for SnappPay (SearchWise) product crawler and feeds.
"""
from django.urls import path, re_path

from . import snappay_crawler as views

urlpatterns = [
    # Method 2: Product Feed (JSON and XML)
    path("feed", views.SnappPayFeedView.as_view(), name="snappay-feed"),
    path("feed/", views.SnappPayFeedView.as_view()),
    path("feed.json", views.SnappPayFeedView.as_view(), {"format": "json"}, name="snappay-feed-json"),
    path("feed.xml", views.SnappPayFeedView.as_view(), {"format": "xml"}, name="snappay-feed-xml"),

    # Method 3: REST API (Pagination and Item Query)
    path("products", views.SnappPayProductsView.as_view(), name="snappay-products"),
    path("products/", views.SnappPayProductsView.as_view()),
    path("products/<str:identifier>", views.SnappPayProductDetailView.as_view(), name="snappay-product-detail"),
    path("products/<str:identifier>/", views.SnappPayProductDetailView.as_view()),

    # Legacy .NET API Compatibility: /api/SnappPay/ProductList and /api/SnappPay/ProductInfo
    re_path(r"^[Pp]roduct[Ll]ist/?$", views.SnappPayLegacyProductListView.as_view(), name="snappay-legacy-list"),
    re_path(r"^[Pp]roduct[Ii]nfo/?$", views.SnappPayLegacyProductInfoView.as_view(), name="snappay-legacy-info"),
]
