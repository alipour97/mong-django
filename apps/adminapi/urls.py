"""
Admin panel API: /api/admin/v1/<Controller>/<Action>, the old adminapi.mong.ir
routes. The panel's NEXT_PUBLIC_ADMIN_PO_MONG points here.

SearchEngine/* (page meta, breadcrumbs, sitemaps) lived on adminapi too and the
storefront still reads it from this address; it is the storefront's own view.
"""
from django.urls import path, re_path

from apps.storefront import views as storefront

from apps.website.models import MediaAttachment

from .views import (
    auth, banners, blog, categories, collections, comments, configs, cooperation, customers, customize, dashboard, gallery,
    products, tags, users,
)

urlpatterns = [
    path("Auth/login", auth.LoginView.as_view()),
    path("Auth/otp", auth.OtpView.as_view()),
    path("Auth/refresh", auth.RefreshView.as_view()),
    path("Auth/GetProfile", auth.ProfileView.as_view()),

    path("Dashboard/Date", dashboard.DateView.as_view()),
    path("Dashboard/DashboardNotif", dashboard.NotifView.as_view()),
    path("Dashboard/GrowthRate", dashboard.GrowthRateView.as_view()),
    path("Dashboard/SynchronizationStatus", dashboard.SyncStatusView.as_view()),
    path("Dashboard/Search", dashboard.SearchView.as_view()),
    path("Report/GetDashboardLablesReports", dashboard.LabelsView.as_view()),
    path("Invoice/DailyCounts", dashboard.DailyCountsView.as_view()),
    path("Invoice/InvoiceCountByHour", dashboard.CountByHourView.as_view()),
    path("Products/TopSelling", dashboard.TopSellingView.as_view()),
    path("Products/TopSellingGroupProduct", dashboard.TopSellingGroupsView.as_view()),

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

    path("PrimaryConfig", customize.ConfigAddView.as_view()),
    path("PrimaryConfig/Get", customize.ConfigGetView.as_view()),
    path("PrimaryConfig/Update/<int:config_id>", customize.ConfigUpdateView.as_view()),
    path("PrimaryConfig/update/<int:config_id>", customize.ConfigUpdateView.as_view()),
    path("PrimaryConfig/SoftDelete/<int:config_id>", customize.ConfigDeleteView.as_view()),

    path("Setting/GetSetting", customize.SettingView.as_view()),
    path("Setting/ChangeMinQty", customize.MinQtyView.as_view()),
    path("Setting/ToggleHasMediaProducts", customize.HasMediaView.as_view()),
    path("Setting/UpdateShowCategoryTopProduct", customize.ShowCategoryTopProductView.as_view()),
    path("Setting/SetDefaultTheme", customize.DefaultThemeView.as_view()),
    path("Setting/GetCompanyInfo", customize.CompanyInfoView.as_view()),
    path("Setting/UpdateCompanyInfo", customize.UpdateCompanyInfoView.as_view()),
    path("Setting/GetPaymentConnections", customize.PaymentConnectionsView.as_view()),
    path("Setting/UpdatePaymentConnections", customize.UpdatePaymentConnectionsView.as_view()),
    path("Cdn/upload", customize.UploadView.as_view()),

    path("RedirectManager/GetAll", customize.RedirectListView.as_view()),
    path("RedirectManager/GetRedirect/<int:redirect_id>", customize.RedirectByIdView.as_view()),
    path("RedirectManager/AddOrUpdateRedirect", customize.RedirectSaveView.as_view()),
    path("RedirectManager/AddOrUpdateRedirects", customize.RedirectBulkView.as_view()),
    path("RedirectManager/BulkAddOrUpdateRedirects", customize.RedirectBulkView.as_view()),
    path("RedirectManager/DeleteRedirect/<int:redirect_id>", customize.RedirectDeleteView.as_view()),
    path("RedirectManager/Redirect", customize.RedirectGoView.as_view()),

    path("Customer/GetCustomerLablesReport", customers.LabelsView.as_view()),
    path("Customer/GetCustomers", customers.ListView.as_view()),
    path("Customer/Add", customers.AddView.as_view()),
    path("Customer/Update", customers.UpdateView.as_view()),
    path("Customer/Validation", customers.ValidationView.as_view()),
    path("Customer/SoftDelete", customers.DeleteView.as_view()),
    path("Customer/BulletinMembers", customers.BulletinView.as_view()),
    path("Customer/<int:customer_id>", customers.DetailView.as_view()),
    path("Job/JobDropdown", customers.JobsView.as_view()),
    path("Favorite/GetLable", customers.FavoriteLabelView.as_view()),
    path("Favorite/GetFavoriteMainCategories", customers.FavoriteMainCategoriesView.as_view()),
    path("Favorite/GetFavoriteCategories", customers.FavoriteCategoriesView.as_view()),
    path("Favorite/GetFiveCustomer", customers.FavoriteCustomersView.as_view()),
    path("Favorite/GetFiveProduct", customers.FavoriteProductsView.as_view()),
    path("Favorite/GetFavoriteFeatures", customers.FavoriteFeaturesView.as_view()),

    path("User/GetUsers", users.ListView.as_view()),
    path("User/GetDashboardUsers", users.DashboardUsersView.as_view()),
    path("User/Add", users.AddView.as_view()),
    path("User/Upadate", users.UpdateView.as_view()),
    path("User/UpadateUser", users.UpdateNameView.as_view()),
    path("User/ChangeSmsState/<int:user_id>", users.SmsStateView.as_view()),
    path("User/ValidationUserName", users.ValidateUsernameView.as_view()),
    path("User/SoftDelete", users.DeleteView.as_view()),
    path("User/GetAllRole", users.RolesView.as_view()),
    path("User/AddRole", users.AddRoleView.as_view()),

    path("Cooperation/GetAllCooperationRequests", cooperation.ListView.as_view()),
    *[
        path(f"Cooperation/Get{name}CooperationRequests", cooperation.ListView.as_view(state=state))
        for name, state in cooperation.LISTS.items()
    ],
    *[path(f"Cooperation/{name}", cooperation.ActionView.as_view(action=name)) for name in cooperation.ACTIONS],

    path("Article", blog.CreateView.as_view()),
    path("Article/All", blog.ListView.as_view()),
    path("Article/All/", blog.ListView.as_view()),
    path("Article/Categories", blog.CategoriesView.as_view()),
    path("Article/categories", blog.CategoriesView.as_view()),
    path("Article/Tags", blog.TagsView.as_view()),
    path("Article/tags", blog.TagsView.as_view()),
    path("Article/SoftDeleteCategory", blog.DeleteCategoryView.as_view()),
    path("Article/SoftDeleteTag", blog.DeleteTagView.as_view()),
    path("Article/CheckUniqUrl", blog.CheckUrlView.as_view()),
    path("Article/SoftDelete/<int:article_id>", blog.DeleteView.as_view()),
    path("Article/<int:article_id>", blog.DetailView.as_view()),

    path("ShippingMethod", configs.ShippingCreateView.as_view()),
    path("ShippingMethod/All", configs.ShippingListView.as_view()),
    path("ShippingMethod/Types", configs.ShippingTypesView.as_view()),
    path("ShippingMethod/Types/<int:type_id>", configs.ShippingTypeUpdateView.as_view()),
    path("ShippingMethod/methods/<int:method_id>", configs.ShippingStateView.as_view()),
    path("ShippingMethod/<int:method_id>", configs.ShippingDetailView.as_view()),

    path("Bank/GetGateway", configs.GatewayListView.as_view()),
    path("Bank/GetInfo", configs.GatewayListView.as_view()),
    path("Bank/AddBankGateway", configs.GatewayRefuseView.as_view()),
    path("Bank/UpdateBankGateway", configs.GatewayRefuseView.as_view()),
    path("Bank/SoftDelete", configs.GatewayRefuseView.as_view()),

    path("ThirdParty/LogSummary", configs.TorobSummaryView.as_view()),
    path("ThirdParty/ProductReport", configs.TorobReportView.as_view()),
    path("ThirdParty/ProductVisitPieChart", configs.EmptyChartView.as_view()),
    path("ThirdParty/ProductVisitBarChart", configs.EmptyChartView.as_view()),

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
