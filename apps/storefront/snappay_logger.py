"""
SnappPay / SearchWise Access Logger.
Logs every request made to SnappPay crawler endpoints across all 3 methods:
1. Method 1: Sitemap (/sitemap.xml / SearchEngine/SiteMaps)
2. Method 2: Feed JSON/XML (/api/snappay/feed, /api/snappay/feed.json)
3. Method 3: WooCommerce API (/wp-json/v1/product/feed) & REST/Legacy endpoints.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from ipaddress import ip_address
from typing import Any

from django.conf import settings
from django.http import HttpRequest

log = logging.getLogger(__name__)

# Known official SnappPay / SearchWise Crawler IP addresses
SNAPPAY_OFFICIAL_IPS = {
    "185.206.93.115",
    "185.206.94.25",
    "37.152.176.176",
    "188.121.106.231",
}

LOGS_DIR = settings.LOGS_DIR
LEGACY_JSONL_FILE = settings.BASE_DIR / "logs" / "snappay_access.jsonl"
ACCESS_LOG_FILE = LOGS_DIR / "snappay_access.log"
ACCESS_JSONL_FILE = LOGS_DIR / "snappay_access.jsonl"


def read_access_logs():
    """Keep pre-existing logs visible after moving writes to the persistent volume."""
    for path in dict.fromkeys((LEGACY_JSONL_FILE, ACCESS_JSONL_FILE)):
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as file:
            for line in file:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict):
                    yield entry


def _valid_ips(header: str):
    for value in header.split(",", 16)[:16]:
        try:
            yield ip_address(value.strip())
        except ValueError:
            continue


def get_real_ip(request: HttpRequest) -> str:
    """Use the frontend's ingress metadata before considering the backend hop."""
    meta = request.META
    forwarded = list(_valid_ips(meta.get("HTTP_X_SEARCHWISE_CLIENT_IP", "")))
    if not forwarded and request.path.endswith("/SearchEngine/SiteMaps"):
        forwarded = list(_valid_ips(meta.get("HTTP_X_CALLER_IP", "")))  # older frontend
    for address in forwarded:
        if address.is_global and not address.is_multicast:
            return str(address)

    direct = [address for name in ("HTTP_CF_CONNECTING_IP", "HTTP_X_REAL_IP", "HTTP_X_FORWARDED_FOR", "REMOTE_ADDR")
              for address in _valid_ips(meta.get(name, ""))]
    for address in direct:
        if address.is_global and not address.is_multicast:
            return str(address)
    candidates = forwarded or direct
    return str(candidates[0]) if candidates else "unknown"


def log_snappay_access(
    method_name: str,
    request: HttpRequest | None = None,
    status_code: int = 200,
    items_count: int | None = None,
    client_ip: str | None = None,
    user_agent: str | None = None,
    params: dict[str, Any] | None = None,
    note: str = "",
) -> None:
    """
    Record an access log entry for SnappPay requests.
    Thread-safe and fails gracefully without disrupting the request cycle.
    """
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")

        # Determine IP
        ip = client_ip or (get_real_ip(request) if request else "unknown")
        is_snappay = ip in SNAPPAY_OFFICIAL_IPS

        # Determine HTTP info
        verb = getattr(request, "method", "GET") if request else "GET"
        path = getattr(request, "path", "") if request else ""
        ua = user_agent or (request.META.get("HTTP_USER_AGENT", "") if request else "")
        ua = " ".join(ua.splitlines())[:512]

        # Summary of params
        query_str = ""
        if request and hasattr(request, "GET") and request.GET:
            query_str = "&".join(f"{k}={v}" for k, v in request.GET.items())

        entry_data = {
            "timestamp": timestamp_str,
            "epoch": int(time.time()),
            "channel": method_name,
            "ip": ip,
            "is_snappay_ip": is_snappay,
            "verb": verb,
            "path": path,
            "query": query_str,
            "params": params or {},
            "status_code": status_code,
            "items_count": items_count if items_count is not None else -1,
            "user_agent": ua,
            "note": note,
        }

        # 1. Plain text format for human inspection
        tag = "[SNAPPAY-IP]" if is_snappay else "[OTHER-IP]"
        line = (
            f"[{timestamp_str}] {tag} [{ip}] [{method_name}] {verb} {path} "
            f"| Status: {status_code} | Count: {items_count if items_count is not None else '-'} "
            f"| Params: {params or query_str or '-'} | UA: {ua[:80]}\n"
        )

        with open(ACCESS_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)

        # 2. JSONL format for machine parsing
        with open(ACCESS_JSONL_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry_data, ensure_ascii=False) + "\n")

    except Exception as exc:
        log.warning("Failed to write SnappPay access log: %s", exc)
