"""Webhook sink — POSTs each monthly booking to your accounting/CRM.

This is the differentiator: instead of just showing spend, push it into your
books as opex. Point it at any endpoint that accepts a JSON expense — your own
CRM/ERP, an n8n/Zapier hook, an accounting API wrapper, etc.

The endpoint URL is read from env (never config), so the repo carries no
internal URLs.

Config (per sinks.webhook in config.yaml):
  enabled: true
  url_env: CCC_WEBHOOK_URL         # POST target
  auth_header_env: ""              # optional: env var holding an Authorization header value
  field_map:                       # optional: rename fields for your endpoint
    description: description
    amount: amount
    currency: currency
    category: category
    vendor: vendor
    expense_date: expense_date

Default payload posted (before field_map):
  {description, amount, currency, category, vendor, expense_date,
   period, recurring, recurring_period}
"""
import json
import os
import urllib.request


def post_expense(cfg, expense):
    url = os.environ.get(cfg.get("url_env", "CCC_WEBHOOK_URL"), "")
    if not url:
        raise RuntimeError("webhook sink enabled but URL env var is unset")

    field_map = cfg.get("field_map") or {}
    payload = {field_map.get(k, k): v for k, v in expense.items()}

    headers = {"Content-Type": "application/json"}
    auth_env = cfg.get("auth_header_env")
    if auth_env and os.environ.get(auth_env):
        headers["Authorization"] = os.environ[auth_env]

    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()
