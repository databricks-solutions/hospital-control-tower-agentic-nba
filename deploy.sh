#!/bin/bash
set -e

TARGET="${1:-dev}"
PROFILE="${2:-}"
APP_NAME="${TARGET}-investment-intel"
PROFILE_ARG=""
[[ -n "$PROFILE" ]] && PROFILE_ARG="-p $PROFILE"

echo "=== Redeploying Investment Intel (target: $TARGET) ==="
echo ""

# --- Read variables and regenerate app/app.yaml ---
read_var() {
  local key="$1"
  grep -A2 "^  ${key}:" variables.yml | grep "default:" \
    | sed 's/.*default: *"\{0,1\}\([^"]*\)"\{0,1\}/\1/' \
    | sed 's/^ *//;s/ *$//'
}

CATALOG=$(read_var "catalog")
SCHEMA=$(read_var "schema")
WAREHOUSE_ID=$(read_var "warehouse_id")
VECTOR_ENDPOINT=$(read_var "vector_search_endpoint")
LLM_ORCHESTRATOR=$(read_var "llm_model_orchestrator")
LLM_RAG=$(read_var "llm_model_rag")

if [[ -z "$CATALOG" || -z "$WAREHOUSE_ID" || -z "$VECTOR_ENDPOINT" ]]; then
  echo "ERROR: Required variables (catalog, warehouse_id, vector_search_endpoint) are empty in variables.yml."
  echo "  Edit variables.yml or run setup.sh first."
  exit 1
fi

echo "Regenerating app/app.yaml from variables.yml..."
cat > app/app.yaml << APPYAML
command:
  - sh
  - -c
  - pip install -r requirements.txt && npm install && npm run build && gunicorn --bind 0.0.0.0:8000 --workers 1 --threads 4 --timeout 600 api_server:app

env:
  - name: DATABRICKS_WAREHOUSE_ID
    value: "${WAREHOUSE_ID}"

  - name: CATALOG
    value: "${CATALOG}"

  - name: SCHEMA
    value: "${SCHEMA}"

  - name: VECTOR_SEARCH_ENDPOINT
    value: "${VECTOR_ENDPOINT}"

  - name: LLM_MODEL_ORCHESTRATOR
    value: "${LLM_ORCHESTRATOR:-databricks-claude-sonnet-4-5}"

  - name: LLM_MODEL_RAG
    value: "${LLM_RAG:-databricks-claude-sonnet-4-5}"

  - name: AUTONOMOUS_INTERVAL_SECONDS
    value: "3600"

  - name: AUTO_START_AUTONOMOUS
    value: "false"

  - name: MLFLOW_EXPERIMENT
    value: "/Shared/investment-intelligence-agent"
APPYAML
echo "  app/app.yaml written"

# Generate databricks.yml from template
cp databricks.yml.template databricks.yml

echo "[1/2] Deploying bundle..."
databricks bundle deploy -t "$TARGET" $PROFILE_ARG || { echo "FAILED: bundle deploy"; exit 1; }
echo "  Bundle deployed"

echo "[2/2] Deploying app..."
databricks bundle run investment_intel_app -t "$TARGET" $PROFILE_ARG \
    || { echo "WARNING: bundle run for app failed — you may need to deploy manually from the workspace"; }
echo "  App deployment triggered"

echo ""
echo "=== SUCCESS ==="
echo "App URL: Check Databricks workspace for $APP_NAME"
echo ""
