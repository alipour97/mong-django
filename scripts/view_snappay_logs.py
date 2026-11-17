#!/usr/bin/env python3
"""
CLI utility to inspect SnappPay crawler access logs.
Usage:
    python back/scripts/view_snappay_logs.py [--limit 50] [--snappay-only] [--json]
"""
import argparse
import json
import sys
from pathlib import Path

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
JSONL_FILE = LOGS_DIR / "snappay_access.jsonl"
TXT_FILE = LOGS_DIR / "snappay_access.log"

def main():
    parser = argparse.ArgumentParser(description="View SnappPay crawler access logs")
    parser.add_argument("--limit", "-n", type=int, default=30, help="Number of records to show (default: 30)")
    parser.add_argument("--snappay-only", "-s", action="store_true", help="Show only requests from official SnappPay IPs")
    parser.add_argument("--tail", "-f", action="store_true", help="Print recent plain log lines")
    args = parser.parse_args()

    if args.tail:
        if not TXT_FILE.exists():
            print("No log file found at", TXT_FILE)
            return
        lines = TXT_FILE.read_text(encoding="utf-8").strip().splitlines()
        for line in lines[-args.limit:]:
            print(line)
        return

    if not JSONL_FILE.exists():
        print(f"No access logs found yet at {JSONL_FILE}")
        print("Logs will appear as soon as requests are made to SnappPay endpoints.")
        return

    records = []
    with open(JSONL_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if args.snappay_only and not rec.get("is_snappay_ip"):
                    continue
                records.append(rec)
            except Exception:
                pass

    if not records:
        print("No matching logs found.")
        return

    records = records[-args.limit:]
    print(f"\n{'='*110}")
    print(f"{'TIME':<20} | {'IP':<16} | {'SNAPPAY?':<9} | {'METHOD / ENDPOINT':<30} | {'STATUS':<6} | {'COUNT':<5} | {'UA'}")
    print(f"{'='*110}")

    for r in records:
        ts = r.get("timestamp", "")
        ip = r.get("ip", "")
        is_sp = "YES (Official)" if r.get("is_snappay_ip") else "No"
        channel = r.get("channel", "")[:28]
        status = str(r.get("status_code", ""))
        cnt = str(r.get("items_count", "-"))
        ua = r.get("user_agent", "")[:25]
        print(f"{ts:<20} | {ip:<16} | {is_sp:<9} | {channel:<30} | {status:<6} | {cnt:<5} | {ua}")
    print(f"{'='*110}")
    print(f"Total matching requests shown: {len(records)} (Log file: {JSONL_FILE})\n")

if __name__ == "__main__":
    main()
