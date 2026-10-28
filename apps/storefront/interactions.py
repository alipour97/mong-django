"""
What signed-in customers (and visitors) add on the site, as api.mong.ir took it.

New product and article comments wait for approval in the admin (status 0).
A product comment is marked "buyer" when the customer has bought the product
(any Mong sale in Samian, store or online).

    POST Comment/add?productId=&featureValueId= {comment, score, title, isAnonymous, parentId}   (customer)
    POST Comment/Reaction {commentId, liked}        liked null undoes the reaction            (customer)
    POST Article/AddComment {articleId, comment, title, isAnonymous, ...}                       (customer)
    POST Article/AddArticleLike/<articleId>/likes?liked=                                       (customer)
    POST Cooperation/CooperationRequestSubmit  multipart: FirstName, LastName, CellPhone, Email, Address,
         JobPositionTitle, AdditionalInfo, ResumeFile (pdf/doc/docx)
    POST ThirdPartyLog/AddThirdPartyLog/AddThirdPartyLog {thirdPartyName, redirectUrl, productVariantId, utm*...}
"""
from __future__ import annotations

import uuid
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.samian.models import SamianSalesRow
from apps.website.models import (
    Article, ArticleComment, ArticleLike, CooperationRequest, MediaAttachment, Product, ProductComment, ProductCommentLike,
    ProductSamianLink, ThirdPartyLog,
)

from . import blog
from .account import CustomerView, _mobile, answer
from .views import PublicView

RESUME_TYPES = {"pdf", "doc", "docx"}
RESUME_MAX_BYTES = 10 * 1024 * 1024
MSG_ADDED = "اطلاعات با موفقیت افزوده شدند."


def _int(value) -> int | None:
    return int(value) if str(value if value is not None else "").lstrip("-").isdigit() else None


def _text(d: dict, key: str, limit: int | None = None) -> str:
    value = str(d.get(key) or "").strip()
    return value[:limit] if limit else value


def bought(customer, product_id: int) -> bool:
    if not customer.samian_customer_id:
        return False
    samian_product = ProductSamianLink.objects.filter(product_id=product_id).values_list("samian_product_id", flat=True).first()
    return bool(samian_product) and SamianSalesRow.objects.filter(
        transaction__samian_customer_id=customer.samian_customer_id, samian_product__samian_id=samian_product, is_return=False,
    ).exists()


class ProductCommentAddView(CustomerView):
    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        pid = _int(request.query_params.get("productId"))
        if not pid or not Product.objects.filter(id=pid, is_deleted=False).exists():
            return answer(False, 400, "شناسه کالا صحیح نمی باشد.")
        comment = _text(d, "comment")
        if not comment:
            return answer(False, 400, "متن نظر الزامی است")
        parent = ProductComment.objects.filter(id=_int(d.get("parentId")), product_id=pid, is_deleted=False).first() if d.get("parentId") else None
        score = min(max(float(d.get("score") or 0), 0), 5) if str(d.get("score") or "0").replace(".", "", 1).isdigit() else 0
        ProductComment.objects.create(
            product_id=pid, parent=parent, commenter_id=request.user.id, title=_text(d, "title", 512), comment=comment,
            score=score, is_admin_comment=False, is_buyer=bought(request.user, pid), is_anonymous=bool(d.get("isAnonymous")),
            is_active=False, status=0, created=timezone.now(),
        )
        return answer(True, message=MSG_ADDED)


class ProductCommentReactionView(CustomerView):
    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        comment = ProductComment.objects.filter(id=_int(d.get("commentId")), is_deleted=False, status=1).first()
        if not comment:
            return answer(False, 400, "نظر مورد نظر یافت نشد.")
        like = ProductCommentLike.objects.filter(comment=comment, customer_id=request.user.id).first()
        liked = d.get("liked")
        if liked is None:  # undo
            if like and not like.is_deleted:
                like.is_deleted, like.last_modified = True, timezone.now()
                like.save(update_fields=["is_deleted", "last_modified"])
            return answer(True, message="پروسه با موفقیت انجام شد.")
        like = like or ProductCommentLike(comment=comment, customer_id=request.user.id, created=timezone.now())
        like.liked, like.is_deleted, like.last_modified = bool(liked), False, timezone.now()
        like.save()
        return answer(True, message="پروسه با موفقیت انجام شد.")


