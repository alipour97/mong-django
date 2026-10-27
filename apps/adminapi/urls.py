"""
Admin panel API: /api/admin/v1/<Controller>/<Action>, the old adminapi.mong.ir
routes. The panel's NEXT_PUBLIC_ADMIN_PO_MONG points here.

SearchEngine/* (page meta, breadcrumbs, sitemaps) lived on adminapi too and the
storefront still reads it from this address; it is the storefront's own view.
"""
from django.urls import path, re_path

from apps.storefront import views as storefront

from apps.website.models import MediaAttachment

from .views import auth, banners, categories, collections, comments, dashboard, gallery, products, tags

urlpatterns = [
    path("Auth/login", auth.LoginView.as_view()),
    path("Auth/otp", auth.OtpView.as_view()),
    path("Auth/refresh", auth.RefreshView.as_view()),
    path("Auth/GetProfile", auth.ProfileView.as_view()),

    path("Dashboard/Date", dashboard.DateView.as_view()),

    path("ProductComment/RecentComments", comments.RecentView.as_view()),
    path("ProductComment/GetFilteredComments", comments.FilteredView.as_view()),
    path("ProductComment/GetCommentStatusCounts", comments.StatusCountsView.as_view()),
    path("ProductComment/GetCommentDetailWithMedia/<int:comment_id>", comments.DetailView.as_view()),
    path("ProductComment/UpdateStatus/<int:comment_id>", comments.UpdateStatusView.as_view()),

    path("Banner/GetBannerById", banners.ByIdView.as_view()),
    path("Banner/GetAllBanners", banners.AllView.as_view()),
    path("Banner/AddOrUpdateBanner", banners.SaveView.as_view()),
    path("Banner/DeleteBanner", banners.DeleteView.as_view()),
    path("Banner/ToggleBannerActivation", banners.ToggleView.as_view()),

    path("Collection", collections.CreateView.as_view()),
    path("Collection/All", collections.AllView.as_view()),
    path("Collection/SoftDelete/<int:collection_id>", collections.DeleteView.as_view()),
    path("Collection/<int:collection_id>", collections.DetailView.as_view()),

    path("Category/All", categories.AllView.as_view()),
    path("Category/GetParents", categories.ParentsView.as_view()),
    path("Category/GetChildren", categories.ChildrenView.as_view()),
    path("Category/GetCatgoryById", categories.ByIdView.as_view()),
    path("Category/<int:category_id>/descriptions", categories.DescriptionsView.as_view()),

    path("Products/GetAllProduct", products.ListView.as_view()),
    path("Products/GetFilters", products.FiltersView.as_view()),
    path("Products/GetProductLables", products.LabelsView.as_view()),
    path("Products/GetDetailProduct/<int:product_id>", products.DetailView.as_view()),
    path("Products/SetImageVisibility", products.ImageVisibilityView.as_view()),
    path("Products/UpdateSlug", products.UpdateSlugView.as_view()),
    path("Products/ValidateSlug", products.ValidateSlugView.as_view()),
    path("Products/ShowInTrob", products.TorobView.as_view()),
    path("Products/<int:product_id>/descriptions", products.DescriptionsView.as_view()),
    path("Products/DeleteGuid", products.DeleteGuideView.as_view()),
    path("Category/DeleteGuid", products.DeleteGuideView.as_view(table=MediaAttachment.Table.CATEGORIES, param="categoryId")),
    path("Products/GetSelectedProducts", products.SelectedListView.as_view()),
    path("Products/AddSelectedProduct", products.SelectedAddView.as_view()),
    path("Products/DeleteSelectedProduct", products.SelectedDeleteView.as_view()),
    path("Products/SetSortingWeight", products.SelectedWeightView.as_view()),
    path("Products/ClearAllSelectedProducts", products.SelectedClearView.as_view()),
    path("Products/GetBriefProducts", products.BriefProductsView.as_view()),

    path("FileMedia/UploadFile", gallery.UploadView.as_view()),
    path("FileMedia/GetFilteredMedia", gallery.FilteredView.as_view()),
    path("FileMedia/GetFileMediaById/<int:file_id>", gallery.ByIdView.as_view()),
    path("FileMedia/GetAllTags", gallery.TagsView.as_view()),
    path("FileMedia/AddTag", gallery.AddTagView.as_view()),
    path("FileMedia/AddTagsToFile", gallery.TagsToFileView.as_view()),
    path("FileMedia/AddTagsToFiles", gallery.TagsToFilesView.as_view()),
    path("FileMedia/AddFilesToEntity", gallery.AddToEntityView.as_view()),
    path("FileMedia/RemoveFiles", gallery.RemoveFilesView.as_view()),
    path("FileMedia/DetachMedia/<int:media_id>", gallery.DetachView.as_view()),
    path("FileMedia/DetachMedias", gallery.DetachManyView.as_view()),
    path("FileMedia/UpdateAttributesToFile", gallery.AttributesView.as_view()),
    path("FileMedia/UpdateAttributesToFiles", gallery.AttributesView.as_view(many=True)),
    path("FileMedia/UpdateAttributesToMedia", gallery.AttributesView.as_view(media=True)),
    path("FileMedia/UpdateAttributesToMedias", gallery.AttributesView.as_view(many=True, media=True)),
    path("FileMedia/GetAllFormats", gallery.FormatsView.as_view()),
    path("FileMedia/GetAllFormatTypes", gallery.FormatsView.as_view(what="types")),
    path("FileMedia/GetAllFormatExtensions", gallery.FormatsView.as_view(what="extensions")),

    path("TagControllers/GetAllTags", tags.AllView.as_view()),
    path("TagControllers/AddTag", tags.AddView.as_view()),
    path("TagControllers/AddTagsToProduct", tags.ToProductView.as_view()),
    path("TagControllers/AddTagsToProducts", tags.ToProductsView.as_view()),
    path("TagControllers/AddTagsToCategory", tags.ToCategoryView.as_view()),
    path("TagControllers/AddTagsToCategories", tags.ToCategoriesView.as_view()),

    path("SearchEngine/SiteMaps", storefront.SearchEngineSiteMapsView.as_view()),
    re_path(r"^SearchEngine/(?P<entity_type>[^/]+)/(?P<slug>.+)/meta$", storefront.SearchEngineMetaView.as_view()),
    re_path(r"^SearchEngine/(?P<entity_type>[^/]+)/(?P<slug>.+)/breadcrumbs$", storefront.SearchEngineBreadcrumbsView.as_view()),
    re_path(r"^SearchEngine/(?P<entity_type>[^/]+)/(?P<slug>.+)/index$", storefront.SearchEngineIndexView.as_view()),
]
