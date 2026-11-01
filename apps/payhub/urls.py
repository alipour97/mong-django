"""
Routes of the hub, at the root of its host (payhub.mong.ir). Case does not
matter and a trailing slash is optional, as on Mong.Pay (Kestrel).
"""
import re

from django.urls import URLPattern
from django.urls.resolvers import RegexPattern
from django.utils.functional import cached_property

from . import views as v

TOKEN = r"(?P<token>[a-f0-9]{32})"


class AnyCase(RegexPattern):
    """The flag sits on the compiled regex: Django's URL reversing, which the admin needs, refuses an inline (?i)."""

    @cached_property
    def regex(self):
        return re.compile(self._regex, re.IGNORECASE)


def route(regex, view):
    return URLPattern(AnyCase(regex, is_endpoint=True), view.as_view())


urlpatterns = [
    route(r"^__health/?$", v.HealthView),
    route(r"^GenerateToken/?$", v.GenerateTokenView),
    route(rf"^GoToPayPage/{TOKEN}/(?P<transaction_id>[^/]+)/(?P<pay_amount>[^/]+)/?$", v.GoToPayPageView),
    route(rf"^GetPaymentToken/{TOKEN}/(?P<transaction_id>[^/]+)/(?P<pay_amount>[^/]+)/?$", v.GetPaymentTokenView),
    route(rf"^zarinpal/callback/{TOKEN}/?$", v.ZarinpalCallbackView),
    route(rf"^PaymentVerification/{TOKEN}/?$", v.PaymentVerificationView),
    route(rf"^CheckToken/{TOKEN}/?$", v.CheckTokenView),
    route(rf"^api/SnappPay/CallBack/(?P<record_id>\d+)/{TOKEN}/?$", v.SnappCallbackView),
    route(r"^api/SnappPay/GetTokenByCompany/(?P<company_id>[^/]+)/?$", v.SnappHubTokenView),
    route(r"^api/SnappPay/EligibleWithAuth/?$", v.SnappEligibleView),
    route(r"^api/SnappPay/PaymentCancel/?$", v.SnappCancelView),
    route(r"^api/SnappPay/UpdatePayment/?$", v.SnappUpdateView),
    route(r"^api/SnappPay/PaymentStatus/?$", v.SnappStatusView),
]
