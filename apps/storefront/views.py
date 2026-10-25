"""
Storefront Web API v1 Views (samian.mong.ir / api/v1/...) matching docs/02_api_website.md and Next.js frontend requirements.
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from urllib.parse import unquote
from apps.samian.models import SamianProduct, SamianDepartment


class PrimaryConfigGetConfigView(APIView):
    """
    Handles:
    - GET /api/v1/PrimaryConfig/GetConfig/<key>
    - POST /api/v1/PrimaryConfig/Get with body {"key": "..."}
    Provides layout configs, metadata, homepage sorting rows, footer, etc.
    """
    permission_classes = [AllowAny]

    def _get_config_data(self, key_str: str):
        key_str = str(key_str).strip()

        if key_str == "sortRowsConfig":
            return []
        elif key_str == "websiteMetaData":
            return {
                "name": "مانگ",
                "description": "فروشگاه آنلاین پوشاک مانگ - شیک، مدرن و باکیفیت",
                "keywords": ["پوشاک", "مانگ", "لباس زنانه", "خرید آنلاین پوشاک"],
                "webSiteLogo": None,
                "favicon": None,
            }
        elif key_str == "footerConfig":
            return {
                "checkBoxes": {
                    "address": True,
                    "phoneNumbers": True,
                    "socialMedias": True,
                    "showFaq": True,
                    "showSupport": True,
                    "showNewsLetter": False,
                    "showCooperation": True,
                    "showTermOfUse": True,
                    "showDepartment": True,
                    "showContactUs": True,
                    "showAboutus": True,
                    "showContactus": True,
                },
                "enamad": None,
                "extraScripts": "",
            }
        elif key_str == "contactUsConfig2":
            return {
                "enabled": True,
                "featuredImage": "",
                "description": "فروشگاه آنلاین پوشاک مانگ - پشتیبانی و خدمات مشتریان",
                "address": "تهران",
                "lat": 35.6892,
                "lng": 51.3890,
                "phones": ["021-12345678"],
                "socials": {
                    "telegram": "",
                    "instagram": "",
                    "eitaa": "",
                    "bale": "",
                    "email": "info@mong.ir",
                    "whatsApp": "",
                },
            }
        elif key_str == "aboutUsConfigNew":
            return {
                "enabled": True,
                "featuredImage": "",
                "title": "درباره ما",
                "description": "فروشگاه پوشاک مانگ ارائه‌دهنده جدیدترین مدل‌های پوشاک زنانه، مردانه و بچگانه.",
            }
        elif key_str == "termsOfUseConfig":
            return {
                "enabled": True,
                "rules": [],
            }
        elif key_str == "faqConfig":
            return []
        elif key_str == "businessDepartments":
            return {
                "enabled": True,
                "featuredImage": "",
                "description": "شعبه‌های فروشگاه مانگ",
                "departmentList": [],
            }
        elif key_str == "CooperationConfig":
            return {
                "enabled": True,
                "description": "فرصت‌های همکاری با فروشگاه مانگ",
            }
        elif key_str == "adminMyThemeConfig":
            return {"theme": "default"}
        elif key_str == "departmentsConfig":
            return []
        elif key_str == "webSortOrder":
            return []
        else:
            return {}

    def get(self, request, key: str = ""):
        key_str = key or request.query_params.get("key", "")
        value = self._get_config_data(key_str)
        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "message": "موفق",
            "result": {
                "data": {
                    "id": 1,
                    "key": key_str,
                    "value": value,
                }
            },
            "data": value,
        }, status=status.HTTP_200_OK)

    def post(self, request, key: str = ""):
        key_str = key or request.data.get("key", "")
        value = self._get_config_data(key_str)
        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "message": "موفق",
            "result": {
                "data": {
                    "id": 1,
                    "key": key_str,
                    "value": value,
                }
            },
            "data": value,
        }, status=status.HTTP_200_OK)


class CompanyInfoView(APIView):
    """
    GET /api/v1/CompanyInfo/GetCompanyInfo
    """
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "result": {
                "data": {
                    "companyName": "فروشگاه پوشاک مانگ",
                    "title": "مانگ",
                    "telephone": "021-00000000",
                    "cellPhone": "09120000000",
                    "address": "تهران",
                    "email": "info@mong.ir",
                    "workTime": "شنبه تا پنج‌شنبه ۹ تا ۲۱",
                    "aboutUs": "فروشگاه پوشاک مانگ",
                }
            }
        })


class CategoryGetAllView(APIView):
    """
    GET /api/v1/Category/GetAll
    Returns categories structured from Samian departments.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        roots = SamianDepartment.objects.filter(parent__isnull=True)[:20]
        categories_data = []

        for root in roots:
            children = root.children.all()[:15]
            categories_data.append({
                "id": root.samian_id,
                "title": root.title,
                "slug": f"cat-{root.samian_id}",
                "isOnlineActive": True,
                "categories": [
                    {
                        "id": ch.samian_id,
                        "title": ch.title,
                        "slug": f"cat-{ch.samian_id}",
                        "isOnlineActive": True,
                        "categories": [],
                    }
                    for ch in children
                ],
            })

        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "result": {
                "data": {
                    "categories": categories_data
                }
            },
            "data": categories_data,
        })


