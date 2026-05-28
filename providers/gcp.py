"""GCP cost provider — reads the BigQuery billing export via the `bq` CLI.

Google has no on-demand cost API, so the only reliable path is a "standard usage
cost" BigQuery export (one per billing account). `setup_wizard.py` creates the
datasets and prints the one console toggle you must flip per account.

The export table for an account lands in your chosen storage project as:
    <storage_project>.<dataset>.gcp_billing_export_v1_<ACCOUNT_ID with '-'->'_'>

Tables take a few hours to first appear; queries against a missing table are
skipped silently so the collector works before and after the data lands.

Config (per providers.gcp in config.yaml):
  enabled: true
  dataset: billing_export            # the dataset name you used in the wizard
  billing_accounts:
    - id: "XXXXXX-XXXXXX-XXXXXX"
      storage_project: "<GCP_PROJECT_ID>"
"""
import datetime
import json
import subprocess

ICON = "🟡"
LABEL = "GCP"
VENDOR = "Google Cloud"


def _table(account_id, storage_project, dataset):
    suffix = account_id.replace("-", "_")
    return f"{storage_project}.{dataset}.gcp_billing_export_v1_{suffix}"


def _bq(sql):
    out = subprocess.run(["bq", "query", "--use_legacy_sql=false", "--format=json", sql],
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        # bq writes some errors (e.g. "Not found: Table") to stdout, not stderr.
        raise RuntimeError((out.stderr.strip() + " " + out.stdout.strip()).strip())
    return json.loads(out.stdout or "[]")


def _tables(pcfg):
    dataset = pcfg.get("dataset", "billing_export")
    out = []
    for a in (pcfg.get("billing_accounts") or []):
        if a.get("id") and a.get("storage_project"):
            out.append(_table(a["id"], a["storage_project"], dataset))
    return out


def _sum(pcfg, date_where, with_service=False):
    """Sum across all export tables for a date filter. Returns (total, currency,
    seen, service_totals). Missing tables are skipped."""
    total, currency, seen = 0.0, "USD", 0
    svc = {}
    for tbl in _tables(pcfg):
        if with_service:
            sql = (f"SELECT service.description svc, ROUND(SUM(cost),2) c, "
                   f"ANY_VALUE(currency) cur FROM `{tbl}` WHERE {date_where} "
                   f"GROUP BY svc")
        else:
            sql = (f"SELECT ROUND(SUM(cost),2) c, ANY_VALUE(currency) cur "
                   f"FROM `{tbl}` WHERE {date_where}")
        try:
            rows = _bq(sql)
        except Exception as e:
            if "ot found" in str(e):  # "Not found" / "not found"
                continue
            raise
        seen += 1
        for row in rows:
            c = float(row.get("c") or 0)
            total += c
            if row.get("cur"):
                currency = row["cur"]
            if with_service and row.get("svc"):
                svc[row["svc"]] = svc.get(row["svc"], 0.0) + c
    return total, currency, seen, svc


def mtd(pcfg):
    if not _tables(pcfg):
        return None
    first = datetime.date.today().replace(day=1).isoformat()
    total, cur, seen, svc = _sum(pcfg, f"DATE(usage_start_time) >= '{first}'", with_service=True)
    if seen == 0:
        return None
    breakdown = sorted(svc.items(), key=lambda x: -x[1])
    return {"total": total, "currency": cur, "breakdown": breakdown, "delta_pct": None}


def last_month(pcfg):
    if not _tables(pcfg):
        return None
    today = datetime.date.today()
    last_end = today.replace(day=1) - datetime.timedelta(days=1)
    first = last_end.replace(day=1)
    total, cur, seen, _ = _sum(
        pcfg, f"DATE(usage_start_time) BETWEEN '{first}' AND '{last_end}'")
    if seen == 0:
        return None
    return {"total": total, "currency": cur, "period": first.strftime("%b %Y")}