class ArticleCommentAddView(CustomerView):
    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        article = blog.visible().filter(id=_int(d.get("articleId"))).first()
        if not article:
            return answer(None, 400, "مقاله مورد نظر یافت نشد.")
        comment = _text(d, "comment")
        if not comment:
            return answer(None, 400, "متن نظر الزامی است")
        ArticleComment.objects.create(
            article=article, commenter_id=request.user.id, title=_text(d, "title", 512), comment=comment,
            is_admin_comment=False, is_anonymous=bool(d.get("isAnonymous")), is_active=False, status=0, created=timezone.now(),
        )
        return answer(True, message="کامنت با موفقیت افزوده شد.")


class ArticleLikeView(CustomerView):
    def post(self, request, article_id: int):
        article = blog.visible().filter(id=article_id).first()
        if not article:
            return answer(False, 400, "مقاله مورد نظر یافت نشد.")
        liked = str(request.query_params.get("liked", "true")).lower() != "false"
        like = ArticleLike.objects.filter(article=article, customer_id=request.user.id).first()
        like = like or ArticleLike(article=article, customer_id=request.user.id, created=timezone.now())
        like.liked, like.is_deleted, like.last_modified = liked, False, timezone.now()
        like.save()
        return answer(True, message="عملیات با موفقیت انجام شد.")


def _save_resume(uploaded) -> str:
    """Stores the resume under MEDIA_ROOT/resumes/ with a random name; returns its public URL."""
    now = timezone.localtime()
    relative = Path("resumes") / f"{now:%Y}" / f"{now:%m}" / f"{uuid.uuid4().hex}{Path(uploaded.name).suffix.lower()}"
    target = Path(settings.MEDIA_ROOT) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as out:
        for chunk in uploaded.chunks():
            out.write(chunk)
    return f"{settings.PUBLIC_MEDIA_BASE_URL.rstrip('/')}{settings.MEDIA_URL}{relative.as_posix()}"


class CooperationSubmitView(PublicView):
    def post(self, request):
        d = request.data
        first, last = _text(d, "FirstName", 150), _text(d, "LastName", 150)
        mobile = _mobile(d.get("CellPhone"))
        if not first or not last or not mobile:
            return answer(None, 400, "نام، نام خانوادگی و موبایل معتبر الزامی است")
        resume = request.FILES.get("ResumeFile")
        if resume is not None:
            if Path(resume.name or "").suffix.lower().lstrip(".") not in RESUME_TYPES:
                return answer(None, 409, "فرمت فایل مورد نظر معتبر نیست")
            if resume.size > RESUME_MAX_BYTES:
                return answer(None, 409, "حجم فایل رزومه حداکثر ۱۰ مگابایت است")
        now = timezone.now()
        with transaction.atomic():
            req = CooperationRequest.objects.create(
                first_name=first, last_name=last, cellphone=mobile, email=_text(d, "Email", 254), address=_text(d, "Address"),
                job_position_title=_text(d, "JobPositionTitle", 255), additional_info=_text(d, "AdditionalInfo"), created=now,
            )
            uploaded = False
            if resume is not None:
                MediaAttachment.objects.create(
                    table=MediaAttachment.Table.COOPERATION_REQUESTS, record_id=req.id, media_url=_save_resume(resume), created=now,
                )
                uploaded = True
        return answer({"cooperationRequestId": req.id, "resumeFileUploaded": uploaded}, message="درخواست همکاری شما با موفقیت ثبت شد")


class ThirdPartyLogView(PublicView):
    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        ip = (request.META.get("HTTP_X_REAL_IP") or request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0]
              or request.META.get("REMOTE_ADDR") or "").strip()
        ThirdPartyLog.objects.create(
            third_party_name=_text(d, "thirdPartyName", 128), redirect_url=_text(d, "redirectUrl", 2000), ip_address=ip[:64],
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:1000], user_id=_int(d.get("userId")),
            product_variant_id=_int(d.get("productVariantId")), price_before_reduction=_int(d.get("priceBeforeReduction")),
            reduction=d.get("reduction") if isinstance(d.get("reduction"), (int, float)) else None,
            image_link=_text(d, "imageLink", 2000), utm_source=_text(d, "utmSource", 255), utm_medium=_text(d, "utmMedium", 255),
            utm_campaign=_text(d, "utmCampaign", 255), created=timezone.now(),
        )
        return answer(True, message="Third-party log added successfully.")
