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

from django.views.static import serve

from apps.website.views import image_variant
from django.urls import re_path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health_check, name="health-check"),
    path("api/samian/", include("apps.samian.urls")),
    path("api/v1/", include("apps.storefront.urls")),
    re_path(r"^(?:api/)?img/(?P<key>.+)$", image_variant),
    re_path(r"^cdn/(?P<path>.*)$", serve, {"document_root": "/mnt/sda2/cdn.samian.mong.ir/public_html/wwwroot"}),
    re_path(r"^api/cdn/(?P<path>.*)$", serve, {"document_root": "/mnt/sda2/cdn.samian.mong.ir/public_html/wwwroot"}),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
