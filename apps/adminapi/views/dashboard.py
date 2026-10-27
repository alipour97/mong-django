"""Dashboard/* — the admin home page."""
from __future__ import annotations

from django.utils import timezone

from ..envelope import ok
from .auth import AdminView


class DateView(AdminView):
    """GET Dashboard/Date -> {"date"}: the server's local time; the panel's date pickers start from it."""

    def get(self, request):
        return ok({"date": timezone.localtime().replace(tzinfo=None).isoformat()})
