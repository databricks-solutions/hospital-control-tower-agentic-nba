# Databricks notebook source
# MAGIC %md
# MAGIC # Setup Vector Search for Hospital Control Tower
# MAGIC
# MAGIC Creates embeddings from all encounter data for semantic search.

# COMMAND ----------

# MAGIC %pip install databricks-vectorsearch --quiet
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# Configuration
dbutils.widgets.text("var.catalog", "", "Catalog")
dbutils.widgets.text("var.schema", "med_logistics_nba", "Schema")
dbutils.widgets.text("var.vector_search_endpoint", "", "Vector Search Endpoint")
CATALOG = dbutils.widgets.get("var.catalog")
SCHEMA = dbutils.widgets.get("var.schema")
VECTOR_ENDPOINT = dbutils.widgets.get("var.vector_search_endpoint")
VECTOR_INDEX = f"{CATALOG}.{SCHEMA}.encounters_vector_index"
SOURCE_TABLE = f"{CATALOG}.{SCHEMA}.encounters_for_embedding"

print(f"Catalog: {CATALOG}")
print(f"Schema: {SCHEMA}")
print(f"Vector Endpoint: {VECTOR_ENDPOINT}")
print(f"Vector Index: {VECTOR_INDEX}")
print(f"Source Table: {SOURCE_TABLE}")

# COMMAND ----------

