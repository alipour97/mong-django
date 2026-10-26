"""
URLs for Samian ERP API endpoints.
"""
from django.urls import path
from .views import (
    SamianStatusView,
    SamianCatalogPreviewView,
    SamianInventoryPreviewView,
    SamianMediaProxyView,
)

urlpatterns = [
    path("status/", SamianStatusView.as_view(), name="samian-status"),
    path("catalog/preview/", SamianCatalogPreviewView.as_view(), name="samian-catalog-preview"),
    path("inventory/preview/", SamianInventoryPreviewView.as_view(), name="samian-inventory-preview"),
    path("media/<int:color_id>/<int:photo_idx>/", SamianMediaProxyView.as_view(), name="samian-media-proxy"),
]
