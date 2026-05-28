"""AWS cost provider — uses Cost Explorer (get_cost_and_usage) via boto3.

AWS is the easiest of the three: Cost Explorer is a proper on-demand cost API.
Auth uses the standard boto3 credential chain (env vars, ~/.aws/credentials,
AWS_PROFILE, or an instance role). Note: Cost Explorer charges ~$0.01 per API
call — negligible for a daily/monthly cron.

Config (per providers.aws in config.yaml):
  enabled: true
  profile: ""        # optional named profile; blank = default chain
  region: us-east-1  # Cost Explorer is global but boto needs a region
"""
import datetime

ICON = "🟠"
LABEL = "AWS"
VENDOR = "Amazon Web Services"


def _client(pcfg):
    import boto3  # imported lazily so the dep is optional unless AWS is enabled
    session = boto3.Session(profile_name=pcfg.get("profile") or None)
    return session.client("ce", region_name=pcfg.get("region", "us-east-1"))


def _ce_total(ce, start, end, group_by_service=False):
    kwargs = dict(TimePeriod={"Start": start, "End": end},
                  Granularity="MONTHLY", Metrics=["UnblendedCost"])
    if group_by_service:
        kwargs["GroupBy"] = [{"Type": "DIMENSION", "Key": "SERVICE"}]
    resp = ce.get_cost_and_usage(**kwargs)
    total, currency, svc = 0.0, "USD", {}
    for period in resp.get("ResultsByTime", []):
        if group_by_service:
            for g in period.get("Groups", []):
                amt = g["Metrics"]["UnblendedCost"]
                c = float(amt["Amount"])
                currency = amt.get("Unit", currency)
                total += c
                svc[g["Keys"][0]] = svc.get(g["Keys"][0], 0.0) + c
        else:
            amt = period["Total"]["UnblendedCost"]
            total += float(amt["Amount"])
            currency = amt.get("Unit", currency)
    return total, currency, svc


def mtd(pcfg):
    ce = _client(pcfg)
    today = datetime.date.today()
    start = today.replace(day=1).isoformat()
    end = (today + datetime.timedelta(days=1)).isoformat()  # CE end is exclusive
    total, currency, svc = _ce_total(ce, start, end, group_by_service=True)
    breakdown = sorted(svc.items(), key=lambda x: -x[1])
    return {"total": total, "currency": currency, "breakdown": breakdown, "delta_pct": None}


def last_month(pcfg):
    ce = _client(pcfg)
    today = datetime.date.today()
    last_end = today.replace(day=1)            # CE end exclusive -> 1st of this month
    first = (last_end - datetime.timedelta(days=1)).replace(day=1)
    total, currency, _ = _ce_total(ce, first.isoformat(), last_end.isoformat())
    return {"total": total, "currency": currency, "period": first.strftime("%b %Y")}
