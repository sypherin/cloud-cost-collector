#!/usr/bin/env bash
# Apply keep-recent-N + delete-older-than cleanup policies to EVERY Artifact
# Registry repo in a GCP project. Container images from `gcloud run deploy
# --source` accumulate forever by default — a single project can quietly hoard
# 50GB+ of dead build images (~$0.10/GB/mo).
#
# Usage: ./gcp_artifact_registry_cleanup.sh <PROJECT_ID> [KEEP_COUNT] [MAX_AGE_DAYS]
set -euo pipefail
PROJECT="${1:?usage: $0 <PROJECT_ID> [KEEP_COUNT=10] [MAX_AGE_DAYS=30]}"
KEEP="${2:-10}"
DAYS="${3:-30}"
POLICY=$(mktemp)
cat > "$POLICY" <<JSON
[
  {"name": "keep-recent-${KEEP}", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": ${KEEP}}},
  {"name": "delete-stale", "action": {"type": "Delete"}, "condition": {"olderThan": "$(( DAYS * 86400 ))s"}}
]
JSON
# location lives inside the resource name: projects/<p>/locations/<loc>/repositories/<repo>
gcloud artifacts repositories list --project "$PROJECT" --format=json \
| python3 -c "
import json,sys
for r in json.load(sys.stdin):
    p = r['name'].split('/')
    print(p[3], p[5], round(int(r.get('sizeBytes',0))/1e9,1))" \
| while read -r LOC REPO GB; do
    echo "-> $PROJECT [$LOC] $REPO (${GB}GB)"
    gcloud artifacts repositories set-cleanup-policies "$REPO" \
      --project "$PROJECT" --location "$LOC" \
      --policy="$POLICY" --no-dry-run
  done
rm -f "$POLICY"
echo "Done. Cleanup executes asynchronously (~1 day)."
