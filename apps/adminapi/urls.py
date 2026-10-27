"""
Admin panel API: /api/admin/v1/<Controller>/<Action>, the old adminapi.mong.ir
routes. The panel's NEXT_PUBLIC_ADMIN_PO_MONG points here.

SearchEngine/* (page meta, breadcrumbs, sitemaps) lived on adminapi too and the
storefront still reads it from this address; it is the storefront's own view.
"""
from django.urls import path, re_path

from apps.storefront import views as storefront

from .views import auth, dashboard

urlpatterns = [
    path("Auth/login", auth.LoginView.as_view()),
    path("Auth/otp", auth.OtpView.as_view()),
    path("Auth/refresh", auth.RefreshView.as_view()),
    path("Auth/GetProfile", auth.ProfileView.as_view()),

    path("Dashboard/Date", dashboard.DateView.as_view()),

    path("SearchEngine/SiteMaps", storefront.SearchEngineSiteMapsView.as_view()),
    re_path(r"^SearchEngine/(?P<entity_type>[^/]+)/(?P<slug>.+)/meta$", storefront.SearchEngineMetaView.as_view()),
    re_path(r"^SearchEngine/(?P<entity_type>[^/]+)/(?P<slug>.+)/breadcrumbs$", storefront.SearchEngineBreadcrumbsView.as_view()),
    re_path(r"^SearchEngine/(?P<entity_type>[^/]+)/(?P<slug>.+)/index$", storefront.SearchEngineIndexView.as_view()),
]
