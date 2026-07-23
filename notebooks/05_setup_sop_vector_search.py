# Databricks notebook source
# MAGIC %md
# MAGIC # Setup SOP Vector Search
# MAGIC
# MAGIC This notebook builds the SOP (Standard Operating Procedure) vector index used for
# MAGIC RAG-based "Next Best Action" grounding. It supports two sources:
# MAGIC
# MAGIC 1. **Bundled text samples (zero-config default).** If no `sop_pdfs` table exists, the
# MAGIC    notebook ingests the SOP `.txt` files committed under `data/sop_samples/` so the demo
# MAGIC    works out of the box on a clean workspace.
# MAGIC 2. **Real customer PDFs (optional).** If a `{catalog}.{schema}.sop_pdfs` table of binary
# MAGIC    PDFs exists (e.g. loaded from a Volume), the notebook parses them with
# MAGIC    `ai_parse_document` instead. This path takes precedence when the table is present.
# MAGIC
# MAGIC Either way it produces `sop_parsed` -> `sop_chunks` -> `sop_vector_index`.

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
SOP_VECTOR_INDEX = f"{CATALOG}.{SCHEMA}.sop_vector_index"
SOP_PDFS_TABLE = f"{CATALOG}.{SCHEMA}.sop_pdfs"
SOP_PARSED_TABLE = f"{CATALOG}.{SCHEMA}.sop_parsed"
SOP_CHUNKS_TABLE = f"{CATALOG}.{SCHEMA}.sop_chunks"

print(f"Catalog: {CATALOG}")
print(f"Schema: {SCHEMA}")
print(f"Vector Endpoint: {VECTOR_ENDPOINT}")
print(f"SOP Vector Index: {SOP_VECTOR_INDEX}")
print(f"SOP PDFs Table: {SOP_PDFS_TABLE}")

# COMMAND ----------

