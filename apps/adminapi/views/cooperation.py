"""
Cooperation/* — job applications from the cooperation page.

The lists answer {data, ...} like the old API; each state has its own list,
and every action sets the state of the given requests and appends the note.

    POST Cooperation/GetAllCooperationRequests {search, pageNumber, pageSize}
    POST Cooperation/Get{New,Seen,Picked,InProgressed,Accepted,Rejected}CooperationRequests {...}
    POST Cooperation/{Seen,Pick,NeedToReview,Accept,Reject} {cooperationIds, reason}
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.storefront import catalog
from apps.website.models import CooperationRequest, MediaAttachment

from ..envelope import fail, ok
from ..paging import int_list, paginated, to_int
from .auth import AdminView

S = CooperationRequest.State
LISTS = {"New": S.NEW, "Seen": S.SEEN, "Picked": S.PICK, "InProgressed": S.IN_PROGRESS, "Accepted": S.ACCEPT, "Rejected": S.REJECT}
ACTIONS = {
    "Seen": (S.SEEN, "مشاهده شده"), "Pick": (S.PICK, "باز شده"), "NeedToReview": (S.IN_PROGRESS, "درحال بررسی"),
    "Accept": (S.ACCEPT, "پذیرفته شده"), "Reject": (S.REJECT, "رد شده"),
}


def _dto(r: CooperationRequest, resumes: dict) -> dict:
    return {
        "id": r.id, "firstName": r.first_name, "lastName": r.last_name, "cellPhone": r.cellphone, "email": r.email,
        "jobPositionTitle": r.job_position_title, "address": r.address, "additionalInfo": r.additional_info,
        "submitTime": r.created.isoformat() if r.created else None, "state": r.state, "stateTitle": r.get_state_display(),
        "reason": r.reason, "lastTimeAction": r.last_time_action.isoformat() if r.last_time_action else None,
        "resumeFileUrl": resumes.get(r.id),
    }


class ListView(AdminView):
    state: int | None = None

    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        qs = CooperationRequest.objects.filter(is_deleted=False)
        if self.state is not None:
            qs = qs.filter(state=self.state)
        if search := (d.get("search") or "").strip():
            qs = qs.filter(Q(email__icontains=search) | Q(first_name__icontains=search) | Q(last_name__icontains=search))
        size, number = to_int(d.get("pageSize"), 1000), to_int(d.get("pageNumber"), 1)
        if size < 1 or number < 1:
            return fail("اندازه و شماره صفحه باید بیشتر از 0 باشد", 400)
        # Untouched ones first, then by the latest action or submission.
        rows = list(qs.order_by(F("last_time_action").asc(nulls_first=True), "-created", "-id"))
        page = paginated(rows, number, size)
        ids = [r.id for r in page["items"]]
        resumes = {}
        for att in MediaAttachment.objects.filter(table=MediaAttachment.Table.COOPERATION_REQUESTS, record_id__in=ids, is_deleted=False).order_by("id"):
            resumes.setdefault(att.record_id, catalog.media_dict(att)["mediaUrl"])
        page["items"] = [_dto(r, resumes) for r in page["items"]]
        return ok({"result": page})


class ActionView(AdminView):
    action: str = ""

    def post(self, request):
        state, label = ACTIONS[self.action]
        d = request.data if isinstance(request.data, dict) else {}
        ids = int_list(d.get("cooperationIds"))
        reason = (d.get("reason") or "").strip()
        now = timezone.now()
        with transaction.atomic():
            for r in CooperationRequest.objects.select_for_update().filter(id__in=ids, is_deleted=False):
                r.state, r.last_time_action, r.last_modified = state, now, now
                if reason:
                    r.reason = f"{r.reason}{label}: {reason}\n"
                r.save(update_fields=["state", "last_time_action", "last_modified", "reason"])
        return ok({"result": True})
