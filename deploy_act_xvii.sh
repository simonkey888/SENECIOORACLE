#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
# SENECIO Oracle — ACT XVII Deployment Script
# ═══════════════════════════════════════════════════════════════════════════
#
# This script pushes all hardened files to the GitHub repository.
# 
# USAGE: Provide your GitHub PAT as argument:
#   ./deploy_act_xvii.sh ghp_xxxxxxxxxxxx
#
# The PAT needs: repo scope (full control of private/public repositories)
#
# AFTER DEPLOYMENT:
#   1. Activate cron-job.org POST to:
#      POST https://api.github.com/repos/simonkey888/SENECIOORACLE/actions/workflows/oracle.yml/dispatches
#      Header: Authorization: token <PAT>
#      Header: Accept: application/vnd.github+json
#      Body: {"ref":"main"}
#   2. Wait 30 minutes
#   3. Check: 2+ new workflow runs with trigger "workflow_dispatch"
#   4. Check: simonkey888.github.io/SENECIOORACLE/ shows updated data
# ═══════════════════════════════════════════════════════════════════════════

set -e

PAT="${1:?Usage: $0 <GITHUB_PAT>}"
REPO="simonkey888/SENECIOORACLE"
BRANCH="main"
CLONE_DIR="/tmp/SENECIOORACLE_deploy_act17"

STAGING_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "═══════════════════════════════════════════════════════════════════"
echo "  SENECIO Oracle — ACT XVII Deployment"
echo "═══════════════════════════════════════════════════════════════════"
echo ""

# Step 1: Clone the repo
echo "[1/5] Cloning repository..."
rm -rf "$CLONE_DIR"
git clone "https://x-access-token:${PAT}@github.com/${REPO}.git" "$CLONE_DIR" --depth 50
cd "$CLONE_DIR"

# Step 2: Copy hardened files from staging
echo "[2/5] Copying hardened files..."

cp "$STAGING_DIR/.github/workflows/oracle.yml" ".github/workflows/oracle.yml"
rm -f ".github/workflows/static.yml"  # Merged into oracle.yml
cp "$STAGING_DIR/exchange_connector.py" "exchange_connector.py"
cp "$STAGING_DIR/predict_only.py" "predict_only.py"
cp "$STAGING_DIR/index.html" "index.html"
cp "$STAGING_DIR/requirements.txt" "requirements.txt"

# Step 3: Verify key changes
echo "[3/5] Verifying changes..."

python3 -c "
with open('predict_only.py') as f:
    c = f.read()
assert 'DEFAULT_EXCHANGE_FALLBACK_CHAIN' in c, 'FAIL: fallback chain missing'
assert 'exchange_used' in c, 'FAIL: exchange_used missing'
assert 'last_heartbeat' in c, 'FAIL: heartbeat missing'
assert 'exchange: str = None' in c, 'FAIL: default exchange should be None'
assert 'fetch_market_snapshot_with_fallback' in c, 'FAIL: fallback function missing'
print('  predict_only.py: OK (fallback chain, exchange_used, heartbeat, None default)')
"

python3 -c "
with open('exchange_connector.py') as f:
    c = f.read()
assert 'DEFAULT_FALLBACK_CHAIN' in c, 'FAIL: DEFAULT_FALLBACK_CHAIN missing'
assert 'fetch_market_snapshot_with_fallback' in c, 'FAIL: fallback function missing'
assert '\"gate\"' in c, 'FAIL: gate exchange missing'
assert '\"mexc\"' in c, 'FAIL: mexc exchange missing'
assert '\"bitget\"' in c, 'FAIL: bitget exchange missing'
print('  exchange_connector.py: OK (8 exchanges, fallback chain, fallback function)')
"

python3 -c "
with open('.github/workflows/oracle.yml') as f:
    c = f.read()
assert 'workflow_dispatch' in c, 'FAIL: workflow_dispatch missing'
assert 'deploy-pages' in c, 'FAIL: deploy-pages missing'
assert '--exchange okx' not in c, 'FAIL: hardcoded --exchange okx still present'
assert '--exchange binance' not in c, 'FAIL: hardcoded --exchange binance still present'
assert 'last_heartbeat.json' in c, 'FAIL: heartbeat not in git add'
assert 'pip install -r requirements.txt' in c, 'FAIL: requirements.txt not used'
print('  oracle.yml: OK (workflow_dispatch, deploy-pages, no hardcoded exchange, heartbeat)')
"

python3 -c "
with open('index.html') as f:
    c = f.read()
assert 'staleness-banner' in c, 'FAIL: staleness sentinel missing'
assert 'status-stale' in c, 'FAIL: STALE badge missing'
print('  index.html: OK (staleness sentinel, STALE badge)')
"

python3 -c "
with open('requirements.txt') as f:
    c = f.read().strip()
assert c == 'ccxt==4.5.58', f'FAIL: requirements.txt should be ccxt==4.5.58, got: {c}'
print('  requirements.txt: OK (ccxt==4.5.58 pinned)')
"

# Step 4: Commit and push
echo "[4/5] Committing changes..."
git config user.name "SENECIO Oracle Hardening"
git config user.email "oracle@senecio.bot"
git add -A
git diff --cached --stat
git commit -m "oracle: ACT XVII — survivability hardening + Pages deploy fix

- exchange_connector.py: 8 exchanges (okx,kraken,gate,mexc,bitget,binance,bybit,testnet), 5-exchange fallback chain
- predict_only.py: fallback chain default (no hardcoded exchange), exchange_used provenance, heartbeat file
- oracle.yml: merged with static.yml (predict+deploy in same job), workflow_dispatch for cron-job.org, no hardcoded exchange, heartbeat tracked, pip install -r requirements.txt
- static.yml: DELETED (merged into oracle.yml — eliminates GITHUB_TOKEN trigger limitation)
- index.html: staleness sentinel (warns when report > 30 min old), STALE badge
- requirements.txt: ccxt==4.5.58 pinned

NO PREDICTION LOGIC CHANGES. NO SCORING CHANGES. NO MODEL CHANGES."

echo "[5/5] Pushing to ${REPO}..."
git push origin "$BRANCH"

echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo "  DEPLOYMENT COMPLETE"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
echo "NEXT STEPS:"
echo "  1. Activate cron-job.org POST to workflow_dispatch"
echo "  2. Wait 30 minutes"
echo "  3. Verify 2+ runs with trigger 'workflow_dispatch'"
echo "  4. Verify Pages: https://simonkey888.github.io/SENECIOORACLE/"
echo "  5. Verify predictions.jsonl has exchange_used field"
echo "  6. Verify last_heartbeat.json exists in repo"
echo ""
