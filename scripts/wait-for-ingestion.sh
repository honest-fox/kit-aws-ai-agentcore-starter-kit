#!/usr/bin/env bash
#
# Wait for every Bedrock Knowledge Base data source to finish ingesting.
#
# Retrieval cases scored against a knowledge base that is still ingesting
# look exactly like a quality regression: the agent answers, the answer is
# fluent, and the citation it needed is simply not there yet. That failure
# mode is indistinguishable from a real one in the scorecard, so the eval
# run must not start until ingestion has actually completed.
#
# This exits non-zero and loudly rather than ever letting the caller
# proceed on an unknown state.
#
#   ./scripts/wait-for-ingestion.sh
#
# Environment:
#   KIT_EVAL_STACK        CloudFormation stack name (default AgentCore-kit-default)
#   AWS_REGION            region (falls back to AWS_DEFAULT_REGION)
#   KIT_INGEST_TIMEOUT    seconds to wait before giving up (default 1200)
#   KIT_INGEST_INTERVAL   seconds between polls (default 15)
#
# Exit codes:
#   0  every data source reports COMPLETE
#   1  a data source reported FAILED/STOPPED, or the wait timed out
#   2  configuration error — no stack, no knowledge base output, no data sources

set -euo pipefail

STACK="${KIT_EVAL_STACK:-AgentCore-kit-default}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
TIMEOUT="${KIT_INGEST_TIMEOUT:-1200}"
INTERVAL="${KIT_INGEST_INTERVAL:-15}"

if [ -z "$REGION" ]; then
  echo "wait-for-ingestion: no region. Set AWS_REGION." >&2
  exit 2
fi

aws_cfn() { aws cloudformation "$@" --region "$REGION"; }
aws_kb()  { aws bedrock-agent "$@" --region "$REGION"; }

# The knowledge base id comes from a stack output whose logical id CDK
# suffixes with a hash (KitKbKitKnowledgeBaseIdOutput31190AF9 today). That
# hash changes whenever the construct path changes, so match on the stable
# part of the key rather than pinning the whole thing.
if ! OUTPUTS_JSON="$(aws_cfn describe-stacks --stack-name "$STACK" --output json 2>&1)"; then
  echo "wait-for-ingestion: could not describe stack '$STACK' in $REGION." >&2
  echo "$OUTPUTS_JSON" >&2
  exit 2
fi

KB_ID="$(printf '%s' "$OUTPUTS_JSON" | python3 -c '
import json, sys
stacks = json.load(sys.stdin).get("Stacks") or [{}]
outs = stacks[0].get("Outputs") or []
hits = [o["OutputValue"] for o in outs if "KnowledgeBaseId" in o.get("OutputKey", "")]
print(hits[0] if len(hits) == 1 else "")
sys.exit(0 if len(hits) == 1 else 3)
' 2>/dev/null)" || {
  echo "wait-for-ingestion: expected exactly one stack output whose key contains" >&2
  echo "  'KnowledgeBaseId' on stack '$STACK'. Found none, or more than one." >&2
  echo "  Outputs present:" >&2
  printf '%s' "$OUTPUTS_JSON" | python3 -c '
import json, sys
for o in (json.load(sys.stdin).get("Stacks") or [{}])[0].get("Outputs") or []:
    print("   ", o.get("OutputKey"))
' >&2 || true
  exit 2
}

echo "wait-for-ingestion: knowledge base $KB_ID (stack $STACK, region $REGION)"

if ! DS_IDS="$(aws_kb list-data-sources --knowledge-base-id "$KB_ID" \
    --query 'dataSourceSummaries[].dataSourceId' --output text 2>&1)"; then
  echo "wait-for-ingestion: could not list data sources for $KB_ID." >&2
  echo "$DS_IDS" >&2
  exit 2
fi

# `--output text` gives an empty string, or the literal "None", for no results.
if [ -z "$DS_IDS" ] || [ "$DS_IDS" = "None" ]; then
  echo "wait-for-ingestion: knowledge base $KB_ID has no data sources." >&2
  echo "  Nothing would ever be ingested, so retrieval cases cannot pass." >&2
  exit 2
fi

echo "wait-for-ingestion: data sources: $DS_IDS"
echo "wait-for-ingestion: timeout ${TIMEOUT}s, polling every ${INTERVAL}s"

DEADLINE=$(( $(date +%s) + TIMEOUT ))

while :; do
  pending=0
  summary=""

  for ds in $DS_IDS; do
    # Most recently started job for this data source. No jobs yet is a
    # legitimate "still waiting" state early in a deploy, not an error.
    if ! status="$(aws_kb list-ingestion-jobs \
        --knowledge-base-id "$KB_ID" --data-source-id "$ds" \
        --query 'sort_by(ingestionJobSummaries, &startedAt)[-1].status' \
        --output text 2>&1)"; then
      echo "wait-for-ingestion: could not list ingestion jobs for $ds." >&2
      echo "$status" >&2
      exit 2
    fi

    summary="$summary $ds=$status"

    case "$status" in
      COMPLETE)
        ;;
      FAILED|STOPPED|STOPPING)
        echo >&2
        echo "wait-for-ingestion: data source $ds ended in $status." >&2
        echo "  Refusing to run retrieval cases against a knowledge base that" >&2
        echo "  did not finish ingesting — the scorecard would blame the agent." >&2
        aws_kb list-ingestion-jobs --knowledge-base-id "$KB_ID" \
          --data-source-id "$ds" \
          --query 'sort_by(ingestionJobSummaries, &startedAt)[-1].[status,failureReasons]' \
          --output text >&2 || true
        exit 1
        ;;
      *)
        # STARTING, IN_PROGRESS, or None (no job started yet).
        pending=$(( pending + 1 ))
        ;;
    esac
  done

  if [ "$pending" -eq 0 ]; then
    echo "wait-for-ingestion: all data sources COMPLETE —$summary"
    exit 0
  fi

  now=$(date +%s)
  if [ "$now" -ge "$DEADLINE" ]; then
    echo >&2
    echo "wait-for-ingestion: timed out after ${TIMEOUT}s with $pending data source(s)" >&2
    echo "  still ingesting —$summary" >&2
    echo "  Not proceeding: retrieval cases scored now would report a quality" >&2
    echo "  regression that is really an empty index." >&2
    exit 1
  fi

  echo "wait-for-ingestion: $pending pending —$summary ($(( DEADLINE - now ))s left)"
  sleep "$INTERVAL"
done
