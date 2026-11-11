"""
Tell SnappPay (SearchWise) that the shop's feed is ready: the same request the WooCommerce
plugin's feed_plugin_activated() sends once, when the plugin is turned on. It adds a row
(domain, email, plugin version) to their Google Sheet.

    python3 scripts/searchwise_register.py https://mong.ir shop@example.com

Standard library only. Run it once; every run adds another row.
"""
import json
import sys
import urllib.error
import urllib.request

WEBHOOK = ("https://script.google.com/macros/s/"
           "AKfycbz2nrP94YdvCyVURqBxaFc_UEYgCHpTGAqjKeJER1j_qx2aM-a1zP1xOgSiEn6Ovc9q/exec")


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit("usage: searchwise_register.py <site url> <email>")
    body = {"domain": sys.argv[1].rstrip("/"), "email": sys.argv[2], "version": "1.0.2"}
    request = urllib.request.Request(
        WEBHOOK, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        # Apps Script answers with a redirect to the result; urllib follows it.
        with urllib.request.urlopen(request, timeout=20) as r:
            status, text = r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status, text = e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        sys.exit(f"no answer: {e}")
    print(f"sent {body} -> HTTP {status}")
    print(text[:1000])


if __name__ == "__main__":
    main()
