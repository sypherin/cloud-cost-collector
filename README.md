# Cloud Cost Collector

**Multi-cloud cost, with no dashboard — it books itself into your accounting and
answers to your AI agent.** Across Azure, GCP, and AWS.

Three things make this different from everything else in the space:

- **No dashboard.** Every other cost tool (OpenCost, Infracost, Vantage,
  Datadog) gives you yet another screen to babysit. This one doesn't. Your cloud
  bill should just *show up where your money already lives* and ping you when it
  spikes.
- **It books itself.** On the 1st, it posts last month's final actual into your
  accounting/CRM as recurring `cloud-hosting` opex — one entry per provider. No
  other tool closes that loop; they all stop at "here's a chart."
- **It's agent-native.** Ships with an [MCP server](#mcp-server), so Claude /
  Cursor / your own agent can just *ask* "what's my cloud spend this month"
  instead of you opening a console. (AWS has an official cost MCP server too —
  but it's AWS-only. This is multi-cloud.)

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

The fastest path is the interactive wizard — it asks which clouds you use,
prompts for the ids, asks where to send the digest, then writes `config.yaml`
and `.env` for you (and runs the GCP/Azure setup steps):

```bash
pip install -r requirements.txt           # + boto3 if you use AWS
python cloud_cost_collector.py init       # answer a few questions
set -a && source .env && set +a           # load the secrets it wrote
python cloud_cost_collector.py --dry-run  # verify output
```

Prefer to do it by hand? The manual path still works:

```bash
cp config.example.yaml config.yaml       # edit: enable providers, add ids
cp .env.example .env                      # add bot token / webhook url, then source it
python setup_wizard.py setup             # creates GCP datasets, prints the manual toggles
python cloud_cost_collector.py --dry-run  # verify output
```

### GCP setup (the one manual step)

GCP has no API to read your spend, so you enable a BigQuery billing export
once per billing account. The wizard creates the dataset for you; the export
toggle is the only thing you must click.

1. **Find your billing account id(s).** [console.cloud.google.com/billing](https://console.cloud.google.com/billing)
   → each account shows an id like `XXXXXX-XXXXXX-XXXXXX`. Note one project under
   each account to store the export.
2. **Run the wizard** (`init`) and enter each account id + storage project. It
   runs `bq mk` to create the `billing_export` dataset in each project.
3. **Flip the export toggle** (no API for this) — the wizard prints a deep-link
   per account:
   `https://console.cloud.google.com/billing/<ACCOUNT_ID>/export/bigquery`
   → **Standard usage cost** → **Edit settings** → pick the project + the
   `billing_export` dataset → **Save**.
4. **Wait a few hours.** The first export table appears ~4–24h after you flip
   the toggle. The collector skips not-yet-created tables silently, so it's safe
   to run in the meantime.

Once a table exists, `--dry-run` will show that account's spend.

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

## MCP server

There's an MCP server (`mcp_server.py`) so any MCP client — Claude Desktop,
Cursor, your own agent — can query your spend as tools instead of you opening a
console. It reuses the same `config.yaml` and providers as the CLI.

Tools exposed:

| Tool | What it does |
|------|--------------|
| `list_providers` | which clouds are enabled and ready |
| `get_costs(period, provider)` | spend (`mtd` or `last_month`), per-provider, with a top-service breakdown |
| `book_last_month(dry_run)` | **write** — posts last month's actual per provider to your webhook. Defaults to `dry_run=true` |

Register it in your client (stdio). Example for Claude Desktop
(`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "cloud-cost-collector": {
      "command": "python",
      "args": ["/abs/path/to/cloud-cost-collector/mcp_server.py"],
      "env": { "CCC_CONFIG": "/abs/path/to/config.yaml" }
    }
  }
}
```

Needs the `mcp` package: `pip install mcp`.

## Architecture

```
cloud_cost_collector.py   # orchestrator: load config, run providers, format, dispatch
providers/
  azure.py   gcp.py   aws.py   # each exposes mtd(cfg) and last_month(cfg)
sinks/
  telegram.py   webhook.py     # send(cfg, text) / post_expense(cfg, expense)
setup_wizard.py           # `init` (interactive) + `setup` (datasets + manual clicks)
mcp_server.py             # MCP server exposing costs as tools
```

Adding a provider = drop a module in `providers/` exposing `mtd()` /
`last_month()` plus `ICON`, `LABEL`, `VENDOR`, and register it in the orchestrator.

## License

MIT.
