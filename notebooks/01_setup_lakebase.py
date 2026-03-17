# Databricks notebook source
# MAGIC %md
# MAGIC # Setup Tables for Hospital Control Tower
# MAGIC
# MAGIC Creates the analysis_outputs and poetry tables in Unity Catalog.

# COMMAND ----------

# Configuration
dbutils.widgets.text("var.catalog", "", "Catalog")
dbutils.widgets.text("var.schema", "med_logistics_nba", "Schema")
CATALOG = dbutils.widgets.get("var.catalog")
SCHEMA = dbutils.widgets.get("var.schema")

print(f"Unity Catalog: {CATALOG}.{SCHEMA}")

# COMMAND ----------

# Set the catalog
spark.sql(f"USE CATALOG {CATALOG}")
print(f"Using catalog: {CATALOG}")

# Create schema
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
print(f"Schema {CATALOG}.{SCHEMA} created/verified")

# COMMAND ----------

# Create analysis_outputs table
spark.sql(
    f"""
CREATE TABLE IF NOT EXISTS {SCHEMA}.analysis_outputs (
    id STRING COMMENT 'Unique analysis ID (UUID)',
    encounter_id STRING COMMENT 'Related encounter ID if applicable',
    analysis_type STRING COMMENT 'Type: readmission_prediction, root_cause_analysis, cost_optimization, etc.',
    insights STRING COMMENT 'Main analysis findings',
    recommendations STRING COMMENT 'Actionable recommendations',
    created_at TIMESTAMP COMMENT 'When analysis was created',
    agent_mode STRING COMMENT 'quick or deep',
    metadata MAP<STRING, STRING> COMMENT 'Additional metadata',
    priority STRING COMMENT 'critical/high/medium/low',
    status STRING COMMENT 'pending/approved/rejected',
    reviewed_by STRING COMMENT 'Who reviewed',
    reviewed_at TIMESTAMP COMMENT 'When reviewed',
    engineer_notes STRING COMMENT 'Reviewer notes'
)
USING DELTA
COMMENT 'Agent analysis outputs for medical logistics next best action'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
"""
)

print(f"Table {CATALOG}.{SCHEMA}.analysis_outputs created")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

print("=" * 60)
print("SETUP COMPLETE")
print("=" * 60)
print(f"Tables created in {CATALOG}.{SCHEMA}:")
print("  - analysis_outputs: For agent insights and recommendations")
print("")
print("Next: Run 02_setup_vector_search.py to create embeddings")
print("=" * 60)

# COMMAND ----------

# Display created tables
display(spark.sql(f"SHOW TABLES IN {SCHEMA}"))