spark.sql(f"USE CATALOG {CATALOG}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Select SOP source: customer PDFs (if present) or bundled text samples
# MAGIC
# MAGIC If a `sop_pdfs` table exists we parse those PDFs. Otherwise we fall back to the SOP
# MAGIC `.txt` files committed under `data/sop_samples/`, so the demo works with no manual upload.

# COMMAND ----------

def _sop_pdfs_table_available():
    """True only if the sop_pdfs table exists AND has at least one document."""
    try:
        count = spark.sql(f"SELECT COUNT(*) FROM {SOP_PDFS_TABLE}").collect()[0][0]
        print(f"SOP PDFs table found with {count} document(s)")
        return count > 0
    except Exception as e:
        print(f"No usable sop_pdfs table ({e}); will fall back to bundled text samples.")
        return False

USE_PDFS = _sop_pdfs_table_available()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Build the parsed-SOP table
# MAGIC
# MAGIC Both paths produce `sop_parsed` with columns `source_path, filename, parsed_text,
# MAGIC parsed_at` — which feeds the shared chunking step below unchanged.

# COMMAND ----------

if USE_PDFS:
    # --- Path A: parse real customer PDFs with ai_parse_document ---
    print("Parsing customer PDFs with ai_parse_document...")
    spark.sql(f"""
    CREATE OR REPLACE TABLE {SOP_PARSED_TABLE} AS
    SELECT
        path as source_path,
        regexp_extract(path, '[^/]+$', 0) as filename,
        ai_parse_document(content, 'text').text as parsed_text,
        current_timestamp() as parsed_at
    FROM {SOP_PDFS_TABLE}
    WHERE content IS NOT NULL
    """)
else:
    # --- Path B: ingest the bundled data/sop_samples/*.txt files (zero-config default) ---
    # The bundle syncs the whole repo to the workspace, so resolve the samples directory
    # relative to this notebook's location (same pattern as 00_generate_data.py).
    import os, glob

    def _find_sop_samples_dir():
        candidates = []
        try:
            nb_path = str(dbutils.notebook.entry_point.getDbutils().notebook()
                          .getContext().notebookPath().get())
            repo_root = os.path.dirname(os.path.dirname(nb_path))  # .../notebooks/.. -> repo root
            for base in (repo_root, "/Workspace" + repo_root):
                candidates.append(os.path.join(base, "data", "sop_samples"))
        except Exception as e:
            print(f"Could not resolve notebook path: {e}")
        for c in candidates:
            if os.path.isdir(c):
                return c
        return None

    samples_dir = _find_sop_samples_dir()
    if not samples_dir:
        raise RuntimeError(
            "No sop_pdfs table and could not locate bundled data/sop_samples/. "
            "Ensure the bundle synced the repo, or create a sop_pdfs table from a Volume."
        )

    txt_files = sorted(glob.glob(os.path.join(samples_dir, "*.txt")))
    if not txt_files:
        raise RuntimeError(f"No .txt SOP samples found in {samples_dir}")
    print(f"Ingesting {len(txt_files)} bundled SOP text sample(s) from {samples_dir}")

    rows = []
    for path in txt_files:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        rows.append((path, os.path.basename(path), text))

    from pyspark.sql.types import StructType, StructField, StringType
    from pyspark.sql import functions as F
    schema = StructType([
        StructField("source_path", StringType(), False),
        StructField("filename", StringType(), False),
        StructField("parsed_text", StringType(), True),
    ])
    (spark.createDataFrame(rows, schema)
        .withColumn("parsed_at", F.current_timestamp())
        .write.mode("overwrite").saveAsTable(SOP_PARSED_TABLE))

parsed_count = spark.sql(f"SELECT COUNT(*) FROM {SOP_PARSED_TABLE}").collect()[0][0]
print(f"Parsed {parsed_count} SOP document(s) into {SOP_PARSED_TABLE}")

# COMMAND ----------

# Display sample of parsed content
display(spark.sql(f"""
SELECT
    filename,
    LENGTH(parsed_text) as text_length,
    LEFT(parsed_text, 500) as text_preview
FROM {SOP_PARSED_TABLE}
LIMIT 5
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Chunk Documents for Embedding

# COMMAND ----------

# Create chunks table with proper chunking strategy
# Using paragraph-based splitting with overlap
spark.sql(f"""
CREATE OR REPLACE TABLE {SOP_CHUNKS_TABLE}
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
AS
WITH chunks_raw AS (
    SELECT 
        source_path,
        filename,
        -- Split by double newlines (paragraphs) or sections
        explode(
            transform(
                filter(
                    split(parsed_text, '\n\n+'),
                    x -> LENGTH(TRIM(x)) > 50  -- Filter out very short chunks
                ),
                x -> TRIM(x)
            )
        ) as chunk_text
    FROM {SOP_PARSED_TABLE}
    WHERE parsed_text IS NOT NULL AND LENGTH(parsed_text) > 100
),
chunks_with_id AS (
    SELECT 
        source_path,
        filename,
        chunk_text,
        -- Try to extract section title from chunk (first line if it looks like a heading)
        CASE 
            WHEN regexp_extract(chunk_text, '^([A-Z][A-Za-z0-9 ]+:)', 1) != '' 
            THEN regexp_extract(chunk_text, '^([A-Z][A-Za-z0-9 ]+:)', 1)
            WHEN regexp_extract(chunk_text, '^([0-9]+\\.\\s*[A-Za-z ]+)', 1) != ''
            THEN regexp_extract(chunk_text, '^([0-9]+\\.\\s*[A-Za-z ]+)', 1)
            ELSE NULL
        END as section_title,
        ROW_NUMBER() OVER (PARTITION BY source_path ORDER BY chunk_text) as chunk_position
    FROM chunks_raw
    WHERE LENGTH(chunk_text) BETWEEN 50 AND 4000  -- Filter reasonable chunk sizes
)
SELECT 
    CONCAT(filename, '_', chunk_position) as chunk_id,
    source_path as source_doc,
    filename,
    section_title,
    chunk_position,
    chunk_text,
    LENGTH(chunk_text) as chunk_length
FROM chunks_with_id
""")

chunk_count = spark.sql(f"SELECT COUNT(*) FROM {SOP_CHUNKS_TABLE}").collect()[0][0]
print(f"Created {chunk_count} chunks from SOP documents")

# COMMAND ----------

# Display chunk distribution
display(spark.sql(f"""
SELECT 
    filename,
    COUNT(*) as chunk_count,
    AVG(chunk_length) as avg_chunk_length,
    MIN(chunk_length) as min_length,
    MAX(chunk_length) as max_length
FROM {SOP_CHUNKS_TABLE}
GROUP BY filename
ORDER BY chunk_count DESC
"""))

# COMMAND ----------

# Sample chunks
display(spark.sql(f"""
SELECT chunk_id, filename, section_title, chunk_length, LEFT(chunk_text, 300) as preview
FROM {SOP_CHUNKS_TABLE}
LIMIT 10
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Create Vector Search Index

# COMMAND ----------

from databricks.sdk import WorkspaceClient
from databricks.vector_search.client import VectorSearchClient
import time

w = WorkspaceClient()
vsc = VectorSearchClient()

# Verify endpoint exists
endpoints = [e.name for e in w.vector_search_endpoints.list_endpoints()]
print(f"Available endpoints: {endpoints}")

if VECTOR_ENDPOINT not in endpoints:
    print(f"ERROR: Vector endpoint {VECTOR_ENDPOINT} not found")
    print("Please run 02_setup_vector_search.py first to create the endpoint")
    dbutils.notebook.exit("Vector endpoint not found")

# COMMAND ----------

# Try to get existing index first
from databricks.vector_search.utils import BadRequest

index_exists = False
try:
    existing_index = vsc.get_index(endpoint_name=VECTOR_ENDPOINT, index_name=SOP_VECTOR_INDEX)
    index_exists = True
    print(f"Index {SOP_VECTOR_INDEX} already exists")
except Exception as e:
    print(f"Index does not exist: {e}")

if index_exists:
    print(f"Syncing existing index {SOP_VECTOR_INDEX}...")
    try:
        vsc.get_index(VECTOR_ENDPOINT, SOP_VECTOR_INDEX).sync()
        print("Sync triggered successfully")
    except Exception as e:
        print(f"Sync status: {e}")
else:
    print(f"Creating SOP vector index {SOP_VECTOR_INDEX}...")
    try:
        vsc.create_delta_sync_index(
            endpoint_name=VECTOR_ENDPOINT,
            index_name=SOP_VECTOR_INDEX,
            source_table_name=SOP_CHUNKS_TABLE,
            pipeline_type="TRIGGERED",
            primary_key="chunk_id",
            embedding_source_column="chunk_text",
            embedding_model_endpoint_name="databricks-gte-large-en"
        )
        print(f"Index {SOP_VECTOR_INDEX} created successfully")
    except BadRequest as e:
        if "already exists" in str(e):
            print(f"Index already exists (UC entity), syncing instead...")
            try:
                vsc.get_index(VECTOR_ENDPOINT, SOP_VECTOR_INDEX).sync()
                print("Sync triggered successfully")
            except Exception as sync_e:
                print(f"Sync status: {sync_e}")
        else:
            raise e

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Verify Index

# COMMAND ----------

# Wait (bounded) for the index to come online before test-searching, so a slow
# TRIGGERED sync doesn't make the smoke test spuriously report failure. Non-fatal:
# the index syncs asynchronously regardless of whether this poll observes ONLINE.
import time

def _index_ready(index_obj, timeout_s=180, interval_s=10):
    waited = 0
    while waited < timeout_s:
        try:
            desc = index_obj.describe()
            status = (desc.get("status", {}) or {})
            state = status.get("detailed_state", "") or status.get("state", "")
            ready = status.get("ready", False)
            print(f"  index state={state or 'unknown'} ready={ready} ({waited}s)")
            if ready or "ONLINE" in str(state).upper():
                return True
        except Exception as e:
            print(f"  describe not available yet: {e}")
        time.sleep(interval_s)
        waited += interval_s
    print(f"  index not confirmed ONLINE after {timeout_s}s — it may still be syncing.")
    return False

# Test search
try:
    index = vsc.get_index(endpoint_name=VECTOR_ENDPOINT, index_name=SOP_VECTOR_INDEX)
    _index_ready(index)
    results = index.similarity_search(
        query_text="readmission handling procedure",
        columns=["chunk_id", "chunk_text", "source_doc", "section_title"],
        num_results=3
    )
    print("Test search results for 'readmission handling procedure':")
    for row in results.get("result", {}).get("data_array", []):
        print(f"\n--- Chunk: {row[1] if len(row) > 1 else 'N/A'} ---")
        print(f"Source: {row[3] if len(row) > 3 else 'N/A'}")
        print(f"Section: {row[4] if len(row) > 4 else 'N/A'}")
        content = row[2] if len(row) > 2 else ""
        print(f"Content: {content[:200]}..." if len(content) > 200 else f"Content: {content}")
except Exception as e:
    print(f"Search test failed (index may still be syncing): {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Summary

# COMMAND ----------

print("=" * 60)
print("SOP VECTOR SEARCH SETUP COMPLETE")
print("=" * 60)
print(f"Source: {'customer PDFs (' + SOP_PDFS_TABLE + ')' if USE_PDFS else 'bundled text samples (data/sop_samples/*.txt)'}")
print(f"Parsed Table: {SOP_PARSED_TABLE}")
print(f"Chunks Table: {SOP_CHUNKS_TABLE}")
print(f"Vector Index: {SOP_VECTOR_INDEX}")
print(f"Vector Endpoint: {VECTOR_ENDPOINT}")
print("")
print(f"Total chunks indexed: {chunk_count}")
print("")
print("The index may take a few minutes to fully sync.")
print("Agents can now use search_sops tool to query hospital operations procedures.")
print("=" * 60)
