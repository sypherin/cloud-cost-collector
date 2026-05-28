#!/usr/bin/env python3
"""Setup wizard — two jobs in one file.

  init   (interactive)  -> asks a few questions, writes config.yaml + .env for you.
  setup  (automatable)  -> does the API-able setup (creates GCP datasets) and prints
                           the few manual clicks that have no API.

You normally run them back-to-back:
  python setup_wizard.py init     # answer questions -> config.yaml + .env written
  python setup_wizard.py setup    # create datasets + print the manual toggles

Or via the main entrypoint:
  python cloud_cost_collector.py init
"""
import os
import subprocess
import sys

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: pyyaml. Run: pip install -r requirements.txt")

HERE = os.path.dirname(os.path.abspath(__file__))


# ----------------------------------------------------------------------------
# Small prompt helpers
# ----------------------------------------------------------------------------
def _ask(prompt, default=""):
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        val = ""
    return val or default


def _yesno(prompt, default=False):
    d = "Y/n" if default else "y/N"
    try:
        val = input(f"{prompt} [{d}]: ").strip().lower()
    except EOFError:
        val = ""
    if not val:
        return default
    return val in ("y", "yes")


# ----------------------------------------------------------------------------
# init — interactive config + .env writer
# ----------------------------------------------------------------------------
def interactive_init():
    print("\n☁️  Cloud Cost Collector — setup\n"
          "Answer a few questions; I'll write config.yaml and .env for you.\n"
          "Press Enter to accept the [default]. No secrets are stored in config.yaml —\n"
          "tokens/URLs go into .env (which is gitignored).\n")

    cfg_path = os.path.join(HERE, "config.yaml")
    if os.path.exists(cfg_path) and not _yesno(
            "config.yaml already exists. Overwrite it?", default=False):
        print("Keeping existing config.yaml. Re-run with a fresh checkout to start over.")
        return

    providers = {}
    env = {}

    # --- Azure ---
    if _yesno("Do you use Azure?", default=False):
        subs = []
        print("  Enter your Azure subscription(s). Blank id to stop.")
        while True:
            sid = _ask("  Azure subscription id (blank = done)")
            if not sid:
                break
            label = _ask("    label", default="Production")
            subs.append({"id": sid, "label": label})
        providers["azure"] = {"enabled": bool(subs), "subscriptions": subs or [
            {"id": "<AZURE_SUBSCRIPTION_ID>", "label": "Production"}]}
    else:
        providers["azure"] = {"enabled": False,
                              "subscriptions": [{"id": "<AZURE_SUBSCRIPTION_ID>",
                                                 "label": "Production"}]}

    # --- GCP ---
    if _yesno("Do you use Google Cloud?", default=False):
        dataset = _ask("  BigQuery dataset name to use for the billing export",
                       default="billing_export")
        accounts = []
        print("  GCP has no on-demand cost API — cost is read from a BigQuery export.")
        print("  Enter each billing account + a project to store its export. Blank to stop.")
        while True:
            acct = _ask("  GCP billing account id (e.g. XXXXXX-XXXXXX-XXXXXX, blank = done)")
            if not acct:
                break
            proj = _ask("    storage project id (a project under that billing account)")
            accounts.append({"id": acct, "storage_project": proj})
        providers["gcp"] = {"enabled": bool(accounts), "dataset": dataset,
                            "billing_accounts": accounts or []}
    else:
        providers["gcp"] = {"enabled": False, "dataset": "billing_export",
                            "billing_accounts": []}

    # --- AWS ---
    if _yesno("Do you use AWS?", default=False):
        profile = _ask("  AWS named profile (blank = default credential chain)")
        region = _ask("  AWS region", default="us-east-1")
        providers["aws"] = {"enabled": True, "profile": profile, "region": region}
        print("  (AWS needs boto3:  pip install boto3)")
    else:
        providers["aws"] = {"enabled": False, "profile": "", "region": "us-east-1"}

    # --- Sinks ---
    sinks = {}
    print("\nWhere should the daily digest go?")
    tg = _yesno("  Send to Telegram?", default=False)
    sinks["telegram"] = {"enabled": tg, "token_env": "CCC_TELEGRAM_TOKEN",
                         "chat_id_env": "CCC_TELEGRAM_CHAT_ID"}
    if tg:
        env["CCC_TELEGRAM_TOKEN"] = _ask("    Telegram bot token (from @BotFather)")
        env["CCC_TELEGRAM_CHAT_ID"] = _ask("    Telegram chat id to send to")

    wh = _yesno("  Book monthly costs to a webhook (your CRM/accounting)?", default=False)
    sinks["webhook"] = {"enabled": wh, "url_env": "CCC_WEBHOOK_URL",
                        "auth_header_env": "", "field_map": {}}
    if wh:
        env["CCC_WEBHOOK_URL"] = _ask("    Webhook URL to POST expenses to")
        if _yesno("    Does it need an Authorization header?", default=False):
            sinks["webhook"]["auth_header_env"] = "CCC_WEBHOOK_AUTH"
            env["CCC_WEBHOOK_AUTH"] = _ask("    Authorization header value")

    spike = _ask("\nDay-over-day % jump that flags a ⚠️SPIKE", default="50")
    try:
        spike_pct = float(spike)
    except ValueError:
        spike_pct = 50.0

    cfg = {"providers": providers, "sinks": sinks, "options": {"spike_pct": spike_pct}}

    with open(cfg_path, "w") as f:
        f.write("# Written by `setup_wizard.py init`. Safe to hand-edit.\n"
                "# No secrets here — tokens/URLs live in .env.\n")
        yaml.safe_dump(cfg, f, sort_keys=False, default_flow_style=False)
    print(f"\n✅ Wrote {cfg_path}")

    if env:
        env_path = os.path.join(HERE, ".env")
        if not os.path.exists(env_path) or _yesno(".env exists. Overwrite it?", default=False):
            with open(env_path, "w") as f:
                f.write("# Written by `setup_wizard.py init`. Never commit this file.\n")
                for k, v in env.items():
                    f.write(f'{k}="{v}"\n')
            os.chmod(env_path, 0o600)
            print(f"✅ Wrote {env_path}  (chmod 600 — keep it secret, it's gitignored)")
            print("   Load it before running:  set -a && source .env && set +a")

    # Offer to run the automatable setup right away.
    if (providers.get("gcp") or {}).get("enabled") or \
       (providers.get("azure") or {}).get("enabled") or \
       (providers.get("aws") or {}).get("enabled"):
        if _yesno("\nRun provider setup now (create GCP datasets, print manual steps)?",
                  default=True):
            run_setup(cfg)

    print("\nNext:  python cloud_cost_collector.py --dry-run   # verify output")


# ----------------------------------------------------------------------------
# setup — the automatable provider prep + manual-step printouts
# ----------------------------------------------------------------------------
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


def run_setup(cfg):
    providers = cfg.get("providers") or {}
    if (providers.get("gcp") or {}).get("enabled"):
        gcp_setup(providers["gcp"])
    if (providers.get("azure") or {}).get("enabled"):
        azure_setup(providers["azure"])
    if (providers.get("aws") or {}).get("enabled"):
        aws_setup(providers["aws"])
    print("\nDone. Test with:  python cloud_cost_collector.py --dry-run")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "setup"
    if cmd == "init":
        interactive_init()
    else:
        cfg_path = os.path.join(HERE, "config.yaml")
        if not os.path.exists(cfg_path):
            sys.exit("No config.yaml — run `python setup_wizard.py init` first.")
        with open(cfg_path) as f:
            run_setup(yaml.safe_load(f))


if __name__ == "__main__":
    main()
