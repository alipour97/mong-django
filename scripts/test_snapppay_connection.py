#!/usr/bin/env python3
"""
SnappPay Connection & Whitelist Diagnostic Tool.

Tests:
1. Public Outbound IP of the current machine/container.
2. Step 1: OAuth Token (/api/online/v1/oauth/token) - verifies IP Whitelist and Credentials.
3. Step 2: Payment Token (/api/online/payment/v1/token) - verifies returnURL validation.

Usage:
    python scripts/test_snapppay_connection.py
    python scripts/test_snapppay_connection.py --base-url https://api.snapppay.ir --client-id ... --client-secret ... --username ... --password ...
"""
import argparse
import base64
import os
import sys
import json
import requests

# Try to load Django settings if inside project
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    django.setup()
    from django.conf import settings
    default_base_url = getattr(settings, "SNAPPAY_BASE_URL", "")
    default_client_id = getattr(settings, "SNAPPAY_CLIENT_ID", "")
    default_client_secret = getattr(settings, "SNAPPAY_CLIENT_SECRET", "")
    default_username = getattr(settings, "SNAPPAY_USERNAME", "")
    default_password = getattr(settings, "SNAPPAY_PASSWORD", "")
    default_return_url = getattr(settings, "PAYHUB_SNAPP_RETURN_URL", "https://pay.mong.ir")
except Exception:
    default_base_url = os.getenv("SNAPPAY_BASE_URL", "https://api.snapppay.ir")
    default_client_id = os.getenv("SNAPPAY_CLIENT_ID", "")
    default_client_secret = os.getenv("SNAPPAY_CLIENT_SECRET", "")
    default_username = os.getenv("SNAPPAY_USERNAME", "")
    default_password = os.getenv("SNAPPAY_PASSWORD", "")
    default_return_url = os.getenv("PAYHUB_SNAPP_RETURN_URL", "https://pay.mong.ir")


def get_public_ip():
    providers = [
        "https://api.ipify.org",
        "https://ifconfig.me/ip",
        "https://icanhazip.com",
    ]
    for url in providers:
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200 and resp.text.strip():
                return resp.text.strip()
        except Exception:
            continue
    return "نامشخص (خطا در دریافت IP)"


