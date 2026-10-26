"""
REST API Views for Samian ERP diagnostics, status, and manual sync triggers.
"""
from __future__ import annotations

import logging
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAdminUser

from .client import get_samian_client
from .config import get_samian_settings
from .services import CatalogService, InventoryService, MediaService, OrderService
from .models import SamianProduct, SamianProductColor, SamianInventory, SamianSyncLog

logger = logging.getLogger(__name__)


class SamianStatusView(APIView):
    """
    Check Samian ERP connectivity and return server statistics.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        cfg = get_samian_settings()
        client = get_samian_client()

        auth_ok = False
        token_len = 0
        error_msg = None

        try:
            token = client.login()
            auth_ok = True
            token_len = len(token)
        except Exception as exc:
            error_msg = str(exc)

        latest_sync = SamianSyncLog.objects.order_by("-started_at").first()

        data = {
            "is_connected": auth_ok,
            "base_url": cfg.base_url,
            "port": "8087 (Development)",
            "token_acquired": auth_ok,
            "token_length": token_len,
            "error": error_msg,
            "local_database_stats": {
                "products_count": SamianProduct.objects.count(),
                "colors_count": SamianProductColor.objects.count(),
                "stock_records_count": SamianInventory.objects.count(),
            },
            "latest_sync": {
                "action": latest_sync.action if latest_sync else None,
                "status": latest_sync.status if latest_sync else None,
                "started_at": latest_sync.started_at if latest_sync else None,
                "records_upserted": latest_sync.records_upserted if latest_sync else 0,
            } if latest_sync else None,
        }
        return Response(data, status=status.HTTP_200_OK if auth_ok else status.HTTP_503_SERVICE_UNAVAILABLE)


class SamianCatalogPreviewView(APIView):
    """
    Direct live preview of products from Samian ERP.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        take = min(int(request.query_params.get("take", 10)), 50)
        skip = int(request.query_params.get("skip", 0))

        catalog = CatalogService()
        try:
            products = catalog.get_products_page(skip=skip, take_count=take)
            return Response({"count": len(products), "results": products})
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SamianInventoryPreviewView(APIView):
    """
    Direct live preview of stock levels from Samian ERP.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        barcode_id = request.query_params.get("barcode_id")
        inventory = InventoryService()
        try:
            if barcode_id:
                stocks = inventory.get_stock_for_barcode(int(barcode_id))
            else:
                take = min(int(request.query_params.get("take", 10)), 50)
                skip = int(request.query_params.get("skip", 0))
                stocks = inventory.get_stock_page(skip=skip, take_count=take)
            return Response({"count": len(stocks), "results": stocks})
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SamianMediaProxyView(APIView):
    """
    Stream product photos directly from Samian ERP to frontend UI.
    URL: /api/samian/media/<int:color_id>/<int:photo_idx>/
    """
    permission_classes = [AllowAny]

    def get(self, request, color_id: int, photo_idx: int = 0):
        import requests
        from django.http import HttpResponse, Http404

        try:
            color = SamianProductColor.objects.get(samian_id=color_id)
        except SamianProductColor.DoesNotExist:
            raise Http404("Color record not found")

        gallery = color.colorsgalery
        if not gallery or photo_idx >= len(gallery):
            raise Http404("Photo index not found in gallery")

        file_item = gallery[photo_idx]
        file_path = file_item.get("filePath") if isinstance(file_item, dict) else None
        if not file_path:
            raise Http404("File path missing")

        cfg = get_samian_settings()
        # Clean target URL: dev server port 8087
        raw_base = cfg.base_url.rstrip("/")
        if raw_base.endswith("/v2"):
            raw_base = raw_base[:-3]

        target_url = f"{raw_base}/{file_path.lstrip('/')}"

        try:
            resp = requests.get(target_url, timeout=12)
            if resp.status_code == 200:
                content_type = resp.headers.get("Content-Type", "image/jpeg")
                response = HttpResponse(resp.content, content_type=content_type)
                response["Cache-Control"] = "public, max-age=86400"
                return response
            return HttpResponse(f"Upstream status: {resp.status_code}", status=resp.status_code)
        except Exception as exc:
            return HttpResponse(f"Media fetch failed: {exc}", status=502)

