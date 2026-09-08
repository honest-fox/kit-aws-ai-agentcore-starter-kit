#!/usr/bin/env bash
#
# Kit preflight — check everything the deploy needs before you spend 20
# minutes finding out. Run from the repo root:
#
#   ./scripts/preflight.sh
#
# Exits 0 if you're clear to deploy, 1 otherwise.

set -uo pipefail

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; D=$'\033[2m'; B=$'\033[1m'; X=$'\033[0m'
else
  R=''; G=''; Y=''; D=''; B=''; X=''
fi

FAILED=0
WARNED=0

ok()   { printf '  %s✓%s %s\n' "$G" "$X" "$1"; }
warn() { printf '  %s!%s %s\n' "$Y" "$X" "$1"; WARNED=1; }
bad()  { printf '  %s✗%s %s\n' "$R" "$X" "$1"; FAILED=1; }
hint() { printf '%s\n' "$D$1$X"; }

printf '\n%sKit preflight%s\n\n' "$B" "$X"

# ---------------------------------------------------------------- tooling

if command -v node >/dev/null 2>&1; then
  NODE_MAJOR=$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)
  if [ "$NODE_MAJOR" -ge 20 ] 2>/dev/null; then
    ok "Node.js $(node -v)"
  else
    bad "Node.js $(node -v) — Kit needs 20 or later."
  fi
else
  bad "Node.js not found. Install 20 or later: https://nodejs.org"
fi

if command -v uv >/dev/null 2>&1; then
  ok "uv $(uv --version 2>/dev/null | awk '{print $2}')"
else
  bad "uv not found. Install it: https://docs.astral.sh/uv/"
fi

if command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then
    ok "Docker running"
  else
    bad "Docker is installed but not running. Start Docker Desktop and retry."
  fi
else
  bad "Docker not found. Install it: https://docker.com"
fi

if command -v aws >/dev/null 2>&1; then
  ok "AWS CLI $(aws --version 2>&1 | awk '{print $1}' | cut -d/ -f2)"
else
  bad "AWS CLI not found. Install it: https://aws.amazon.com/cli/"
  printf '\n%s✗ Preflight failed.%s\n\n' "$R" "$X"
  exit 1
fi

if command -v agentcore >/dev/null 2>&1; then
  ok "AgentCore CLI $(agentcore --version 2>/dev/null || echo '')"
else
  warn "agentcore not on PATH. Install: npm install -g @aws/agentcore"
fi

# ------------------------------------------------------------ target file

TARGETS="agentcore/aws-targets.json"
TARGET_NAME="${1:-default}"
WANT_ACCOUNT=""
WANT_REGION=""

if [ ! -f "$TARGETS" ]; then
  bad "$TARGETS not found."
  hint "    cp agentcore/aws-targets.example.json $TARGETS"
  hint "    then edit it: your 12-digit account id, and your region"
  hint "    (Run this from the repo root, not from agentcore/.)"
else
  read -r WANT_ACCOUNT WANT_REGION <<<"$(python3 - "$TARGETS" "$TARGET_NAME" <<'PY' 2>/dev/null
import json, sys
try:
    targets = json.load(open(sys.argv[1]))
    for t in targets:
        if t.get("name") == sys.argv[2]:
            print(t.get("account", ""), t.get("region", ""))
            break
except Exception:
    pass
PY
)"

  if [ -z "$WANT_ACCOUNT" ]; then
    bad "No target named '$TARGET_NAME' in $TARGETS."
  elif [ "$WANT_ACCOUNT" = "123456789012" ]; then
    bad "$TARGETS still has the placeholder account id."
    hint "    Edit it and put your real 12-digit account id in."
  else
    ok "Target '$TARGET_NAME' → account $WANT_ACCOUNT, region $WANT_REGION"
  fi
fi

# ------------------------------------------------------------ credentials
#
# This is the one that catches people. The AgentCore CLI has no --profile
# flag: it reads the standard AWS SDK provider chain. So `aws sso login
# --profile foo` on its own is invisible to it — the token lands in a cache
# the default chain never consults.

CALLER=$(aws sts get-caller-identity --query 'Account' --output text 2>/dev/null)

if [ -n "$CALLER" ] && [ "$CALLER" != "None" ]; then
  if [ -n "${AWS_PROFILE:-}" ]; then
    ok "AWS credentials valid (account $CALLER, via AWS_PROFILE=$AWS_PROFILE)"
  else
    ok "AWS credentials valid (account $CALLER)"
  fi

  if [ -n "$WANT_ACCOUNT" ] && [ "$WANT_ACCOUNT" != "123456789012" ] && [ "$CALLER" != "$WANT_ACCOUNT" ]; then
    bad "Wrong account: credentials are for $CALLER, $TARGETS says $WANT_ACCOUNT."
    hint "    Deploying now would build Kit in the wrong account."
  fi
