# Cloud Cost Collector

Pull your cloud spend, get a digest, and **book it straight into your books** —
across Azure, GCP, and AWS.

Most cost tools (Vantage, Infracost, OpenCost) give you yet another dashboard to
check. This one is built around a different idea: your cloud bill should just
show up in your accounting/CRM as recurring opex, and ping you when it spikes.
No dashboard babysitting.

## What it does

- **Daily digest** → month-to-date spend per cloud, top services, day-over-day
  delta with a spike flag. Sent to Telegram (or printed, or your own sink).
- **Monthly booking** → on the 1st, posts *last month's final actual* once per
  provider to a webhook you control (your CRM, accounting API, n8n/Zapier hook),
  tagged as `cloud-hosting` recurring opex.

```
cloud_cost_collector.py            # daily digest
cloud_cost_collector.py --book     # monthly: book last month's actual
cloud_cost_collector.py --dry-run  # print, don't send
```

## Provider reality check

The three clouds expose cost very differently — this matters for setup:

| Cloud | How cost is read | Setup effort |
|-------|------------------|--------------|
| **AWS** | Cost Explorer API (`ce:GetCostAndUsage`) — proper on-demand API | Easiest: one IAM action |
| **Azure** | Cost Management query API | Easy: grant `Cost Management Reader` |
| **GCP** | BigQuery billing export — **no on-demand cost API exists** | One console toggle per billing account (the wizard does the rest) |

GCP is the awkward one: Google has no "get my spend" API. The only reliable
source is a BigQuery export. The setup wizard auto-creates the dataset and gives
you the single unavoidable console toggle with a deep-link. Tables take a few
hours to first populate; the collector skips them until they exist.

## Setup

```bash
pip install -r requirements.txt          # + boto3 if you use AWS
cp config.example.yaml config.yaml       # edit: enable providers, add ids
cp .env.example .env                      # add bot token / webhook url, then source it
python setup_wizard.py                    # creates GCP datasets, prints the manual toggles
python cloud_cost_collector.py --dry-run  # verify output
```

Then schedule it (example: systemd timers, cron, or any scheduler):

- digest: daily, e.g. `cloud_cost_collector.py`
- booking: monthly on the 1st, `cloud_cost_collector.py --book`

## Config

See [`config.example.yaml`](config.example.yaml). Rules:

- **No secrets in config.** Bot tokens and webhook URLs are read from env vars
  (names are configurable). The repo never holds credentials or cloud IDs.
- Enable only the providers/sinks you use (`enabled: true`).
- `field_map` lets you rename the booking payload fields to match your endpoint.

### Booking payload

The webhook sink POSTs JSON like:

```json
{
  "description": "Microsoft Azure — cloud (Jan 2026)",
  "amount": 142.50,
  "currency": "USD",
  "category": "cloud-hosting",
  "vendor": "Microsoft Azure",
  "expense_date": "2026-02-01",
  "period": "Jan 2026",
  "recurring": true,
  "recurring_period": "monthly"
}
```

Point `CCC_WEBHOOK_URL` at anything that accepts that — your own API, a no-code
hook, or an accounting wrapper.

## Architecture

```
cloud_cost_collector.py   # orchestrator: load config, run providers, format, dispatch
providers/
  azure.py   gcp.py   aws.py   # each exposes mtd(cfg) and last_month(cfg)
sinks/
  telegram.py   webhook.py     # send(cfg, text) / post_expense(cfg, expense)
setup_wizard.py           # automatable setup + the unavoidable manual clicks
```

Adding a provider = drop a module in `providers/` exposing `mtd()` /
`last_month()` plus `ICON`, `LABEL`, `VENDOR`, and register it in the orchestrator.

## License

MIT.
