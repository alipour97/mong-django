"""
Customer/*, Job/JobDropdown and Favorite/* — the site's customers.

A customer's "invoices" are their Mong purchases in Samian (every branch):
the sales of the Samian customer linked to them by mobile. Site invoices come
with the order phase.

Customers sign in with a one-time code, so the password the panel may send on
add/update is ignored. Gift cards (Customer/GetAllGiftCard) are in Samian
(retail/giftcard) and wait for the gift card phase.

    GET  Customer/GetCustomerLablesReport
    GET  Customer/GetCustomers?RegistrationDateFrom=&RegistrationDateTo=&JobId=&SearchText=&InvoiceNumberFrom=&InvoiceNumberTo=&IsActive=&pageNumber=&pageSize=
    GET  Customer/<id>
    POST Customer/Add {firstName, lastName, cellPhone, email}      POST Customer/Update?id= {..., isActive}
    POST Customer/Validation?cellphone=     GET Customer/SoftDelete?id=     POST Customer/BulletinMembers {search, pageNumber, pageSize}
    GET  Job/JobDropdown
    GET  Favorite/GetLable | GetFiveCustomer | GetFiveProduct | GetFavoriteMainCategories | GetFavoriteCategories?parentId= | GetFavoriteFeatures
"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
from urllib.parse import quote

from django.db.models import Count, Q
from django.utils import timezone

from apps.samian.models import SamianSalesTransaction
from apps.smsir import normalize_mobile
from apps.storefront import catalog
from apps.storefront.envelope import _g2j, jalali
from apps.website.models import Category, CompanyInfo, Customer, CustomerFavoriteProduct, FeatureValue, Job, Product

from .. import products as index
from ..envelope import fail, ok
from ..paging import paginated, to_bool, to_int
from .auth import AdminView
from .comments import _date

NOT_FOUND = "مشتری مورد نظر موجود نیست."


def _customers():
    return Customer.objects.filter(is_deleted=False)


def _purchases(customers) -> dict[int, int]:
    """customer id -> number of their Samian sales (Mong purchases)."""
    samian = {c.samian_customer_id: c.id for c in customers if c.samian_customer_id}
    counts = (
        SamianSalesTransaction.objects.filter(samian_customer_id__in=samian)
        .values_list("samian_customer_id").annotate(n=Count("pk"))
    )
    return {samian[sid]: n for sid, n in counts}


def _month_start():
    """Start of the current Persian month (Tehran time)."""
    day = timezone.localdate()
    while _g2j(day.year, day.month, day.day)[2] != 1:
        day -= timedelta(days=1)
    return timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.min.time()))


class LabelsView(AdminView):
    def get(self, request):
        qs = _customers()
        buyers = SamianSalesTransaction.objects.filter(
            samian_customer_id__in=qs.exclude(samian_customer=None).values("samian_customer_id")
        ).values("samian_customer_id").distinct().count()
        return ok({"result": {
            "totalCustomers": qs.count(), "activeCustomers": qs.filter(is_active=True).count(),
            "customersWithPurchases": buyers, "newCustomersLastMonth": qs.filter(created__gte=_month_start()).count(),
        }})


class ListView(AdminView):
    def get(self, request):
        q = request.query_params
        qs = _customers()
        if begin := _date(q.get("RegistrationDateFrom")):
            qs = qs.filter(created__gte=begin)
        if end := _date(q.get("RegistrationDateTo"), end=True):
            qs = qs.filter(created__lte=end)
        if (job := to_int(q.get("JobId"))) is not None:
            qs = qs.filter(job_id=job)
        if (active := to_bool(q.get("IsActive"))) is not None:
            qs = qs.filter(is_active=active)
        if search := (q.get("SearchText") or "").strip():
            qs = qs.filter(Q(first_name__icontains=search) | Q(last_name__icontains=search) | Q(cellphone__icontains=search) | Q(email__icontains=search))
        customers = list(qs.order_by("-created", "-id"))
        purchases = _purchases(customers)
        low, high = to_int(q.get("InvoiceNumberFrom")), to_int(q.get("InvoiceNumberTo"))
        if (low and low > 0) or (high and high > 0):
            customers = [
                c for c in customers
                if (not low or low <= 0 or purchases.get(c.id, 0) >= low) and (not high or high <= 0 or purchases.get(c.id, 0) <= high)
            ]
        jobs = dict(Job.objects.values_list("id", "title"))

        def item(c: Customer) -> dict:
            return {
                "customerId": c.id, "firstName": c.first_name, "lastName": c.last_name, "cellPhone": c.cellphone,
                "registrationDate": jalali(c.created, with_time=False), "isActive": c.is_active,
                "birthDate": jalali(c.birth_date, with_time=False), "jobTitle": jobs.get(c.job_id), "email": c.email,
                "invoiceCount": purchases.get(c.id, 0),
            }

        return ok({"result": paginated(customers, to_int(q.get("pageNumber"), 1), to_int(q.get("pageSize"), 10), item)})


class DetailView(AdminView):
    def get(self, request, customer_id: int):
        c = _customers().filter(id=customer_id).first()
        if not c:
            return fail("مشتری وجود ندارد.", 404)
        job = Job.objects.filter(id=c.job_id).values_list("title", flat=True).first()
        return ok({"result": {
            "customerId": c.id, "firstName": c.first_name, "lastName": c.last_name, "mobile": c.cellphone,
            "birthDate": jalali(c.birth_date, with_time=False) or "", "nationalCode": c.national_code, "job": job,
            "email": c.email, "isActive": c.is_active, "registrationDate": jalali(c.created, with_time=False),
            "invoiceCount": _purchases([c]).get(c.id, 0),
        }})


def _mobile(value) -> str:
    return normalize_mobile("".join(ch for ch in str(value or "") if ch.isdigit() or ch == "+"))


class AddView(AdminView):
    def post(self, request):
        d = request.data
        mobile = _mobile(d.get("cellPhone"))
        if len(mobile) != 11 or not mobile.startswith("09"):
            return fail("شماره موبایل نامعتبر است", 400)
        if Customer.objects.filter(cellphone=mobile).exists():
            return fail("مشتری با این اطلاعات قبلا ثبت نام کرده است.", 400)
        Customer.objects.create(
            first_name=(d.get("firstName") or "").strip(), last_name=(d.get("lastName") or "").strip(),
            cellphone=mobile, email=(d.get("email") or "").strip(), is_active=True, created=timezone.now(),
        )
        return ok({"result": True})


class UpdateView(AdminView):
    def post(self, request):
        c = _customers().filter(id=to_int(request.query_params.get("id"))).first()
        if not c:
            return fail(NOT_FOUND, 404)
        d = request.data
        if d.get("cellPhone") is not None:
            mobile = _mobile(d["cellPhone"])
            if len(mobile) != 11 or not mobile.startswith("09"):
                return fail("شماره موبایل نامعتبر است", 400)
            if Customer.objects.filter(cellphone=mobile).exclude(id=c.id).exists():
                return fail("این شماره موبایل برای مشتری دیگری ثبت شده است", 400)
            if mobile != c.cellphone:
                c.cellphone, c.samian_customer, c.samian_checked_at = mobile, None, None  # re-linked by the next customer sync
        for field, key in (("email", "email"), ("first_name", "firstName"), ("last_name", "lastName")):
            if d.get(key) is not None:
                setattr(c, field, str(d[key]).strip())
        if (active := to_bool(d.get("isActive"))) is not None:
            c.is_active = active
        c.last_modified = timezone.now()
        c.save()
        return ok({"result": True})


class ValidationView(AdminView):
    def post(self, request):
        mobile = _mobile(request.query_params.get("cellphone"))
        return ok({"result": not Customer.objects.filter(cellphone=mobile).exists()})


class DeleteView(AdminView):
    def get(self, request):
        n = _customers().filter(id=to_int(request.query_params.get("id"))).update(is_deleted=True, last_modified=timezone.now())
        return ok({"result": True}) if n else fail(NOT_FOUND, 404)


class BulletinView(AdminView):
    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        qs = _customers().filter(is_bulletin_enabled=True).exclude(email="")
        if search := (d.get("search") or "").strip():
            qs = qs.filter(Q(email__icontains=search) | Q(first_name__icontains=search) | Q(last_name__icontains=search))
        size, number = to_int(d.get("pageSize"), 1000), to_int(d.get("pageNumber"), 1)
        if size < 1 or number < 1:
            return fail("اندازه و شماره صفحه باید بیشتر از 0 باشد", 400)
        company = CompanyInfo.objects.filter(is_deleted=False).values_list("name", flat=True).first() or ""
        subject = quote(f"خبرنامه {company}")

        def item(c: Customer) -> dict:
            body = quote(f"سلام {c.first_name} {c.last_name} عزیز.\nبه مجموعه {company} خوش آمدید.")
            return {
                "id": c.id, "firstName": c.first_name, "lastName": c.last_name, "email": c.email,
                "personalMailLink": f"mailto:{c.email}?subject={subject}&body={body}",
            }

        page = paginated(list(qs.order_by("id")), number, size, item)
        emails = ";".join(x["email"] for x in page["items"])
        page["additionalInfo"] = f"mailto:{emails}?subject={subject}&body={quote(f'سلام همراهان عزیز مجموعه {company}')}"
        return ok({"result": page})


class JobsView(AdminView):
    def get(self, request):
        return ok({"result": [{"id": j.id, "title": j.title} for j in Job.objects.filter(is_deleted=False)]})


# -----------------------------------------------------------------------------
# Favorites: only products that are on the site
# -----------------------------------------------------------------------------
def _favorites() -> list[CustomerFavoriteProduct]:
    on_site = {r.id for r in index.admin_rows()}
    return [
        f for f in CustomerFavoriteProduct.objects.filter(is_deleted=False, customer__is_deleted=False)
        if f.product_id in on_site
    ]


def _categories(favs) -> tuple[dict[int, int | None], dict[int, Category]]:
    """product id -> category id, and the categories with their parents."""
    cat_of = dict(Product.objects.filter(id__in={f.product_id for f in favs}).values_list("id", "category_id"))
    cats = Category.objects.in_bulk(set(cat_of.values()) | set(
        Category.objects.filter(id__in=set(cat_of.values())).exclude(parent_id=None).values_list("parent_id", flat=True)
    ))
    return cat_of, cats


def _top(counter: Counter, cats: dict[int, Category]) -> list[dict]:
    return [
        {"id": cid or 0, "title": cats[cid].title if cid in cats else None, "productCount": n}
        for cid, n in counter.most_common()
    ]


class FavoriteLabelView(AdminView):
    def get(self, request):
        favs = _favorites()
        cat_of, cats = _categories(favs)
        by_cat = Counter(cat_of.get(f.product_id) for f in favs)
        by_main = Counter(cats[cat_of[f.product_id]].parent_id if cat_of.get(f.product_id) in cats else None for f in favs)
        top_cat, top_main = by_cat.most_common(1), by_main.most_common(1)
        return ok({"result": {
            "totalCustomer": len({f.customer_id for f in favs}), "totalProduct": len({f.product_id for f in favs}),
            "favoriteCategoryName": cats[top_cat[0][0]].title if top_cat and top_cat[0][0] in cats else None,
            "favoriteParentCategoryName": cats[top_main[0][0]].title if top_main and top_main[0][0] in cats else None,
        }})


class FavoriteMainCategoriesView(AdminView):
    def get(self, request):
        favs = _favorites()
        cat_of, cats = _categories(favs)
        counter = Counter(cats[cat_of[f.product_id]].parent_id if cat_of.get(f.product_id) in cats else None for f in favs)
        return ok({"result": _top(counter, cats)})


class FavoriteCategoriesView(AdminView):
    def get(self, request):
        parent = to_int(request.query_params.get("parentId"))
        favs = _favorites()
        cat_of, cats = _categories(favs)
        counter = Counter(
            cat_of[f.product_id] for f in favs
            if cat_of.get(f.product_id) in cats and cats[cat_of[f.product_id]].parent_id == parent
        )
        return ok({"result": _top(counter, cats)})


class FavoriteCustomersView(AdminView):
    def get(self, request):
        top = Counter(f.customer_id for f in _favorites()).most_common(5)
        customers = Customer.objects.in_bulk([cid for cid, _ in top])
        purchases = _purchases(customers.values())
        return ok({"result": [
            {
                "customerId": c.id, "firstName": c.first_name, "lastName": c.last_name, "isActive": c.is_active,
                "cellPhone": c.cellphone, "createDate": jalali(c.created, with_time=False),
                "invoiceCount": purchases.get(c.id, 0), "totalFavoriteCount": n,
            }
            for cid, n in top if (c := customers.get(cid))
        ]})


class FavoriteProductsView(AdminView):
    def get(self, request):
        top = Counter(f.product_id for f in _favorites()).most_common(5)
        titles = dict(Product.objects.filter(id__in=[pid for pid, _ in top]).values_list("id", "title"))
        return ok({"result": [{"id": pid, "title": titles.get(pid), "totalFavoriteCount": n} for pid, n in top]})


class FavoriteFeaturesView(AdminView):
    """The five most liked colors and sizes (the Dadehfa color and size the customer picked)."""

    def get(self, request):
        favs = _favorites()
        values = FeatureValue.objects.in_bulk({f.color_id for f in favs} | {f.size_id for f in favs})

        def top(ids, is_color: bool) -> list[dict]:
            return [
                {"key": values[i].name, "value": values[i].value, "isColor": is_color, "productCount": n}
                for i, n in Counter(i for i in ids if i in values).most_common(5)
            ]

        return ok({"result": top([f.color_id for f in favs], True) + top([f.size_id for f in favs], False)})