def main():
    parser = argparse.ArgumentParser(description="Test SnappPay Connection and IP Whitelist")
    parser.add_argument("--base-url", default=default_base_url, help="SnappPay Base URL")
    parser.add_argument("--client-id", default=default_client_id, help="SnappPay Client ID")
    parser.add_argument("--client-secret", default=default_client_secret, help="SnappPay Client Secret")
    parser.add_argument("--username", default=default_username, help="SnappPay Username")
    parser.add_argument("--password", default=default_password, help="SnappPay Password")
    parser.add_argument("--return-url", default=default_return_url, help="Return URL base domain")
    args = parser.parse_args()

    print("=" * 65)
    print("🔍 ابزار عیب‌یابی اتصال به اسنپ‌پی و بررسی IP Whitelist")
    print("=" * 65)

    # 1. Check Outbound IP
    print("\n[۱] بررسی آی‌پی خروجی سرور شما (Public Outbound IP):")
    my_ip = get_public_ip()
    print(f"👉 آی‌پی خروجی فعلی سرور: \033[1;36m{my_ip}\033[0m")
    print("   (این همان آی‌پی است که فایروال اسنپ‌پی مشاهده می‌کند)")

    # Validate inputs
    base_url = (args.base_url or "https://api.snapppay.ir").rstrip("/")
    client_id = args.client_id
    client_secret = args.client_secret
    username = args.username
    password = args.password

    if not (client_id and client_secret and username and password):
        print("\n\033[1;33m[!] اطلاعات احراز هویت اسنپ‌پی در متغیرهای محیطی یا ورودی یافت نشد.\033[0m")
        print("می‌توانید مقادیر را به صورت دستی با سوییچ‌ها وارد کنید:")
        print("python scripts/test_snapppay_connection.py --client-id '...' --client-secret '...' --username '...' --password '...'")
        return

    # 2. Test Step 1: OAuth Token
    print("\n[۲] مرحله اول: تست دریافت توکن احراز هویت (OAuth Token)")
    print(f"URL: {base_url}/api/online/v1/oauth/token")
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    payload = {
        "grant_type": "password",
        "scope": "online-merchant",
        "username": username,
        "password": password
    }

    try:
        resp = requests.post(f"{base_url}/api/online/v1/oauth/token", headers=headers, data=payload, timeout=15)
        print(f"HTTP Status Code: \033[1;33m{resp.status_code}\033[0m")
        
        if resp.status_code == 200:
            data = resp.json()
            access_token = data.get("access_token")
            print("✅ \033[1;32mموفق! آی‌پی سرور شما در وایت‌لیست اسنپ‌پی مجاز است و یوزرنیم/پسورد صحیح است.\033[0m")
        elif resp.status_code == 403:
            print("❌ \033[1;31mخطای 403 Forbidden دریافت شد!\033[0m")
            print(f"👉 متن پاسخ اسنپ‌پی: {resp.text}")
            print(f"نتیجه: آی‌پی {my_ip} در لیست سفید (Whitelist) فایروال اسنپ‌پی ثبت نشده است.")
            return
        elif resp.status_code in (400, 401):
            print("⚠️ \033[1;31mخطای احراز هویت (400/401)!\033[0m")
            print(f"پاسخ اسنپ‌پی: {resp.text}")
            print("نتیجه: آی‌پی دسترسی دارد اما نام‌کاربری یا کلمه عبور یا Client Secret اشتباه است.")
            return
        else:
            print(f"پاسخ غیرمنتظره ({resp.status_code}): {resp.text}")
            return
    except Exception as exc:
        print(f"❌ خطا در ارسال درخواست: {exc}")
        return

    # 3. Test Step 2: Payment Token (Return URL test)
    print("\n[۳] مرحله دوم: تست درخواست توکن پرداخت (Payment Token) و بررسی Return URL")
    return_url_full = f"{args.return_url.rstrip('/')}/api/SnappPay/CallBack/9999/test-token"
    print(f"URL: {base_url}/api/online/payment/v1/token")
    print(f"Return URL ارسالی: \033[1;34m{return_url_full}\033[0m")

    token_headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    token_body = {
        "amount": 100000,
        "discountAmount": 0,
        "externalSourceAmount": 0,
        "mobile": "+989123456789",
        "returnURL": return_url_full,
        "transactionId": "99999999",
        "cartList": []
    }

    try:
        resp2 = requests.post(f"{base_url}/api/online/payment/v1/token", headers=token_headers, json=token_body, timeout=15)
        print(f"HTTP Status Code: \033[1;33m{resp2.status_code}\033[0m")
        print(f"پاسخ اسنپ‌پی: {resp2.text}")
        
        if resp2.status_code == 200:
            res_json = resp2.json()
            if res_json.get("successful"):
                print("✅ \033[1;32mموفق! توکن پرداخت با موفقیت تولید شد و آدرس returnURL کاملاً معتبر است.\033[0m")
            else:
                print(f"⚠️ پاسخ با کد 200 اما خطا در بیزینس اسنپ: {res_json.get('errorData')}")
        elif resp2.status_code == 403:
            print("❌ \033[1;31mدر مرحله دریافت توکن پرداخت خطای 403 داده شد!\033[0m")
            print("این نشان می‌دهد توکن احراز هویت معتبر است، اما Return URL ثبت شده در قرارداد اسنپ‌پی با آدرس فوق مطابقت ندارد.")
    except Exception as exc:
        print(f"❌ خطا در درخواست توکن پرداخت: {exc}")

    print("\n" + "=" * 65)


if __name__ == "__main__":
    main()
