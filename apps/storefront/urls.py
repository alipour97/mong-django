"""
URLs for the storefront API (<SITE_URL>/api/v1/...), mirroring api.mong.ir.
SearchEngine/* lived on adminapi.mong.ir in the legacy system; both frontend
base URLs point here for now.
"""
from django.urls import path, re_path

from . import account as acc
from . import blog
from . import interactions as act
from . import orders
from . import payments as pay
from . import views as v

urlpatterns = [
    # Configs, company, theme
    path("PrimaryConfig/GetConfig/<str:key>", v.PrimaryConfigGetConfigView.as_view()),
    path("PrimaryConfig/Get", v.PrimaryConfigGetConfigView.as_view()),
    path("CompanyInfo/GetCompanyInfo", v.CompanyInfoView.as_view()),
    path("Setting/GetDefaultTheme", v.SettingGetDefaultThemeView.as_view()),
    path("SortCriteria/GetAll", v.SortCriteriaGetAllView.as_view()),

    # Customer sign-in and account
    path("Authentication/CustomerAthenticateInfo", acc.AuthenticateInfoView.as_view()),
    path("Authentication/SendOtpCode", acc.SendOtpView.as_view()),
    path("Authentication/CustomerAuthenticate", acc.AuthenticateView.as_view()),
    path("Customer/SignUp", acc.SignUpView.as_view()),
    path("Customer/GetMyProfile", acc.ProfileView.as_view()),
    path("Customer/UpdateMyProfile", acc.UpdateProfileView.as_view()),
    path("Customer/UpdateMyPassword", acc.UpdatePasswordView.as_view()),
    path("Customer/GetAllJob", acc.JobsView.as_view()),
    path("Customer/ActivateBulletin", acc.BulletinView.as_view()),
    path("Customer/GetCustomerAddress", acc.AddressesView.as_view()),
    path("Customer/AddCustomerAddress", acc.AddAddressView.as_view()),
    path("Customer/UpdateCustomerAddress", acc.UpdateAddressView.as_view()),
    path("Customer/SoftDeleteCustomerAddress", acc.DeleteAddressView.as_view()),
    path("Customer/GetCustomerFavoriteProduct", acc.FavoritesView.as_view()),
    path("Customer/AddFavoriteProduct", acc.AddFavoriteView.as_view()),
    path("Customer/DeleteFavoriteProduct", acc.DeleteFavoriteView.as_view()),

    # Comments, likes, forms
    path("Comment/add", act.ProductCommentAddView.as_view()),
    path("Comment/add/", act.ProductCommentAddView.as_view()),
    path("Comment/Reaction", act.ProductCommentReactionView.as_view()),
    path("Article/AddComment", act.ArticleCommentAddView.as_view()),
    path("Article/AddArticleLike/<int:article_id>/likes", act.ArticleLikeView.as_view()),
    path("Cooperation/CooperationRequestSubmit", act.CooperationSubmitView.as_view()),
    path("ThirdPartyLog/AddThirdPartyLog/AddThirdPartyLog", act.ThirdPartyLogView.as_view()),

    # Cart, orders and payment
    path("Invoice/Add", orders.AddView.as_view()),
    path("Invoice/GetLastPreInvoice", orders.LastPreInvoiceView.as_view()),
    path("Invoice/SoftDelete/<int:invoice_id>", orders.DeletePreInvoiceView.as_view()),
    path("Invoice/ClearCart", orders.ClearCartView.as_view()),
    path("Invoice/GetAllCustomerInvoice", orders.CustomerInvoicesView.as_view()),
    path("Invoice/GetCustomerInvoiceById/<int:invoice_id>", orders.CustomerInvoiceView.as_view()),
    path("ShipingMethod/GetAllShipingMethod", orders.ShippingMethodsView.as_view()),
    path("Coupon/Validation", orders.CouponValidationView.as_view()),
    path("GiftCard/GetAll", orders.GiftCardsView.as_view()),
    path("Bank/GetGateways", pay.GatewaysView.as_view()),
    path("Bank/PayInvoiceById", pay.PayView.as_view()),
    path("Bank/SnappPayEligible", pay.SnappEligibleView.as_view()),
    path("Bank/GiftCardPayInvoiceById", pay.ZeroAmountView.as_view()),
    path("Bank/SnappPayOffer", pay.SnappOfferView.as_view()),
    path("Bank/PaymentVerification", pay.PaymentVerificationView.as_view()),

    # Blog
    path("Article/GetRecentArticles", blog.RecentView.as_view()),
    path("Article/GetArticleByUniqUrl", blog.ByUniqUrlView.as_view()),
    path("Article/View/<int:article_id>", blog.ViewCountView.as_view()),
    path("Article/GetAllCategoryArticle", blog.CategoriesView.as_view()),
    path("Article/ListMeta", blog.ListMetaView.as_view()),
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
    path("SearchEngine/product-address/<int:product_id>", v.ProductAddressView.as_view()),
    re_path(r"^SearchEngine/(?P<entity_type>[^/]+)/(?P<slug>.+)/meta$", v.SearchEngineMetaView.as_view()),
    re_path(r"^SearchEngine/(?P<entity_type>[^/]+)/(?P<slug>.+)/breadcrumbs$", v.SearchEngineBreadcrumbsView.as_view()),
    re_path(r"^SearchEngine/(?P<entity_type>[^/]+)/(?P<slug>.+)/index$", v.SearchEngineIndexView.as_view()),
]
