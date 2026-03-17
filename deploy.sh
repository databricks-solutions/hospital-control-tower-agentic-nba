#!/bin/bash
set -e

TARGET="${1:-dev}"
PROFILE="${2:-}"
APP_NAME="${TARGET}-investment-intel"
PROFILE_ARG=""
[[ -n "$PROFILE" ]] && PROFILE_ARG="-p $PROFILE"

# Resolve the workspace root path where the bundle was deployed
BUNDLE_ROOT=$(databricks bundle validate -t "$TARGET" $PROFILE_ARG 2>/dev/null | grep '"workspace_root_path"' | head -1 | sed 's/.*: *"\(.*\)".*/\1/')
if [[ -z "$BUNDLE_ROOT" ]]; then
  DEPLOYING_USER=$(databricks current-user me $PROFILE_ARG 2>/dev/null | grep '"userName"' | head -1 | sed 's/.*: *"\(.*\)".*/\1/')
  BUNDLE_NAME=$(grep '^  name:' databricks.yml | head -1 | sed 's/.*: *//')
  BUNDLE_ROOT="/Workspace/Users/${DEPLOYING_USER}/.bundle/${BUNDLE_NAME}/${TARGET}"
fi
APP_SOURCE_PATH="${BUNDLE_ROOT}/files/app"

echo "=== Deploying Investment Intel (target: $TARGET) ==="
echo ""

# Step 1: Deploy bundle
echo "[1/7] Deploying bundle..."
databricks bundle deploy -t "$TARGET" $PROFILE_ARG || { echo "FAILED: bundle deploy"; exit 1; }
echo "  Bundle deployed successfully"

# Step 2: Create tables (must run before vector search so source tables exist)
echo ""
echo "[2/7] Setting up tables..."
databricks bundle run setup_lakebase -t "$TARGET" $PROFILE_ARG \
    || { echo "FAILED: setup_lakebase"; exit 1; }
echo "  Tables created successfully"

# Step 3: Setup vector search (creates endpoint + fund_documents index)
echo ""
echo "[3/7] Setting up vector search..."
databricks bundle run setup_vector_search -t "$TARGET" $PROFILE_ARG || { echo "FAILED: setup_vector_search"; exit 1; }
echo "  Vector search setup complete"

# Step 4: Setup SOP vector search (creates investment_policy index on same endpoint)
echo ""
echo "[4/7] Setting up SOP vector search..."
databricks bundle run setup_sop_vector_search -t "$TARGET" $PROFILE_ARG || { echo "WARNING: SOP vector search setup had issues (SOPs may not be loaded yet)"; }
echo "  SOP vector search setup complete"

# Step 5: Grant permissions (runs AFTER all resources exist)
echo ""
echo "[5/7] Granting permissions to app service principal..."
databricks bundle run grant_permissions -t "$TARGET" $PROFILE_ARG \
    || { echo "FAILED: grant_permissions"; exit 1; }
echo "  Permissions granted successfully"

# Step 6: Run diagnostics
echo ""
echo "[6/7] Running diagnostics..."
databricks bundle run diagnostic_check -t "$TARGET" $PROFILE_ARG || { echo "WARNING: diagnostic_check had issues"; }
echo "  Diagnostics complete"

# Step 7: Deploy the app
echo ""
echo "[7/7] Deploying app..."
echo "  Source: $APP_SOURCE_PATH"
databricks apps deploy "$APP_NAME" --source-code-path "$APP_SOURCE_PATH" $PROFILE_ARG \
    || { echo "WARNING: App deploy failed — you may need to deploy manually from the workspace"; }
echo "  App deployment triggered"

echo ""
echo "=== SUCCESS ==="
echo "App URL: Check Databricks workspace for $APP_NAME"
echo ""
