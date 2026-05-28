"""Azure cost provider — uses the CostManagement query API via the `az` CLI token.

Azure is the friendly one: it has a real on-demand cost API. Auth uses the
locally logged-in `az` account; we fetch a scoped token per subscription so the
global CLI default is never mutated.

Config (per providers.azure in config.yaml):
  enabled: true
  subscriptions:
    - id: "<AZURE_SUBSCRIPTION_ID>"
      label: "Production"      # optional, for the digest line
"""
import datetime
import json
import subprocess
import time
import urllib.request
import urllib.error

ICON = "🔵"
LABEL = "Azure"
VENDOR = "Microsoft Azure"

_TOKEN_CACHE = {}


def _token(subscription_id):
    if subscription_id in _TOKEN_CACHE:
        return _TOKEN_CACHE[subscription_id]
    out = subprocess.run(
        ["az", "account", "get-access-token", "--subscription", subscription_id,
         "--resource", "https://management.azure.com", "-o", "json"],
        capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f"az token failed: {out.stderr.strip()}")
    tok = json.loads(out.stdout)["accessToken"]
    _TOKEN_CACHE[subscription_id] = tok
    return tok


def _query(subscription_id, body, retries=3):
    tok = _token(subscription_id)
    url = (f"https://management.azure.com/subscriptions/{subscription_id}"
           f"/providers/Microsoft.CostManagement/query?api-version=2023-11-01")
    for attempt in range(retries):
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = int(e.headers.get("Retry-After") or (8 * (attempt + 1)))
                time.sleep(min(wait, 30))
                continue
            raise


def _subscriptions(pcfg):
    return [s["id"] for s in (pcfg.get("subscriptions") or []) if s.get("id")]


def mtd(pcfg):
    total, currency = 0.0, "USD"
    svc_totals = {}
    yest = prev = 0.0
    for sub in _subscriptions(pcfg):
        # MTD grouped by service (also yields total via sum + currency).
        grp = _query(sub, {"type": "ActualCost", "timeframe": "MonthToDate",
                           "dataset": {"granularity": "None",
                                       "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
                                       "grouping": [{"type": "Dimension", "name": "ServiceName"}]}})
        cols = [c["name"] for c in grp.get("properties", {}).get("columns", [])]
        ci = cols.index("Cost") if "Cost" in cols else 0
        si = cols.index("ServiceName") if "ServiceName" in cols else 1
        cur_i = cols.index("Currency") if "Currency" in cols else None
        for r in grp.get("properties", {}).get("rows", []):
            c = float(r[ci])
            total += c
            svc_totals[str(r[si])] = svc_totals.get(str(r[si]), 0.0) + c
            if cur_i is not None:
                currency = r[cur_i]
        # Daily for day-over-day delta.
        daily = _query(sub, {"type": "ActualCost", "timeframe": "MonthToDate",
                            "dataset": {"granularity": "Daily",
                                        "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}}}})
        dcols = [c["name"] for c in daily.get("properties", {}).get("columns", [])]
        dci = dcols.index("Cost") if "Cost" in dcols else 0
        ddi = dcols.index("UsageDate") if "UsageDate" in dcols else 1
        drows = sorted(daily.get("properties", {}).get("rows", []), key=lambda x: x[ddi])
        vals = [float(x[dci]) for x in drows]
        if vals:
            yest += vals[-1]
        if len(vals) >= 2:
            prev += vals[-2]
    delta = ((yest - prev) / prev * 100) if prev > 0 else None
    breakdown = sorted(svc_totals.items(), key=lambda x: -x[1])
    return {"total": total, "currency": currency, "breakdown": breakdown, "delta_pct": delta}


def last_month(pcfg):
    today = datetime.date.today()
    last_end = today.replace(day=1) - datetime.timedelta(days=1)
    first = last_end.replace(day=1)
    total, currency = 0.0, "USD"
    for sub in _subscriptions(pcfg):
        r = _query(sub, {"type": "ActualCost", "timeframe": "Custom",
                        "timePeriod": {"from": first.isoformat() + "T00:00:00Z",
                                       "to": last_end.isoformat() + "T23:59:59Z"},
                        "dataset": {"granularity": "None",
                                    "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}}}})
        rows = r.get("properties", {}).get("rows", [])
        if rows:
            total += float(rows[0][0])
            if len(rows[0]) > 1:
                currency = rows[0][1]
    return {"total": total, "currency": currency, "period": first.strftime("%b %Y")}
