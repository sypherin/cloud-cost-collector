#!/usr/bin/env python3
"""Setup wizard — does the automatable parts of cloud cost setup, and tells you
the exact (few) manual clicks that have no API.

What it does:
  • GCP: for each billing account in config, picks/uses a storage project and
    creates the `billing_export` dataset via `bq` (so you skip the fiddly console
    form), then prints the ONE console toggle you must flip per account, with a
    deep-link.
  • Azure: prints the role you need (Cost Management Reader) + the assign command.
  • AWS: prints the IAM action you need (ce:GetCostAndUsage).

Run after editing config.yaml:
  python setup_wizard.py
"""
import subprocess
import sys

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: pyyaml. Run: pip install -r requirements.txt")


def gcp_setup(pcfg):
    dataset = pcfg.get("dataset", "billing_export")
    accounts = pcfg.get("billing_accounts") or []
    if not accounts:
        print("  (no billing_accounts in config — nothing to do)")
        return
    print(f"\n🟡 GCP — creating dataset '{dataset}' per account, then your toggles:")
    for a in accounts:
        acct, proj = a.get("id"), a.get("storage_project")
        if not acct or not proj:
            print(f"  ! skipping incomplete entry: {a}")
            continue
        # Auto-create the dataset (idempotent).
        r = subprocess.run(["bq", "mk", "--dataset", "--location=US",
                            "--description=Cloud Billing export", f"{proj}:{dataset}"],
                           capture_output=True, text=True)
        msg = (r.stdout + r.stderr).strip().splitlines()
        status = "created" if r.returncode == 0 else ("exists" if "already exists" in " ".join(msg) else "FAILED")
        print(f"  • {acct} -> {proj}:{dataset}  [{status}]")
        if status == "FAILED":
            print(f"      {' '.join(msg)}")
        print(f"      TOGGLE (no API for this): "
              f"https://console.cloud.google.com/billing/{acct}/export/bigquery")
        print(f"      -> Enable standard export -> project '{proj}' -> dataset '{dataset}' -> Save")
    print("  Tables appear a few hours after you flip each toggle; the collector "
          "skips them until then.")


def azure_setup(pcfg):
    print("\n🔵 Azure — grant Cost Management Reader on each subscription:")
    for s in (pcfg.get("subscriptions") or []):
        sid = s.get("id", "<SUBSCRIPTION_ID>")
        print(f"  az role assignment create --assignee <you@example.com> "
              f"--role \"Cost Management Reader\" --scope /subscriptions/{sid}")
    print("  (You need Owner or User Access Administrator on the sub to self-assign.)")


def aws_setup(pcfg):
    print("\n🟠 AWS — the identity you run as needs Cost Explorer read access:")
    print("  IAM action: ce:GetCostAndUsage  (attach to your user/role)")
    print("  Also enable Cost Explorer once in the console (Billing -> Cost Explorer).")


def main():
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)
    providers = cfg.get("providers") or {}
    if (providers.get("gcp") or {}).get("enabled"):
        gcp_setup(providers["gcp"])
    if (providers.get("azure") or {}).get("enabled"):
        azure_setup(providers["azure"])
    if (providers.get("aws") or {}).get("enabled"):
        aws_setup(providers["aws"])
    print("\nDone. Test with:  python cloud_cost_collector.py --dry-run")


if __name__ == "__main__":
    main()