spark.sql(f"USE CATALOG {CATALOG}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Create Vector Search Endpoint (if not exists)

# COMMAND ----------

from databricks.sdk import WorkspaceClient
from databricks.vector_search.client import VectorSearchClient
import time

w = WorkspaceClient()
vsc = VectorSearchClient()

# Check if endpoint exists
endpoints = [e.name for e in w.vector_search_endpoints.list_endpoints()]
print(f"Existing endpoints: {endpoints}")

if VECTOR_ENDPOINT not in endpoints:
    print(f"Creating vector search endpoint: {VECTOR_ENDPOINT}")
    from databricks.sdk.service.vectorsearch import EndpointType
    w.vector_search_endpoints.create_endpoint(name=VECTOR_ENDPOINT, endpoint_type=EndpointType.STANDARD)
    
    # Wait for endpoint to be ready
    print("Waiting for endpoint to be ready...")
    for i in range(60):
        try:
            status = w.vector_search_endpoints.get_endpoint(VECTOR_ENDPOINT)
            if status.endpoint_status and status.endpoint_status.state.value == "ONLINE":
                print(f"Endpoint {VECTOR_ENDPOINT} is ONLINE")
                break
        except:
            pass
        time.sleep(10)
        print(f"  Waiting... ({i*10}s)")
else:
    print(f"Endpoint {VECTOR_ENDPOINT} already exists")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Create Rich Embedding Table (combining all data)

# COMMAND ----------

# Check source table exists
try:
    count = spark.sql(f"SELECT COUNT(*) FROM {CATALOG}.{SCHEMA}.dim_encounters").collect()[0][0]
    print(f"Source table dim_encounters exists with {count} rows")
except Exception as e:
    print(f"ERROR: dim_encounters not found: {e}")
    print("Please ensure the source data exists before running this notebook")
    dbutils.notebook.exit("Source table not found")

# COMMAND ----------

# Create enriched embedding table with text from multiple tables
spark.sql(f"""
CREATE OR REPLACE TABLE {SOURCE_TABLE}
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
AS
WITH drug_agg AS (
    SELECT encounter_id, CONCAT('Total drug cost: $', ROUND(SUM(total_cost), 2)) as drug_summary
    FROM {CATALOG}.{SCHEMA}.fact_drug_costs
    GROUP BY encounter_id
),
ed_info AS (
    SELECT encounter_id, MAX(CONCAT('ED wait time: ', ROUND(wait_minutes, 1), ' minutes, acuity ', acuity_level)) as ed_summary
    FROM {CATALOG}.{SCHEMA}.fact_ed_wait_times
    GROUP BY encounter_id
)
SELECT 
    e.encounter_id as encounter_id,
    e.hospital,
    e.department,
    e.payer,
    e.is_readmission,
    CONCAT(
        'Encounter ', e.encounter_id, ' at ', e.hospital, ' in ', e.department, '. ',
        'Payer: ', e.payer, '. ',
        CASE WHEN e.is_readmission THEN 'READMISSION. ' ELSE 'No readmission. ' END,
        'Length of stay: ', COALESCE(CAST(e.los_days AS STRING), 'unknown'), ' days. ',
        'Discharge day: ', COALESCE(e.discharge_day_of_week, 'unknown'), '. ',
        'DRG: ', COALESCE(e.drg_code, 'unknown'), '. ',
        COALESCE(d.drug_summary, ''), ' ',
        COALESCE(ed.ed_summary, '')
    ) as text_content
FROM {CATALOG}.{SCHEMA}.dim_encounters e
LEFT JOIN drug_agg d ON d.encounter_id = e.encounter_id
LEFT JOIN ed_info ed ON ed.encounter_id = e.encounter_id
""")

count = spark.sql(f"SELECT COUNT(*) FROM {SOURCE_TABLE}").collect()[0][0]
print(f"Created {SOURCE_TABLE} with {count} rows")

# COMMAND ----------

# Display sample
display(spark.sql(f"SELECT encounter_id, hospital, department, is_readmission, LEFT(text_content, 200) as text_preview FROM {SOURCE_TABLE} LIMIT 5"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Create Vector Index

# COMMAND ----------

from databricks.vector_search.utils import BadRequest

# Try to get existing index first
index_exists = False
try:
    existing_index = vsc.get_index(endpoint_name=VECTOR_ENDPOINT, index_name=VECTOR_INDEX)
    index_exists = True
    print(f"Index {VECTOR_INDEX} already exists")
except Exception as e:
    print(f"Index does not exist or cannot be accessed: {e}")

if index_exists:
    print(f"Syncing existing index {VECTOR_INDEX}...")
    try:
        vsc.get_index(VECTOR_ENDPOINT, VECTOR_INDEX).sync()
        print("Sync triggered successfully")
    except Exception as e:
        print(f"Sync may already be in progress or not needed: {e}")
else:
    print(f"Creating index {VECTOR_INDEX}...")
    try:
        vsc.create_delta_sync_index(
            endpoint_name=VECTOR_ENDPOINT,
            index_name=VECTOR_INDEX,
            source_table_name=SOURCE_TABLE,
            pipeline_type="TRIGGERED",
            primary_key="encounter_id",
            embedding_source_column="text_content",
            embedding_model_endpoint_name="databricks-gte-large-en"
        )
        print(f"Index {VECTOR_INDEX} created")
    except BadRequest as e:
        if "already exists" in str(e):
            print(f"Index already exists (UC entity), syncing instead...")
            try:
                vsc.get_index(VECTOR_ENDPOINT, VECTOR_INDEX).sync()
                print("Sync triggered successfully")
            except Exception as sync_e:
                print(f"Sync status: {sync_e}")
        else:
            raise e

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Verify

# COMMAND ----------

# Wait a moment for index to be ready
import time
time.sleep(5)

# Test search
try:
    index = vsc.get_index(endpoint_name=VECTOR_ENDPOINT, index_name=VECTOR_INDEX)
    results = index.similarity_search(
        query_text="encounters with readmissions at Hospital A",
        columns=["encounter_id", "hospital", "is_readmission"],
        num_results=3
    )
    print("Test search results:")
    for row in results.get("result", {}).get("data_array", []):
        print(f"  {row}")
except Exception as e:
    print(f"Search test failed (index may still be syncing): {e}")

# COMMAND ----------

print("=" * 60)
print("VECTOR SEARCH SETUP COMPLETE")
print("=" * 60)
print(f"Endpoint: {VECTOR_ENDPOINT}")
print(f"Index: {VECTOR_INDEX}")
print(f"Source: {SOURCE_TABLE}")
print("")
print("The index may take a few minutes to fully sync.")
print("Run 03_grant_permissions.py next.")
print("=" * 60)
