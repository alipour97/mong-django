"""
URL Configuration for mong_samian.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse

def health_check(request):
    return JsonResponse({
        "status": "healthy",
        "service": "mong_backend",
        "erp": "Samian ERP (Development Port 8087)",
    })

from apps.website.media import cdn_file
from apps.website.views import image_variant
from django.urls import re_path

urlpatterns = [
    # /admin is the Next.js admin panel (nginx); Django admin lives here
    path("django-admin/", admin.site.urls),
    path("api/health/", health_check, name="health-check"),
    path("api/samian/", include("apps.samian.urls")),
    path("api/v1/", include("apps.storefront.urls")),
    path("api/admin/v1/", include("apps.adminapi.urls")),
    # The payment hub: its routes sit at the root, as on Mong.Pay (apps/payhub/urls.py)
    path("", include("apps.payhub.urls")),
    # SnappPay Crawler Feed & API (Legacy and Modern endpoints, handles both snappay and SnappPay)
    re_path(r"^api/[Ss]napp[Pp]?ay/", include("apps.storefront.snappay_urls")),
    re_path(r"^api/v1/[Ss]napp[Pp]?ay/", include("apps.storefront.snappay_urls")),
    re_path(r"^(?:api/)?img/(?P<key>.+)$", image_variant),
    re_path(r"^(?:api/)?cdn/(?P<path>.+)$", cdn_file),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
