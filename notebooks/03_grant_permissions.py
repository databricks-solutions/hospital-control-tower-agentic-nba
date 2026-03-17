# Databricks notebook source
# MAGIC %md
# MAGIC # Grant Permissions to App Service Principal
# MAGIC 
# MAGIC Grants permissions for the Investment Portfolio Intelligence app to access all data tables, models, and vector search.

# COMMAND ----------

# Configuration
dbutils.widgets.text("var.catalog", "", "Catalog")
dbutils.widgets.text("var.schema", "investment_intel", "Schema")
dbutils.widgets.text("var.app_name", "dev-hospital-control-tower", "App Name")
CATALOG = dbutils.widgets.get("var.catalog")
SCHEMA = dbutils.widgets.get("var.schema")
APP_NAME = dbutils.widgets.get("var.app_name")

print(f"Catalog: {CATALOG}")
print(f"Schema: {SCHEMA}")
print(f"App Name: {APP_NAME}")

# COMMAND ----------

# Look up the app's service principal via SDK (requires databricks-sdk>=0.90.0 pinned in jobs.yml)
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()

try:
    app_info = w.apps.get(name=APP_NAME)
except Exception as e:
    raise RuntimeError(
        f"Could not find app '{APP_NAME}'. Deploy the app first (setup.sh or Databricks Apps UI), then re-run this notebook.\n"
        f"Error: {e}"
    )

SP_NAME = app_info.service_principal_name
SP_ID = str(app_info.service_principal_id or "")
SP_CLIENT_ID = app_info.service_principal_client_id
if not SP_CLIENT_ID:
    raise RuntimeError(f"App '{APP_NAME}' has no service_principal_client_id. Ensure the app was deployed and has an associated service principal.")
PRINCIPAL = f"`{SP_CLIENT_ID}`"
print(f"Resolved SP from app '{APP_NAME}': {PRINCIPAL} (id={SP_ID})")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Grant Catalog and Schema Access
# MAGIC These are critical -- if they fail, nothing else works.

# COMMAND ----------

spark.sql(f"USE CATALOG {CATALOG}")

# USE CATALOG -- must succeed or the whole notebook fails
spark.sql(f"GRANT USE CATALOG ON CATALOG {CATALOG} TO {PRINCIPAL}")
print(f"OK: Granted USE CATALOG on {CATALOG} to {PRINCIPAL}")

# USE SCHEMA -- must succeed
spark.sql(f"GRANT USE SCHEMA ON SCHEMA {CATALOG}.{SCHEMA} TO {PRINCIPAL}")
print(f"OK: Granted USE SCHEMA on {CATALOG}.{SCHEMA} to {PRINCIPAL}")

