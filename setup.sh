#!/bin/bash
# First-time provisioning for the Hospital Control Tower demo.
#
# Config is pure DABs now — no files are generated. Workspace-specific values and
# the CLI profile come from .databricks-env.sh (see .databricks-env.sh.example).
#
# Usage:
#   source .databricks-env.sh
#   ./setup.sh [target]            # target defaults to dev
#   ./setup.sh dev --skip-data     # skip the (slow) data generation job
#   ./setup.sh dev --skip-to-app   # only (re)deploy + run the app, skip setup jobs
#
# For routine redeploys after setup, you don't need this script — just:
#   source .databricks-env.sh && databricks bundle deploy -t dev \
#     && databricks bundle run hospital_ops_app -t dev
set -euo pipefail

TARGET="dev"
SKIP_DATA=false
SKIP_TO_APP=false
for arg in "$@"; do
  case "$arg" in
    --skip-data)   SKIP_DATA=true ;;
    --skip-to-app) SKIP_TO_APP=true ;;
    -*)            echo "Unknown flag: $arg" >&2; exit 1 ;;
    *)             TARGET="$arg" ;;
  esac
done

echo "=========================================="
echo " Hospital Control Tower — Setup"
echo " Target:  $TARGET"
echo " Profile: ${DATABRICKS_CONFIG_PROFILE:-<none — set via .databricks-env.sh>}"
echo "=========================================="

# --- Pre-flight ---
command -v databricks >/dev/null 2>&1 || {
  echo "ERROR: 'databricks' CLI not found. https://docs.databricks.com/dev-tools/cli/install.html" >&2
  exit 1
}
if [[ -z "${BUNDLE_VAR_catalog:-}" || -z "${BUNDLE_VAR_warehouse_id:-}" || -z "${BUNDLE_VAR_vector_search_endpoint:-}" ]]; then
  echo "ERROR: Required BUNDLE_VAR_* not set. Run: source .databricks-env.sh" >&2
  echo "  (copy .databricks-env.sh.example to .databricks-env.sh and fill in your values)" >&2
  exit 1
fi
echo "  catalog=$BUNDLE_VAR_catalog  warehouse=$BUNDLE_VAR_warehouse_id  vs=$BUNDLE_VAR_vector_search_endpoint"

run_job() {  # run_job <job_key> <fatal|warn>
  local job="$1" mode="${2:-fatal}"
  echo "  -> $job"
  if databricks bundle run "$job" -t "$TARGET"; then
    return 0
  elif [[ "$mode" == "warn" ]]; then
    echo "  WARNING: $job failed (non-fatal) — continue and check manually later." >&2
    return 1   # non-zero so callers can detect the failure (guard bare calls with '|| true')
  else
    echo "FAILED: $job" >&2; exit 1
  fi
}

# --- Deploy the bundle (jobs + app resource) ---
echo "[1/8] Deploying bundle..."
databricks bundle deploy -t "$TARGET"

if [[ "$SKIP_TO_APP" == "false" ]]; then
  # --- Data + data model ---
  if [[ "$SKIP_DATA" == "false" ]]; then
    echo "[2/8] Generating data..."
    run_job generate_data fatal
  else
    echo "[2/8] Skipping data generation (--skip-data)"
  fi

  echo "[3/8] Setting up data model..."
  run_job setup_data_model fatal

  echo "[4/8] Setting up Lakebase / analysis table..."
  run_job setup_lakebase warn || true   # optional; UC-Delta fallback covers analysis writes

  echo "[5/8] Building encounter vector index..."
  run_job setup_vector_search fatal

  echo "[6/8] Building SOP vector index..."
  # Self-sufficient now: falls back to bundled data/sop_samples/*.txt when no sop_pdfs
  # table exists, so SOP grounding (the demo's Next-Best-Action core) works on a clean
  # workspace. Fatal because a silent failure here guts the headline capability.
  run_job setup_sop_vector_search fatal
fi

# --- Deploy app code & start ---
echo "[7/8] Deploying app code..."
run_job hospital_ops_app fatal

# --- Grant permissions to the app service principal (retry for SP provisioning delay) ---
echo "[8/8] Granting permissions..."
GRANT_OK=false
for attempt in 1 2 3; do
  if databricks bundle run grant_permissions -t "$TARGET"; then GRANT_OK=true; break; fi
  echo "  attempt $attempt/3 failed, retrying in 15s..."; sleep 15
done
[[ "$GRANT_OK" == "true" ]] || echo "  WARNING: grant_permissions failed after 3 attempts — run manually later." >&2

# --- Diagnostics (non-fatal) ---
DIAG_OK=true
run_job diagnostic_check warn || DIAG_OK=false

echo ""
echo "=========================================="
if [[ "$GRANT_OK" == "true" && "$DIAG_OK" == "true" ]]; then
  echo " Setup complete — open Databricks > Apps > $TARGET-hospital-control-tower"
else
  echo " Setup finished WITH WARNINGS — the app is deployed but needs attention:"
  [[ "$GRANT_OK" == "true" ]]  || echo "   - grant_permissions did not succeed; the app may lack table/index access."
  [[ "$DIAG_OK"  == "true" ]]  || echo "   - diagnostic_check reported problems; review its job output."
  echo " Open Databricks > Apps > $TARGET-hospital-control-tower and check the items above."
fi
echo "=========================================="
