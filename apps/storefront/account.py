"""
Customer sign-in and account (Authentication/*, Customer/*), as api.mong.ir.

Sign-in is by SMS code or, once the customer has set one, by password. A code
lasts 5 minutes; while it is valid no new one is sent (409 with the seconds
left, which the site uses to resume the code step), and it allows 5 tries.
Sign-up needs a code too. Tokens are HS512 JWTs valid 30 days, sent back as
"Authorization: Bearer"; a missing or bad token answers 401, on which the site
signs the customer out.

These answer with the HTTP status of statusCode, as the old API did (the site
reads 409 from the HTTP status).

    POST Authentication/CustomerAthenticateInfo {cellPhone}   -> {userIsExist, hasPassword}
    POST Authentication/SendOtpCode {cellPhone}               -> {messageStatus, userIsExist, hasPassword, seconds}
    POST Authentication/CustomerAuthenticate {cellPhone, password, isOtp} -> token
    POST Customer/SignUp {cellPhone, confirmationCode, firstName?, lastName?, email?, password?} -> token
    GET  Customer/GetMyProfile | Customer/GetAllJob | Customer/GetCustomerAddress | Customer/GetCustomerFavoriteProduct
    POST Customer/UpdateMyProfile | Customer/UpdateMyPassword | Customer/AddCustomerAddress | Customer/UpdateCustomerAddress
    GET  Customer/SoftDeleteCustomerAddress?id= | Customer/DeleteFavoriteProduct?id=<productId> | Customer/ActivateBulletin?email=
    POST Customer/AddFavoriteProduct {productId, firstItemId (color), secondItemId (size)}
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import timedelta

import jwt
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission
from rest_framework.views import APIView

from apps import smsir
from apps.website.models import City, Customer, CustomerAddress, CustomerFavoriteProduct, CustomerOtp, Job, Product, Province

from . import catalog
from .envelope import MSG_FETCHED, envelope
from .views import PublicView

OTP_MINUTES = 5
OTP_MAX_ATTEMPTS = 5
TOKEN_DAYS = 30
ISSUER = "mong-site"
ALGORITHM = "HS512"

MSG_UPDATED = "اطلاعات با موفقیت بروزرسانی شدند."
MSG_NO_USER = "اطلاعات کاربر مورد نظر یافت نشد."
MSG_BAD_MOBILE = "شماره موبایل معتبر نیست."
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def answer(data=None, status: int = 200, message: str = MSG_FETCHED):
    return envelope(data, status_code=status, message=message, http_status=status)


# -----------------------------------------------------------------------------
# Tokens
# -----------------------------------------------------------------------------
def _key() -> bytes:
    return hashlib.sha512((settings.SECRET_KEY + ":customer").encode()).digest()


def issue_token(customer: Customer) -> dict:
    now = timezone.now()
    expires = now + timedelta(days=TOKEN_DAYS)
    token = jwt.encode(
        {"sub": str(customer.pk), "iss": ISSUER, "iat": int(now.timestamp()), "nbf": int(now.timestamp()),
         "exp": int(expires.timestamp())},
        _key(), algorithm=ALGORITHM,
    )
    # The site keeps only the access token; the refresh token is there for the response shape.
    return {"token": token, "tokenType": "Bearer", "issuedAt": now.isoformat(), "expires": expires.isoformat(),
            "refreshToken": secrets.token_hex(32)}


class CustomerTokenAuthentication(BaseAuthentication):
    """Authorization: Bearer <customer token> -> request.user is the Customer."""

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if len(parts) != 2 or parts[0].lower() != b"bearer":
            return None
        try:
            claims = jwt.decode(parts[1].decode(errors="ignore"), _key(), algorithms=[ALGORITHM], issuer=ISSUER,
                                options={"require": ["exp", "sub"]})
        except jwt.PyJWTError:
            raise AuthenticationFailed("توکن نامعتبر است")
        customer = Customer.objects.filter(pk=claims.get("sub"), is_deleted=False, is_active=True).first()
        if customer is None:
            raise AuthenticationFailed("کاربر یافت نشد")
        return customer, None

    def authenticate_header(self, request):
        return "Bearer"


class IsCustomer(BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.user, Customer)


class CustomerView(APIView):
    authentication_classes = [CustomerTokenAuthentication]
    permission_classes = [IsCustomer]

    def permission_denied(self, request, message=None, code=None):
        # No token: 401 as well, so the site signs out like it did before.
        raise AuthenticationFailed("لطفا دوباره وارد شوید. کاربر قابل شناسایی نیست.")


# -----------------------------------------------------------------------------
# Sign-in
# -----------------------------------------------------------------------------
def _mobile(value) -> str | None:
    mobile = smsir.normalize_mobile("".join(ch for ch in str(value or "") if ch.isdigit() or ch == "+"))
    return mobile if len(mobile) == 11 and mobile.startswith("09") else None


def _customer(mobile: str) -> Customer | None:
    return Customer.objects.filter(cellphone=mobile, is_deleted=False).first()


def _who(mobile: str) -> dict:
    c = _customer(mobile)
    return {"userIsExist": c is not None, "hasPassword": bool(c and c.password)}


def _live_code(mobile: str) -> CustomerOtp | None:
    return CustomerOtp.objects.filter(cellphone=mobile, used=False, expires__gt=timezone.now()).first()


def _check_code(mobile: str, code) -> bool:
    otp = _live_code(mobile)
    if not otp or otp.attempts >= OTP_MAX_ATTEMPTS:
        return False
    if not check_password(str(code or "").strip(), otp.code_hash):
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        return False
    otp.used = True
    otp.save(update_fields=["used"])
    return True


class AuthenticateInfoView(PublicView):
    def post(self, request):
        mobile = _mobile(request.data.get("cellPhone"))
        if not mobile:
            return answer({"userIsExist": False, "hasPassword": False}, 400, MSG_BAD_MOBILE)
        return answer({"messageStatus": False, "seconds": 0, **_who(mobile)}, message="دریافت اطلاعات با موفقیت انجام شد.")


class SendOtpView(PublicView):
    def post(self, request):
        mobile = _mobile(request.data.get("cellPhone"))
        if not mobile:
            return answer({"messageStatus": False, "seconds": 0, "userIsExist": False, "hasPassword": False}, 400, MSG_BAD_MOBILE)
        now = timezone.now()
        if live := _live_code(mobile):
            left = int((live.expires - now).total_seconds()) + 1
            return answer({"messageStatus": False, "seconds": left, **_who(mobile)}, 409, "کد قبلا برای شما ارسال شده است.")
        code = f"{secrets.randbelow(10_000):04d}"
        otp = CustomerOtp.objects.create(cellphone=mobile, code_hash=make_password(code), expires=now + timedelta(minutes=OTP_MINUTES))
        CustomerOtp.objects.filter(created__lt=now - timedelta(days=1)).delete()
        if not smsir.send_otp(mobile, code):
            otp.delete()
            return answer({"messageStatus": False, "seconds": 0, **_who(mobile)}, 500, "هنگام ارسال پیامک خطای نامشخصی رخ داده است.")
        return answer({"messageStatus": True, "seconds": OTP_MINUTES * 60, **_who(mobile)}, message="کد تایید ارسال شد.")


class AuthenticateView(PublicView):
    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        mobile = _mobile(d.get("cellPhone"))
        customer = _customer(mobile) if mobile else None
        if customer is None:
            return answer(None, 401, "ورود شما با خطا مواجه شد.")
        if not customer.is_active:
            return answer(None, 403, "دسترسی شما مسدود شده است")
        password = str(d.get("password") or "")
        if d.get("isOtp"):
            if not _check_code(mobile, password):
                return answer(None, 404, "اطلاعات ورود صحیح نمی باشد")
        elif not customer.check_password(password):
            return answer(None, 404, "رمز عبور اشتباه است.")
        return answer(issue_token(customer), message="ورود شما موفقیت آمیز بود")


class SignUpView(PublicView):
    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        mobile = _mobile(d.get("cellPhone"))
        if not mobile:
            return answer(None, 400, MSG_BAD_MOBILE)
        if not _check_code(mobile, d.get("confirmationCode")):
            return answer(None, 403, "کد تایید صحیح نمی باشد لطفا دوباره درخواست دهید.")
        customer = _customer(mobile)
        if customer is None:  # an existing account (also a deleted one) is just signed in, as before
            customer = Customer.objects.filter(cellphone=mobile).first() or Customer(cellphone=mobile, created=timezone.now())
            customer.is_deleted, customer.is_active = False, True
            customer.first_name = str(d.get("firstName") or customer.first_name).strip()
            customer.last_name = str(d.get("lastName") or customer.last_name).strip()
            email = str(d.get("email") or "").strip()
            if EMAIL_RE.match(email):
                customer.email = email
            if d.get("password"):
                customer.set_password(str(d["password"]))
            customer.last_modified = timezone.now()
            try:
                customer.save()
            except IntegrityError:
                return answer(None, 400, "هنگام ثبت نام خطایی رخ داده است.")
        if not customer.is_active:
            return answer(None, 403, "دسترسی شما مسدود شده است")
        return answer(issue_token(customer), message="ثبت نام با موفقیت انجام شد.")


# -----------------------------------------------------------------------------
# Profile
# -----------------------------------------------------------------------------
def _profile(c: Customer) -> dict:
    birth = c.birth_date.isoformat() if c.birth_date else None
    return {
        "id": c.id, "CustomerId": c.id, "lastModifiedBy": None, "firstName": c.first_name, "lastName": c.last_name,
        "cellPhone": c.cellphone, "email": c.email, "isActive": c.is_active, "isTowFactorAuthentication": False,
        "nationalCode": c.national_code or None, "birthDate": birth, "birthday": birth, "jobId": c.job_id,
        "hasPassword": bool(c.password), "isBulletinEnable": c.is_bulletin_enabled,
    }


class ProfileView(CustomerView):
    def get(self, request):
        return answer(_profile(request.user))


class UpdateProfileView(CustomerView):
    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        c: Customer = request.user
        # The mobile is the sign-in identity and is not changed here.
        for key, field in (("firstName", "first_name"), ("lastName", "last_name"), ("nationalCode", "national_code")):
            if d.get(key) is not None:
                setattr(c, field, str(d[key]).strip())
        if d.get("email") is not None:
            email = str(d["email"]).strip()
            if email and not EMAIL_RE.match(email):
                return answer(False, 400, "ایمیل نامعتبر است")
            c.email = email
        if "birthDate" in d:
            raw = str(d.get("birthDate") or "")
            c.birth_date = (parse_date(raw[:10]) or (parse_datetime(raw) and parse_datetime(raw).date())) if raw else None
        if "jobId" in d:
            job = d.get("jobId")
            c.job_id = int(job) if str(job or "").isdigit() and Job.objects.filter(id=int(job)).exists() else None
        c.last_modified = timezone.now()
        c.save()
        return answer(True, message=MSG_UPDATED)


class UpdatePasswordView(CustomerView):
    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        c: Customer = request.user
        new = str(d.get("newPassword") or "")
        if c.password and not c.check_password(str(d.get("oldPassword") or "")):
            return answer(False, 404, "رمز عبور اشتباه است.")
        if len(new) < 6:
            return answer(False, 400, "رمز عبور باید حداقل ۶ کاراکتر باشد")
        if d.get("confirmPassword") is not None and d["confirmPassword"] != new:
            return answer(False, 400, "تکرار رمز عبور با رمز عبور یکسان نیست")
        c.set_password(new)
        c.last_modified = timezone.now()
        c.save(update_fields=["password", "last_modified"])
        return answer(True, message=MSG_UPDATED)


class JobsView(PublicView):
    def get(self, request):
        return answer([{"id": j.id, "title": j.title} for j in Job.objects.filter(is_deleted=False).order_by("id")])


class BulletinView(CustomerView):
    def get(self, request):
        email = (request.query_params.get("email") or "").strip()
        if not email:
            return answer(None, 400, "ایمیل اجباری است")
        if not EMAIL_RE.match(email):
            return answer(None, 400, "ایمیل نامعتبر است")
        c: Customer = request.user
        if Customer.objects.filter(email__iexact=email, is_deleted=False).exclude(id=c.id).exists():
            return answer(None, 409, "ایمیل وارد شده مطعلق به شخص دیگری است")
        data = {"profileEmailChanged": c.email.lower() != email.lower(), "bulletinIsAlreadyActive": c.is_bulletin_enabled}
        c.email = email
        if not c.is_bulletin_enabled:
            c.is_bulletin_enabled, c.bulletin_subscription_date = True, timezone.now()
        c.save(update_fields=["email", "is_bulletin_enabled", "bulletin_subscription_date"])
        return answer(data, message="دریافت خبرنامه با موفقیت برای شما فعال شد")


# -----------------------------------------------------------------------------
# Addresses
# -----------------------------------------------------------------------------
def _address(a: CustomerAddress, provinces: dict, cities: dict) -> dict:
    return {
        "id": a.id, "lastModifiedBy": None, "customerId": a.customer_id, "isDefault": a.is_default, "address": a.address,
        "provinceId": a.province_id, "provinceTitle": provinces.get(a.province_id, ""), "cityId": a.city_id,
        "cityTitle": cities.get(a.city_id, ""), "isMyselfRecipient": a.is_myself_recipient, "firstName": a.first_name,
        "lastName": a.last_name, "zipCode": a.zip_code, "mobile": a.mobile, "title": a.title,
        "latitude": float(a.latitude) if a.latitude is not None else None,
        "longitude": float(a.longitude) if a.longitude is not None else None,
    }


def _addresses(customer: Customer) -> list[dict]:
    rows = list(customer.addresses.filter(is_deleted=False).order_by("-is_default", "-id"))
    provinces = dict(Province.objects.filter(id__in={a.province_id for a in rows}).values_list("id", "name"))
    cities = dict(City.objects.filter(id__in={a.city_id for a in rows}).values_list("id", "name"))
    return [_address(a, provinces, cities) for a in rows]


def _fill_address(a: CustomerAddress, d: dict):
    """Copies the payload onto the address; returns an error message or None."""
    province = Province.objects.filter(id=d.get("provinceId"), is_deleted=False).first() if d.get("provinceId") else None
    city = City.objects.filter(id=d.get("cityId"), is_deleted=False).first() if d.get("cityId") else None
    if not province or not city or city.province_id != province.id:
        return "استان و شهر را انتخاب کنید"
    if not str(d.get("address") or "").strip():
        return "آدرس الزامی است"
    mobile = _mobile(d.get("mobile")) if d.get("mobile") else None
    if d.get("mobile") and not mobile:
        return MSG_BAD_MOBILE
    a.province, a.city = province, city
    a.address, a.title = str(d.get("address")).strip(), str(d.get("title") or "").strip()
    a.zip_code = "".join(ch for ch in str(d.get("zipCode") or "") if ch.isdigit())[:10]
    a.first_name, a.last_name = str(d.get("firstName") or "").strip(), str(d.get("lastName") or "").strip()
    a.mobile = mobile or ""
    a.is_myself_recipient = bool(d.get("isMyselfRecipient", True))
    a.latitude = d.get("latitude") if isinstance(d.get("latitude"), (int, float)) else None
    a.longitude = d.get("longitude") if isinstance(d.get("longitude"), (int, float)) else None
    a.is_default = bool(d.get("isDefault"))
    a.last_modified = timezone.now()
    return None


def _save_address(customer: Customer, a: CustomerAddress) -> None:
    with transaction.atomic():
        has_default = customer.addresses.filter(is_deleted=False, is_default=True).exclude(id=a.id).exists()
        if a.is_default:
            customer.addresses.filter(is_default=True).exclude(id=a.id).update(is_default=False)
        elif not has_default:
            a.is_default = True  # the first address is the default one
        a.save()


class AddressesView(CustomerView):
    def get(self, request):
        rows = _addresses(request.user)
        return answer(rows, message=MSG_FETCHED if rows else "آدرسی وجود ندارد")


class AddAddressView(CustomerView):
    def post(self, request):
        a = CustomerAddress(customer=request.user, created=timezone.now())
        if error := _fill_address(a, request.data if isinstance(request.data, dict) else {}):
            return answer(None, 400, error)
        _save_address(request.user, a)
        return answer(next(x for x in _addresses(request.user) if x["id"] == a.id), message="اطلاعات با موفقیت افزوده شدند.")


class UpdateAddressView(CustomerView):
    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        a = request.user.addresses.filter(id=d.get("id"), is_deleted=False).first() if str(d.get("id") or "").isdigit() else None
        if not a:
            return answer(False, 404, "آدرس وجود ندارد")
        if error := _fill_address(a, d):
            return answer(False, 400, error)
        _save_address(request.user, a)
        return answer(True, message=MSG_UPDATED)


class DeleteAddressView(CustomerView):
    def get(self, request):
        aid = request.query_params.get("id")
        a = request.user.addresses.filter(id=aid, is_deleted=False).first() if str(aid or "").isdigit() else None
        if not a:
            return answer(False, 400, "آدرس وجود ندارد")
        with transaction.atomic():
            a.is_deleted, a.last_modified = True, timezone.now()
            a.save(update_fields=["is_deleted", "last_modified"])
            if a.is_default and (other := request.user.addresses.filter(is_deleted=False).order_by("-id").first()):
                other.is_default = True
                other.save(update_fields=["is_default"])
        return answer(True, message="اطلاعات با موفقیت حذف شدند.")


# -----------------------------------------------------------------------------
# Favorites
# -----------------------------------------------------------------------------
def _int(value) -> int | None:
    return int(value) if str(value or "").lstrip("-").isdigit() else None


class FavoritesView(CustomerView):
    """The favorite products as Product/GetById shows them; products no longer on the site are left out."""

    def get(self, request):
        ids = list(request.user.favorites.filter(is_deleted=False).order_by("-id").values_list("product_id", flat=True))
        listed = {r.id for r in catalog.listing_rows()}
        ids = [i for i in dict.fromkeys(ids) if i in listed]
        bundle = catalog.ProductBundle.load(ids)
        return answer([bundle.full_detail(i) for i in ids if i in bundle.products and not bundle.products[i].is_deleted])


class AddFavoriteView(CustomerView):
    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        pid = _int(d.get("productId"))
        if not pid or not Product.objects.filter(id=pid, is_deleted=False).exists():
            return answer(False, 400, "شناسه کالا صحیح نمی باشد.")
        fav = request.user.favorites.filter(product_id=pid).first()
        if fav and not fav.is_deleted:
            return answer(False, 400, "این کالا قبلا به مورد علاقه شما اضافه شده.")
        fav = fav or CustomerFavoriteProduct(customer=request.user, product_id=pid, created=timezone.now())
        fav.color_id, fav.size_id = _int(d.get("firstItemId")), _int(d.get("secondItemId"))
        fav.is_deleted, fav.last_modified = False, timezone.now()
        fav.save()
        return answer(True, message="کالای مورد نظر به علاقه مندی های شما اضافه شد.")


class DeleteFavoriteView(CustomerView):
    def get(self, request):
        n = request.user.favorites.filter(product_id=_int(request.query_params.get("id")), is_deleted=False).update(
            is_deleted=True, last_modified=timezone.now())
        return answer(True, message="اطلاعات با موفقیت حذف شدند.") if n else answer(False, 400, "این محصول مورد علاقه شما نیست.")
