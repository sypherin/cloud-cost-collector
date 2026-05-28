#!/usr/bin/env python3
"""MCP server for Cloud Cost Collector.

Exposes your cloud spend to any MCP client (Claude, Lyra, Cursor, etc.) as tools,
so an agent can just ask "what's my GCP spend this month" instead of you opening
a console. Reuses the same providers + config as the CLI.

Run (stdio):
  python mcp_server.py
  # or register in your MCP client config as: command "python", args ["mcp_server.py"]

Config: same config.yaml as the CLI (CCC_CONFIG env var overrides the path).
Only providers marked enabled are queried.
"""
import os

from mcp.server.fastmcp import FastMCP

from providers import azure as azure_provider
from providers import gcp as gcp_provider
from providers import aws as aws_provider

try:
    import yaml
except ImportError:
    raise SystemExit("Missing dependency: pyyaml. Run: pip install -r requirements.txt")

PROVIDERS = {"azure": azure_provider, "gcp": gcp_provider, "aws": aws_provider}

CONFIG_PATH = os.environ.get(
    "CCC_CONFIG", os.path.join(os.path.dirname(__file__), "config.yaml"))

mcp = FastMCP("cloud-cost-collector")


def _config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _enabled(cfg):
    for name, mod in PROVIDERS.items():
        pcfg = (cfg.get("providers") or {}).get(name) or {}
        if pcfg.get("enabled"):
            yield name, mod, pcfg


@mcp.tool()
def list_providers() -> dict:
    """List which cloud providers are enabled and ready to query."""
    cfg = _config()
    return {"enabled": [name for name, _, _ in _enabled(cfg)],
            "all": list(PROVIDERS.keys())}


@mcp.tool()
def get_costs(period: str = "mtd", provider: str = "") -> dict:
    """Get cloud spend.

    Args:
        period: "mtd" (month-to-date) or "last_month" (previous calendar month).
        provider: optional — one of azure/gcp/aws. Empty = all enabled providers.

    Returns per-provider totals, currency, and (for mtd) a top-service breakdown.
    """
    cfg = _config()
    out = {"period": period, "providers": {}}
    for name, mod, pcfg in _enabled(cfg):
        if provider and provider != name:
            continue
        try:
            if period == "last_month":
                r = mod.last_month(pcfg)
            else:
                r = mod.mtd(pcfg)
        except Exception as e:
            out["providers"][name] = {"error": str(e)}
            continue
        if r is None:
            out["providers"][name] = {"status": "not_ready"}
            continue
        entry = {"vendor": mod.VENDOR, "total": round(r["total"], 2),
                 "currency": r["currency"]}
        if r.get("period"):
            entry["month"] = r["period"]
        if r.get("delta_pct") is not None:
            entry["day_over_day_pct"] = round(r["delta_pct"], 1)
        if r.get("breakdown"):
            entry["top_services"] = [
                {"service": s, "cost": round(c, 2)} for s, c in r["breakdown"][:5] if c > 0]
        out["providers"][name] = entry
    grand = sum(p.get("total", 0) for p in out["providers"].values() if isinstance(p, dict))
    out["grand_total_note"] = "Totals may mix currencies; sum naive only if single currency."
    out["grand_total"] = round(grand, 2)
    return out


@mcp.tool()
def book_last_month(dry_run: bool = True) -> dict:
    """Book last month's final actual into your books via the configured webhook.

    WRITE action — posts one expense per provider to your accounting/CRM webhook.
    Defaults to dry_run=True (returns what WOULD be booked without posting).
    Set dry_run=False to actually post.
    """
    import datetime
    from sinks import webhook as webhook_sink

    cfg = _config()
    book_date = datetime.date.today().replace(day=1).isoformat()
    wcfg = (cfg.get("sinks") or {}).get("webhook") or {}
    results = []
    for name, mod, pcfg in _enabled(cfg):
        try:
            r = mod.last_month(pcfg)
        except Exception as e:
            results.append({"provider": name, "error": str(e)})
            continue
        if not r or r["total"] <= 0:
            results.append({"provider": name, "status": "nothing_to_book"})
            continue
        expense = {"description": f"{mod.VENDOR} — cloud ({r['period']})",
                   "amount": round(r["total"], 2), "currency": r["currency"],
                   "category": "cloud-hosting", "vendor": mod.VENDOR,
                   "expense_date": book_date, "period": r["period"],
                   "recurring": True, "recurring_period": "monthly"}
        if dry_run:
            results.append({"provider": name, "would_book": expense})
        else:
            if not wcfg.get("enabled"):
                results.append({"provider": name, "error": "webhook sink not enabled"})
                continue
            webhook_sink.post_expense(wcfg, expense)
            results.append({"provider": name, "booked": expense})
    return {"dry_run": dry_run, "results": results}


if __name__ == "__main__":
    mcp.run()