# CREATE TABLE -- needed so the app can self-heal analysis_outputs on startup
spark.sql(f"GRANT CREATE TABLE ON SCHEMA {CATALOG}.{SCHEMA} TO {PRINCIPAL}")
print(f"OK: Granted CREATE TABLE on {CATALOG}.{SCHEMA} to {PRINCIPAL}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Grant Table Permissions (All Data Tables + Output Tables)

# COMMAND ----------

# Tables the app reads only
READ_TABLES = [
    "fact_portfolio_kpis",
    "portfolio_overview",
    "fund_documents_for_embedding",
    "investment_policy_docs",
    "investment_policy_parsed",
    "investment_policy_chunks",
]

# Tables the app reads AND writes (INSERT/UPDATE/DELETE)
WRITE_TABLES = [
    "dim_funds",
    "analysis_outputs",
    "fact_fund_performance",
    "fact_portfolio_holdings",
    "fact_fund_flows",
]

print("Granting SELECT permissions:")
for table in READ_TABLES:
    try:
        spark.sql(f"GRANT SELECT ON TABLE {CATALOG}.{SCHEMA}.{table} TO {PRINCIPAL}")
        print(f"  OK: SELECT on {table}")
    except Exception as e:
        print(f"  SKIP: SELECT on {table}: {e}")

print("\nGranting SELECT + MODIFY permissions:")
for table in WRITE_TABLES:
    try:
        spark.sql(f"GRANT SELECT, MODIFY ON TABLE {CATALOG}.{SCHEMA}.{table} TO {PRINCIPAL}")
        print(f"  OK: SELECT, MODIFY on {table}")
    except Exception as e:
        print(f"  SKIP: MODIFY on {table}: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Grant Vector Search Permissions

# COMMAND ----------

dbutils.widgets.text("var.vector_search_endpoint", "", "Vector Search Endpoint")
VECTOR_ENDPOINT = dbutils.widgets.get("var.vector_search_endpoint")
FUND_DOCUMENTS_VECTOR_INDEX = f"{CATALOG}.{SCHEMA}.fund_documents_vector_index"
INVESTMENT_POLICY_VECTOR_INDEX = f"{CATALOG}.{SCHEMA}.investment_policy_vector_index"

print(f"Vector Endpoint: {VECTOR_ENDPOINT}")
print(f"Fund Documents Vector Index: {FUND_DOCUMENTS_VECTOR_INDEX}")
print(f"Investment Policy Vector Index: {INVESTMENT_POLICY_VECTOR_INDEX}")

# Grant CAN_USE on vector search endpoint (needed to query indexes hosted on it)
try:
    from databricks.sdk.service.iam import AccessControlRequest, PermissionLevel
    w.permissions.update(
        request_object_type="vector-search-endpoints",
        request_object_id=VECTOR_ENDPOINT,
        access_control_list=[
            AccessControlRequest(
                service_principal_name=SP_NAME or APP_NAME,
                permission_level=PermissionLevel.CAN_USE
            )
        ]
    )
    print(f"OK: Granted CAN_USE on vector endpoint {VECTOR_ENDPOINT}")
except Exception as e:
    print(f"SKIP: Vector endpoint permission: {e}")

# VS index SELECT grants (fund_documents_vector_index, investment_policy_vector_index)
# and their source tables are now handled automatically via uc_securable resources
# declared in resources/apps.yml. No manual grants needed here.
print("\nVector index SELECT grants: handled by uc_securable app resources in apps.yml")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Grant Foundation Model Access

# COMMAND ----------

MODEL_ENDPOINTS = [
    "databricks-claude-sonnet-4-5",
    "databricks-gte-large-en",  # embedding model used by vector search delta sync indexes
]

from databricks.sdk.service.serving import ServingEndpointAccessControlRequest, ServingEndpointPermissionLevel

for endpoint_name in MODEL_ENDPOINTS:
    try:
        w.serving_endpoints.update_permissions(
            serving_endpoint_id=endpoint_name,
            access_control_list=[
                ServingEndpointAccessControlRequest(
                    service_principal_name=SP_NAME or APP_NAME,
                    permission_level=ServingEndpointPermissionLevel.CAN_QUERY
                )
            ]
        )
        print(f"OK: Granted CAN_QUERY on {endpoint_name}")
    except Exception as e:
        print(f"SKIP: Model {endpoint_name}: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

print("=" * 60)
print("PERMISSIONS SUMMARY")
print("=" * 60)
print(f"Service Principal: {PRINCIPAL}")
print(f"Service Principal ID: {SP_ID or 'N/A'}")
print(f"")
print("Data Access:")
print(f"  - USE CATALOG on {CATALOG}")
print(f"  - USE SCHEMA on {CATALOG}.{SCHEMA}")
print(f"  - SELECT on: {', '.join(READ_TABLES)}")
print(f"  - SELECT + MODIFY on: {', '.join(WRITE_TABLES)}")
print(f"")
print("Vector Search:")
print(f"  - CAN_USE on endpoint: {VECTOR_ENDPOINT}")
print(f"  - Index SELECT grants: via uc_securable in apps.yml (auto-granted)")
print(f"")
print("Serving Endpoints:")
print(f"  - CAN_QUERY on: {', '.join(MODEL_ENDPOINTS)}")
print(f"  (includes embedding model for vector search)")
print("=" * 60)
