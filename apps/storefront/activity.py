from django.db import transaction
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.throttling import SimpleRateThrottle

from apps.website.models import Product, ProductVariant, StoreActivity, StoreVisitor

from .account import CustomerTokenAuthentication, answer
from .journey import browser_uuid, identify_visitor
from .views import PublicView

KIND = StoreActivity.Kind


class ActivityThrottle(SimpleRateThrottle):
    rate = "240/min"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": "store_activity", "ident": self.get_ident(request)}


class ProductActivityView(PublicView):
    throttle_classes = [ActivityThrottle]

    @transaction.atomic
    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        kind = data.get("kind")
        key = browser_uuid(data.get("visitorId"))
        id_field = "variantId" if kind == KIND.CART_ADD else "productId"
        item_id = str(data.get(id_field, ""))
        if (
            not key or kind not in (KIND.PRODUCT_VIEW, KIND.CART_ADD)
            or not item_id.isascii() or not item_id.isdecimal() or len(item_id) > 18
        ):
            return answer(None, 400, "رویداد نامعتبر است.")
        if kind == KIND.CART_ADD:
            title = (ProductVariant.objects.filter(pk=int(item_id), is_deleted=False, product__is_active=True, product__is_deleted=False)
                     .values_list("product__title", flat=True).first())
        else:
            title = (Product.objects.filter(pk=int(item_id), is_active=True, is_deleted=False)
                     .values_list("title", flat=True).first())
        if title is None:
            return answer(None, 404, "کالا یافت نشد.")
        try:
            auth = CustomerTokenAuthentication().authenticate(request)
        except AuthenticationFailed:
            auth = None
        customer = auth[0] if auth else None
        if customer:
            identify_visitor(str(key), customer)
        visitor, _ = StoreVisitor.objects.get_or_create(browser_id=key)
        StoreActivity.objects.create(visitor=visitor, customer=customer, kind=kind, detail=title)
        return answer(True)
