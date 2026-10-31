"""
Routes of the hub, at the root of its host (payhub.mong.ir). Case does not
matter and a trailing slash is optional, as on Mong.Pay (Kestrel).
"""
from django.urls import re_path

from . import views as v

TOKEN = r"(?P<token>[a-f0-9]{32})"

urlpatterns = [
    re_path(r"(?i)^__health/?$", v.HealthView.as_view()),
    re_path(r"(?i)^GenerateToken/?$", v.GenerateTokenView.as_view()),
    re_path(rf"(?i)^GoToPayPage/{TOKEN}/(?P<transaction_id>[^/]+)/(?P<pay_amount>[^/]+)/?$", v.GoToPayPageView.as_view()),
    re_path(rf"(?i)^GetPaymentToken/{TOKEN}/(?P<transaction_id>[^/]+)/(?P<pay_amount>[^/]+)/?$", v.GetPaymentTokenView.as_view()),
    re_path(rf"(?i)^zarinpal/callback/{TOKEN}/?$", v.ZarinpalCallbackView.as_view()),
    re_path(rf"(?i)^PaymentVerification/{TOKEN}/?$", v.PaymentVerificationView.as_view()),
    re_path(rf"(?i)^CheckToken/{TOKEN}/?$", v.CheckTokenView.as_view()),
    re_path(rf"(?i)^api/SnappPay/CallBack/(?P<record_id>\d+)/{TOKEN}/?$", v.SnappCallbackView.as_view()),
    re_path(r"(?i)^api/SnappPay/GetTokenByCompany/(?P<company_id>[^/]+)/?$", v.SnappHubTokenView.as_view()),
    re_path(r"(?i)^api/SnappPay/EligibleWithAuth/?$", v.SnappEligibleView.as_view()),
    re_path(r"(?i)^api/SnappPay/PaymentCancel/?$", v.SnappCancelView.as_view()),
    re_path(r"(?i)^api/SnappPay/UpdatePayment/?$", v.SnappUpdateView.as_view()),
    re_path(r"(?i)^api/SnappPay/PaymentStatus/?$", v.SnappStatusView.as_view()),
]
