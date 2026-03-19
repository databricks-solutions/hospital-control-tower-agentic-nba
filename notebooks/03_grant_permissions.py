# Databricks notebook source
# MAGIC %md
# MAGIC # Grant Permissions to App Service Principal
# MAGIC 
# MAGIC Grants permissions for the Hospital Control Tower app to access all data tables, models, and vector search.

# COMMAND ----------

# Configuration
dbutils.widgets.text("var.catalog", "", "Catalog")
dbutils.widgets.text("var.schema", "med_logistics_nba", "Schema")
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
    "fact_operational_kpis",
    "hospital_overview",
    "encounters_for_embedding",
    "sop_pdfs",
    "sop_parsed",
    "sop_chunks",
]

# Tables the app reads AND writes (INSERT/UPDATE/DELETE)
WRITE_TABLES = [
    "dim_encounters",
    "analysis_outputs",
    "fact_drug_costs",
    "fact_staffing",
    "fact_ed_wait_times",
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
ENCOUNTER_VECTOR_INDEX = f"{CATALOG}.{SCHEMA}.encounters_vector_index"
SOP_VECTOR_INDEX = f"{CATALOG}.{SCHEMA}.sop_vector_index"

print(f"Vector Endpoint: {VECTOR_ENDPOINT}")
print(f"Encounter Vector Index: {ENCOUNTER_VECTOR_INDEX}")
print(f"SOP Vector Index: {SOP_VECTOR_INDEX}")

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

print("\nGranting SELECT on vector indexes:")
for idx_name in [ENCOUNTER_VECTOR_INDEX, SOP_VECTOR_INDEX]:
    try:
        spark.sql(f"GRANT SELECT ON TABLE {idx_name} TO {PRINCIPAL}")
        print(f"  OK: SELECT on {idx_name}")
    except Exception as e:
        print(f"  SKIP: SELECT on {idx_name}: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Grant Foundation Model Access

# COMMAND ----------

MODEL_ENDPOINTS = [
    "databricks-claude-sonnet-4-5",
]

for endpoint_name in MODEL_ENDPOINTS:
    try:
        from databricks.sdk.service.serving import ServingEndpointAccessControlRequest, ServingEndpointPermissionLevel
        w.serving_endpoints.set_permissions(
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
print(f"  - CAN_USE on {VECTOR_ENDPOINT}")
print(f"  - Encounter Index: {ENCOUNTER_VECTOR_INDEX}")
print(f"  - SOP Index: {SOP_VECTOR_INDEX}")
print(f"")
print("Models:")
print(f"  - CAN_QUERY on: {', '.join(MODEL_ENDPOINTS)}")
print("=" * 60)
