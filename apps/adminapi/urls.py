"""
Admin panel API: /api/admin/v1/<Controller>/<Action>, the old adminapi.mong.ir
routes. The panel's NEXT_PUBLIC_ADMIN_PO_MONG points here.

SearchEngine/* (page meta, breadcrumbs, sitemaps) lived on adminapi too and the
storefront still reads it from this address; it is the storefront's own view.
"""
from django.urls import path, re_path

from apps.storefront import views as storefront

from .views import auth, categories, dashboard, products

urlpatterns = [
    path("Auth/login", auth.LoginView.as_view()),
    path("Auth/otp", auth.OtpView.as_view()),
    path("Auth/refresh", auth.RefreshView.as_view()),
    path("Auth/GetProfile", auth.ProfileView.as_view()),

    path("Dashboard/Date", dashboard.DateView.as_view()),

    path("Category/All", categories.AllView.as_view()),
    path("Category/GetParents", categories.ParentsView.as_view()),
    path("Category/GetChildren", categories.ChildrenView.as_view()),
    path("Category/GetCatgoryById", categories.ByIdView.as_view()),
    path("Category/<int:category_id>/descriptions", categories.DescriptionsView.as_view()),

    path("Products/GetAllProduct", products.ListView.as_view()),
    path("Products/GetFilters", products.FiltersView.as_view()),
    path("Products/GetProductLables", products.LabelsView.as_view()),
    path("Products/GetDetailProduct/<int:product_id>", products.DetailView.as_view()),
    path("Products/UpdateSlug", products.UpdateSlugView.as_view()),
    path("Products/ValidateSlug", products.ValidateSlugView.as_view()),
    path("Products/ShowInTrob", products.TorobView.as_view()),
    path("Products/<int:product_id>/descriptions", products.DescriptionsView.as_view()),

    path("SearchEngine/SiteMaps", storefront.SearchEngineSiteMapsView.as_view()),
    re_path(r"^SearchEngine/(?P<entity_type>[^/]+)/(?P<slug>.+)/meta$", storefront.SearchEngineMetaView.as_view()),
    re_path(r"^SearchEngine/(?P<entity_type>[^/]+)/(?P<slug>.+)/breadcrumbs$", storefront.SearchEngineBreadcrumbsView.as_view()),
    re_path(r"^SearchEngine/(?P<entity_type>[^/]+)/(?P<slug>.+)/index$", storefront.SearchEngineIndexView.as_view()),
]
