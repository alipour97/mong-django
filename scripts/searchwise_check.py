"""
Ask SearchWise (SnappPay's product search) whether an API key is valid for a domain: the same
request the WooCommerce plugin's has_access() sends on every feed call.

    python3 scripts/searchwise_check.py mong.ir
    python3 scripts/searchwise_check.py mong.ir THE_KEY

Standard library only. It prints the HTTP status and the server's answer as is.
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

URL = "https://merchants.searchwise.ir/api/v1/feed/validate-token"


def main() -> None:
    domain = sys.argv[1] if len(sys.argv) > 1 else "mong.ir"
    api_key = sys.argv[2] if len(sys.argv) > 2 else ""
    body = urllib.parse.urlencode({"merchant_domain": domain, "api_key": api_key, "plugin_version": "1.0.2"}).encode()
    request = urllib.request.Request(URL, data=body, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as r:
            status, text = r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status, text = e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"no answer: {e}")
        sys.exit(1)
    print(f"domain={domain} key={'(empty)' if not api_key else api_key} -> HTTP {status}")
    try:
        print(json.dumps(json.loads(text), ensure_ascii=False, indent=2))
    except ValueError:
        print(text[:2000])


if __name__ == "__main__":
    main()
