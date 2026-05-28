#!/usr/bin/env python3
"""Cloud Cost Collector — pull cloud spend, digest it, and book it into your books.

Multi-cloud (Azure / GCP / AWS) cost collector with two jobs:
  digest   (default)  -> a spend summary to your sink(s): Telegram, Slack, webhook
  book     --book      -> last month's final actual posted once per provider to a
                          webhook (your accounting/CRM), as recurring opex

Everything is config-driven (config.yaml). No cloud IDs or secrets live in code.
Secrets (bot tokens, webhook URLs) come from environment variables.

Usage:
  cloud_cost_collector.py init            # interactive setup -> writes config.yaml + .env
  cloud_cost_collector.py                 # daily digest
  cloud_cost_collector.py --book          # monthly: book last month's actual
  cloud_cost_collector.py --config /path/to/config.yaml
  cloud_cost_collector.py --dry-run       # print, don't send
"""
import argparse
import datetime
import os
import sys

from providers import azure as azure_provider
from providers import gcp as gcp_provider
from providers import aws as aws_provider
from sinks import telegram as telegram_sink
from sinks import webhook as webhook_sink

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: pyyaml. Run: pip install -r requirements.txt")

PROVIDERS = {
    "azure": azure_provider,
    "gcp": gcp_provider,
    "aws": aws_provider,
}


def load_config(path):
    if not os.path.exists(path):
        sys.exit(f"Config not found: {path}\nCopy config.example.yaml -> config.yaml and edit it.")
    with open(path) as f:
        return yaml.safe_load(f)


def enabled_providers(cfg):
    for name, mod in PROVIDERS.items():
        pcfg = (cfg.get("providers") or {}).get(name) or {}
        if pcfg.get("enabled"):
            yield name, mod, pcfg


def run_digest(cfg, dry_run):
    spike_pct = float((cfg.get("options") or {}).get("spike_pct", 50))
    lines = ["☁️ Cloud costs — month-to-date"]
    for name, mod, pcfg in enabled_providers(cfg):
        try:
            result = mod.mtd(pcfg)  # -> dict {total, currency, breakdown:[(label,cost)], delta_pct?}
        except Exception as e:
            lines.append(f"\n{mod.ICON} {mod.LABEL}: error — {e}")
            continue
        if result is None:
            lines.append(f"\n{mod.ICON} {mod.LABEL}: not ready yet (export still populating).")
            continue
        cur = result["currency"]
        lines.append(f"\n{mod.ICON} {mod.LABEL}: {cur} {result['total']:,.2f}")
        delta = result.get("delta_pct")
        if delta is not None:
            spike = " ⚠️SPIKE" if delta >= spike_pct else ""
            lines.append(f"   day-over-day {delta:+.0f}%{spike}")
        for label, cost in (result.get("breakdown") or [])[:5]:
            if cost > 0:
                lines.append(f"     • {label}: {cur} {cost:,.2f}")

    body = "\n".join(lines)
    dispatch(cfg, body, dry_run, booking=False)


def run_book(cfg, dry_run):
    today = datetime.date.today()
    book_date = today.replace(day=1).isoformat()
    summary = ["📒 Monthly cloud costs booked as opex:"]
    bookings = []
    for name, mod, pcfg in enabled_providers(cfg):
        try:
            result = mod.last_month(pcfg)  # -> {total, currency, period} or None
        except Exception as e:
            summary.append(f"{mod.ICON} {mod.LABEL}: book FAILED — {e}")
            continue
        if result is None:
            summary.append(f"{mod.ICON} {mod.LABEL}: not ready — skipped")
            continue
        total, cur, period = result["total"], result["currency"], result["period"]
        if total <= 0:
            summary.append(f"{mod.ICON} {mod.LABEL}: {cur} 0.00 — nothing to book")
            continue
        bookings.append({
            "description": f"{mod.VENDOR} — cloud ({period})",
            "amount": round(total, 2),
            "currency": cur,
            "category": "cloud-hosting",
            "vendor": mod.VENDOR,
            "expense_date": book_date,
            "period": period,
            "recurring": True,
            "recurring_period": "monthly",
        })
        summary.append(f"{mod.ICON} {mod.LABEL}: {cur} {total:,.2f} ({period})")

    # Post each booking to the webhook sink (the "book into your books" step).
    wcfg = (cfg.get("sinks") or {}).get("webhook") or {}
    if wcfg.get("enabled") and bookings and not dry_run:
        for b in bookings:
            try:
                webhook_sink.post_expense(wcfg, b)
            except Exception as e:
                summary.append(f"   ⚠️ webhook post failed for {b['vendor']}: {e}")

    dispatch(cfg, "\n".join(summary), dry_run, booking=True)


def dispatch(cfg, text, dry_run, booking):
    if dry_run:
        print(text)
        return
    tcfg = (cfg.get("sinks") or {}).get("telegram") or {}
    if tcfg.get("enabled"):
        telegram_sink.send(tcfg, text)
    if not ((cfg.get("sinks") or {}).get("telegram", {}).get("enabled")):
        print(text)  # no sink configured -> stdout fallback


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        import setup_wizard
        setup_wizard.interactive_init()
        return
    ap = argparse.ArgumentParser(description="Cloud Cost Collector")
    ap.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "config.yaml"))
    ap.add_argument("--book", action="store_true", help="book last month's actual into your books")
    ap.add_argument("--dry-run", action="store_true", help="print output instead of sending")
    a = ap.parse_args()
    cfg = load_config(a.config)
    if a.book:
        run_book(cfg, a.dry_run)
    else:
        run_digest(cfg, a.dry_run)


if __name__ == "__main__":
    main()