else
  bad "AWS credentials not visible to the default chain."
  printf '\n'
  hint "    agentcore has no --profile flag. It reads the standard"
  hint "    AWS SDK chain, so an SSO login on a named profile alone"
  hint "    will not reach it."

  # Collect working profiles with their account ids, so we can recommend one
  # that actually matches the deployment target rather than whatever sorts
  # first.
  WORKING=""
  MATCHING=""
  for p in $(aws configure list-profiles 2>/dev/null); do
    ACCT=$(aws sts get-caller-identity --profile "$p" --query 'Account' --output text \
             --cli-connect-timeout 3 --cli-read-timeout 8 2>/dev/null)
    if [ -n "$ACCT" ] && [ "$ACCT" != "None" ]; then
      WORKING="$WORKING $p:$ACCT"
      if [ -n "$WANT_ACCOUNT" ] && [ "$ACCT" = "$WANT_ACCOUNT" ]; then
        MATCHING="$MATCHING $p"
      fi
    fi
  done

  printf '\n'
  if [ -n "$WORKING" ]; then
    hint "    Your profiles that DO work:"
    for entry in $WORKING; do
      pname="${entry%%:*}"; pacct="${entry##*:}"
      if [ -n "$WANT_ACCOUNT" ] && [ "$pacct" = "$WANT_ACCOUNT" ]; then
        printf '      %s%-28s%s account %s %s(matches your target)%s\n' \
          "$B" "$pname" "$X" "$pacct" "$G" "$X"
      else
        printf '      %-28s account %s %s(different account)%s\n' \
          "$pname" "$pacct" "$D" "$X"
      fi
    done
    printf '\n'
    hint "    Fix, either:"
    if [ -n "$MATCHING" ]; then
      FIRST=$(echo $MATCHING | awk '{print $1}')
      printf '      %sexport AWS_PROFILE=%s%s\n' "$B" "$FIRST" "$X"
    else
      printf '      %sexport AWS_PROFILE=<a profile for account %s>%s\n' \
        "$B" "$WANT_ACCOUNT" "$X"
      hint "      # none of your working profiles are in that account"
    fi
    hint "      # or make [default] an SSO profile in ~/.aws/config"
  else
    hint "    No configured profile currently has valid credentials."
    hint "    Log in first, e.g.:"
    printf '      %saws sso login --profile <your-profile>%s\n' "$B" "$X"
    hint "    then re-run this check with AWS_PROFILE set."
  fi

  if [ -f "$HOME/.aws/credentials" ] && grep -q '^\[default\]' "$HOME/.aws/credentials" 2>/dev/null; then
    printf '\n'
    hint "    Note: you have a [default] block in ~/.aws/credentials."
    hint "    The credentials file overrides ~/.aws/config for the same"
    hint "    profile name, so stale keys there shadow your SSO setup"
    hint "    no matter how many times you log in. Check there first."
  fi
fi

# -------------------------------------------------------------- bootstrap
#
# CDK bootstrap is per account+region and easy to forget when trying a new
# region. The AgentCore CLI's own "Check bootstrap status" step passes even
# when the region is not bootstrapped, so the failure surfaces minutes into
# the deploy instead of up front.

if [ -n "$WANT_REGION" ] && [ -n "$CALLER" ] && [ "$CALLER" != "None" ]; then
  if aws ssm get-parameter --name /cdk-bootstrap/hnb659fds/version \
       --region "$WANT_REGION" >/dev/null 2>&1; then
    ok "CDK bootstrapped in $WANT_REGION"
  else
    warn "$WANT_REGION is not CDK-bootstrapped."
    hint "    \`agentcore deploy\` will NOT do this for you (CLI 0.28.1),"
    hint "    interactively or otherwise. Bootstrap first, or the deploy"
    hint "    fails minutes in with a missing-SSM-parameter error:"
    printf '      %s(cd agentcore/cdk && npx cdk bootstrap aws://%s/%s)%s\n' \
      "$B" "$WANT_ACCOUNT" "$WANT_REGION" "$X"
    hint "    Note: bootstrap creates a customer-managed KMS key, roughly"
    hint "    US\$1/month, which outlives the Kit stack."
  fi
fi

# ---------------------------------------------------------------- verdict

printf '\n'
if [ "$FAILED" -ne 0 ]; then
  printf '%s✗ Not ready to deploy.%s Fix the above, then re-run.\n\n' "$R" "$X"
  exit 1
fi
if [ "$WARNED" -ne 0 ]; then
  printf '%s✓ Ready to deploy%s (with warnings above).\n\n' "$G" "$X"
else
  printf '%s✓ Ready to deploy.%s\n\n' "$G" "$X"
fi
if [ "$TARGET_NAME" = "default" ]; then
  printf '  Next: %sagentcore deploy%s\n\n' "$B" "$X"
else
  printf '  Next: %sagentcore deploy --target %s%s\n\n' "$B" "$TARGET_NAME" "$X"
fi
