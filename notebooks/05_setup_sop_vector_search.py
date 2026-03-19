# Databricks notebook source
# MAGIC %md
# MAGIC # Setup SOP Vector Search
# MAGIC 
# MAGIC This notebook ingests hospital operations policies and procedures (SOP) PDFs using ai_parse_document, chunks the text,
# MAGIC and creates a vector search index for RAG-based SOP retrieval.

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
# MAGIC ## 1. Check SOP PDFs Table Exists

# COMMAND ----------

try:
    count = spark.sql(f"SELECT COUNT(*) FROM {SOP_PDFS_TABLE}").collect()[0][0]
    print(f"SOP PDFs table found with {count} documents")
    display(spark.sql(f"SELECT * FROM {SOP_PDFS_TABLE} LIMIT 5"))
except Exception as e:
    print(f"WARNING: SOP PDFs table not found: {e}")
    print("Please upload hospital operations policy/procedure PDFs to the table before running this notebook")
    print(f"Expected table: {SOP_PDFS_TABLE}")
    print("\nTo create the table with Volume files:")
    print("""
    CREATE TABLE IF NOT EXISTS {table} AS
    SELECT 
        path,
        content
    FROM read_files('/Volumes/{catalog}/{schema}/hospital_sop_documents/*.pdf', format => 'binaryFile')
    """.format(table=SOP_PDFS_TABLE, catalog=CATALOG, schema=SCHEMA))
    dbutils.notebook.exit("SOP PDFs table not found")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Parse PDFs with ai_parse_document

# COMMAND ----------

# Parse PDFs using ai_parse_document
# This extracts text content from the binary PDF files
spark.sql(f"""
CREATE OR REPLACE TABLE {SOP_PARSED_TABLE} AS
SELECT 
    path as source_path,
    -- Extract filename from path for easier reference
    regexp_extract(path, '[^/]+$', 0) as filename,
    -- Parse the PDF content to text
    ai_parse_document(content, 'text').text as parsed_text,
    -- Get document metadata if available
    ai_parse_document(content, 'text').metadata as doc_metadata,
    current_timestamp() as parsed_at
FROM {SOP_PDFS_TABLE}
WHERE content IS NOT NULL
""")

parsed_count = spark.sql(f"SELECT COUNT(*) FROM {SOP_PARSED_TABLE}").collect()[0][0]
print(f"Parsed {parsed_count} SOP documents")

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

# Wait a moment for index to be ready
import time
time.sleep(10)

# Test search
try:
    index = vsc.get_index(endpoint_name=VECTOR_ENDPOINT, index_name=SOP_VECTOR_INDEX)
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
print(f"Source PDFs: {SOP_PDFS_TABLE}")
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