class CategoryGetByIdView(APIView):
    """
    GET /api/v1/Category/GetById/<id>
    """
    permission_classes = [AllowAny]

    def get(self, request, category_id: int):
        try:
            dept = SamianDepartment.objects.get(samian_id=category_id)
            data = {
                "id": dept.samian_id,
                "title": dept.title,
                "slug": f"cat-{dept.samian_id}",
                "isOnlineActive": True,
                "categories": [
                    {
                        "id": ch.samian_id,
                        "title": ch.title,
                        "slug": f"cat-{ch.samian_id}",
                        "isOnlineActive": True,
                        "categories": [],
                    }
                    for ch in dept.children.all()[:20]
                ],
            }
        except SamianDepartment.DoesNotExist:
            data = {
                "id": category_id,
                "title": f"دسته‌بندی {category_id}",
                "slug": f"cat-{category_id}",
                "isOnlineActive": True,
                "categories": [],
            }

        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "result": {
                "data": data
            },
            "data": data,
        })


class ProductGetAllView(APIView):
    """
    POST /api/v1/Product/GetAll
    Filterable product listing for storefront.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        page_num = int(request.data.get("pageNumber", 1))
        page_size = int(request.data.get("pageSize", 20))
        offset = (page_num - 1) * page_size

        qs = SamianProduct.objects.filter(is_active=True).order_by("-samian_id")
        total_count = qs.count()
        products = qs[offset : offset + page_size]

        items = []
        for p in products:
            items.append({
                "id": p.samian_id,
                "productName": p.name,
                "slug": f"product-{p.subcode or p.samian_id}",
                "product_Base_Price": 0,
                "product_base_reduction": 0,
                "priceAfterReduction": 0,
                "mainImages": [],
                "hasColor": p.colors.exists(),
            })

        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "data": {
                "items": items,
                "totalCount": total_count,
                "pageNumber": page_num,
                "pageSize": page_size,
            }
        })


class SettingGetSettingView(APIView):
    """
    GET /api/v1/Setting/GetSetting
    """
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "data": {
                "freeShippingThreshold": 15000000,
                "shippingCost": 650000,
                "isStoreOpen": True,
            }
        })


class SliderGetAllView(APIView):
    """
    GET /api/v1/Slider/GetAll
    """
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "data": []
        })


class BannerGetAllView(APIView):
    """
    GET /api/v1/Banner/GetAll
    """
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "data": []
        })


class SearchEngineMetaView(APIView):
    """
    GET /api/v1/SearchEngine/<entity_type>/<slug>/meta
    Returns SEO metadata and structured JSON-LD data for the requested entity.
    """
    permission_classes = [AllowAny]

    def get(self, request, entity_type: str, slug: str):
        cleaned_slug = unquote(slug).strip()
        title = f"{cleaned_slug} | مانگ" if cleaned_slug else "فروشگاه پوشاک مانگ"
        description = f"خرید آنلاین انواع {cleaned_slug} با بهترین قیمت، کیفیت و ارسال سریع از فروشگاه مانگ."
        keywords = ["مانگ", cleaned_slug, "پوشاک", "خرید آنلاین"]

        data = {
            "title": title,
            "metaDescription": description,
            "keywords": keywords,
            "canonicalUrl": "",
            "context": "https://schema.org/",
            "type": "CollectionPage" if entity_type == "category" else "Product",
            "name": title,
            "offers": {
                "type": "Offer",
                "urlSlug": cleaned_slug,
                "priceCurrency": "IRR",
                "price": "0",
                "availability": "https://schema.org/InStock",
                "itemCondition": "https://schema.org/NewCondition",
            },
        }

        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "result": {
                "data": data,
            },
            "data": data,
        })


class SearchEngineBreadcrumbsView(APIView):
    """
    GET /api/v1/SearchEngine/<entity_type>/<slug>/breadcrumbs
    """
    permission_classes = [AllowAny]

    def get(self, request, entity_type: str, slug: str):
        cleaned_slug = unquote(slug).strip()
        breadcrumbs = [
            {"title": "صفحه اصلی", "url": "/"},
            {"title": cleaned_slug, "url": f"/{entity_type}/{slug}"},
        ]

        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "result": {
                "data": breadcrumbs,
            },
            "data": breadcrumbs,
        })


class SearchEngineIndexView(APIView):
    """
    GET /api/v1/SearchEngine/<entity_type>/<slug>/index
    """
    permission_classes = [AllowAny]

    def get(self, request, entity_type: str, slug: str):
        return Response(1, status=status.HTTP_200_OK)


class SearchEngineSiteMapsView(APIView):
    """
    GET /api/v1/SearchEngine/SiteMaps
    """
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({
            "isSuccess": True,
            "statusCode": 200,
            "result": {
                "data": {
                    "product": {"entityType": "product", "lastCacheTime": "", "items": []},
                    "category": {"entityType": "category", "lastCacheTime": "", "items": []},
                    "blog": {"entityType": "blog", "lastCacheTime": "", "items": []},
                }
            }
        })
