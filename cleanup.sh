#!/bin/bash
set -e

TARGET="${1:-dev}"
PROFILE="${2:-}"

PROFILE_ARG=""
[[ -n "$PROFILE" && "$PROFILE" != --* ]] && PROFILE_ARG="-p $PROFILE"

# Reuse read_var from setup.sh
read_var() {
  local key="$1"
  local val
  val=$(grep -A2 "^  ${key}:" variables.yml | grep "default:" | sed 's/.*default: *"\{0,1\}\([^"]*\)"\{0,1\}/\1/' | tr -d ' ')
  if [[ -z "$val" ]] && [[ -f databricks.yml ]]; then
    val=$(grep -A20 "^  ${TARGET}:" databricks.yml | grep "      ${key}:" | head -1 | sed 's/.*: *"\{0,1\}\([^"#]*\)"\{0,1\}.*/\1/' | tr -d ' ')
  fi
  echo "$val"
}

CATALOG=$(read_var "catalog")
SCHEMA=$(read_var "schema")
WAREHOUSE_ID=$(read_var "warehouse_id")
VECTOR_ENDPOINT=$(read_var "vector_search_endpoint")

echo "=========================================="
echo " Investment Intel -- Cleanup"
echo " Target: $TARGET"
echo " Catalog: ${CATALOG:-<not set>}"
echo " Schema: ${SCHEMA:-<not set>}"
echo " Vector Endpoint: ${VECTOR_ENDPOINT:-<not set>}"
echo "=========================================="
echo ""
echo "This will DELETE all resources created by setup.sh."
read -p "Are you sure? (y/N) " -n 1 -r
echo ""
[[ ! $REPLY =~ ^[Yy]$ ]] && { echo "Aborted."; exit 0; }
echo ""

# --- Step 1: Delete vector search indexes ---
if [[ -n "$VECTOR_ENDPOINT" && -n "$CATALOG" && -n "$SCHEMA" ]]; then
  echo "[1/4] Deleting vector search indexes..."
  for INDEX in "${CATALOG}.${SCHEMA}.fund_documents_vector_index" "${CATALOG}.${SCHEMA}.investment_policy_vector_index"; do
    echo "  Deleting index: $INDEX"
    databricks vector-search indexes delete "$INDEX" $PROFILE_ARG 2>/dev/null \
      && echo "    Deleted" \
      || echo "    Not found or already deleted"
  done

  echo "  Deleting vector search endpoint: $VECTOR_ENDPOINT"
  databricks vector-search endpoints delete "$VECTOR_ENDPOINT" $PROFILE_ARG 2>/dev/null \
    && echo "    Deleted" \
    || echo "    Not found or already deleted"
else
  echo "[1/4] Skipping vector search cleanup (variables not set)"
fi
echo ""

# --- Step 2: Drop tables and schema ---
if [[ -n "$CATALOG" && -n "$SCHEMA" && -n "$WAREHOUSE_ID" ]]; then
  echo "[2/4] Dropping tables, views, and schema..."

  TABLES=(
    "dim_encounters"
    "fact_drug_costs"
    "fact_staffing"
    "fact_ed_wait_times"
    "fact_operational_kpis"
    "analysis_outputs"
    "encounters_for_embedding"
    "sop_pdfs"
    "sop_parsed"
    "sop_chunks"
  )

  for TABLE in "${TABLES[@]}"; do
    echo "  DROP TABLE IF EXISTS ${CATALOG}.${SCHEMA}.${TABLE}"
    databricks api post /api/2.0/sql/statements $PROFILE_ARG --json "{
      \"warehouse_id\": \"${WAREHOUSE_ID}\",
      \"statement\": \"DROP TABLE IF EXISTS ${CATALOG}.${SCHEMA}.${TABLE}\",
      \"wait_timeout\": \"30s\"
    }" > /dev/null 2>&1 || echo "    Warning: failed to drop ${TABLE}"
  done

  echo "  DROP VIEW IF EXISTS ${CATALOG}.${SCHEMA}.portfolio_overview"
  databricks api post /api/2.0/sql/statements $PROFILE_ARG --json "{
    \"warehouse_id\": \"${WAREHOUSE_ID}\",
    \"statement\": \"DROP VIEW IF EXISTS ${CATALOG}.${SCHEMA}.portfolio_overview\",
    \"wait_timeout\": \"30s\"
  }" > /dev/null 2>&1 || echo "    Warning: failed to drop view"

  echo "  DROP SCHEMA IF EXISTS ${CATALOG}.${SCHEMA} CASCADE"
  databricks api post /api/2.0/sql/statements $PROFILE_ARG --json "{
    \"warehouse_id\": \"${WAREHOUSE_ID}\",
    \"statement\": \"DROP SCHEMA IF EXISTS ${CATALOG}.${SCHEMA} CASCADE\",
    \"wait_timeout\": \"30s\"
  }" > /dev/null 2>&1 || echo "    Warning: failed to drop schema"

  echo "  Done"
else
  echo "[2/4] Skipping table/schema cleanup (catalog, schema, or warehouse_id not set)"
fi
echo ""

# --- Step 3: Clean up generated app.yaml ---
echo "[3/4] Removing generated app/app.yaml..."
rm -f app/app.yaml
echo "  Done"
echo ""

# --- Step 4: Destroy bundle ---
echo "[4/4] Running databricks bundle destroy..."
databricks bundle destroy -t "$TARGET" $PROFILE_ARG --auto-approve \
  || echo "  Warning: bundle destroy had issues"
echo ""

echo "=========================================="
echo " Cleanup complete."
echo "=========================================="
