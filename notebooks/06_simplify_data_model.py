# Databricks notebook source
# MAGIC %md
# MAGIC # Setup Data Model for Hospital Control Tower
# MAGIC
# MAGIC Creates the medical logistics data model tables and hospital_overview VIEW.
# MAGIC
# MAGIC **Tables created:**
# MAGIC - `dim_encounters` - Patient encounter metadata
# MAGIC - `fact_drug_costs` - Drug/pharmacy costs by encounter
# MAGIC - `fact_staffing` - Staffing and contract labor by hospital/department
# MAGIC - `fact_ed_wait_times` - ED wait time events
# MAGIC - `fact_operational_kpis` - Daily operational KPIs
# MAGIC - `hospital_overview` - Summary VIEW

# COMMAND ----------

# Configuration
dbutils.widgets.text("var.catalog", "", "Catalog")
dbutils.widgets.text("var.schema", "med_logistics_nba", "Schema")
CATALOG = dbutils.widgets.get("var.catalog")
SCHEMA = dbutils.widgets.get("var.schema")

print(f"Unity Catalog: {CATALOG}.{SCHEMA}")

# COMMAND ----------

spark.sql(f"USE CATALOG {CATALOG}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
spark.sql(f"USE SCHEMA {SCHEMA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Create dim_encounters

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {SCHEMA}.dim_encounters (
    encounter_id STRING COMMENT 'Unique encounter identifier',
    patient_id STRING COMMENT 'Patient identifier',
    hospital STRING COMMENT 'Hospital/facility',
    department STRING COMMENT 'Department (Cardiology, Emergency, etc.)',
    admit_date TIMESTAMP COMMENT 'Admission date',
    discharge_date TIMESTAMP COMMENT 'Discharge date',
    los_days INT COMMENT 'Length of stay in days',
    discharge_day_of_week STRING COMMENT 'Day of week at discharge',
    payer STRING COMMENT 'Payer (Medicare, Medicaid, etc.)',
    drg_code STRING COMMENT 'DRG code',
    attending_physician STRING COMMENT 'Attending physician',
    is_readmission BOOLEAN COMMENT 'Whether this is a readmission'
)
USING DELTA
COMMENT 'Patient encounter dimension table'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
""")
print(f"Created {SCHEMA}.dim_encounters")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Create fact_drug_costs

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {SCHEMA}.fact_drug_costs (
    encounter_id STRING COMMENT 'Encounter identifier',
    date TIMESTAMP COMMENT 'Date of drug order',
    hospital STRING COMMENT 'Hospital',
    department STRING COMMENT 'Department',
    drug_name STRING COMMENT 'Drug name',
    drug_category STRING COMMENT 'Drug category (Antibiotics, Biologics, etc.)',
    unit_cost DOUBLE COMMENT 'Cost per unit',
    quantity INT COMMENT 'Quantity ordered',
    total_cost DOUBLE COMMENT 'Total cost (unit_cost * quantity)'
)
USING DELTA
COMMENT 'Drug/pharmacy costs by encounter'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
""")
print(f"Created {SCHEMA}.fact_drug_costs")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Create fact_staffing

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {SCHEMA}.fact_staffing (
    date TIMESTAMP COMMENT 'Date',
    hospital STRING COMMENT 'Hospital',
    department STRING COMMENT 'Department',
    staff_type STRING COMMENT 'full_time, contract, or per_diem',
    fte_count DOUBLE COMMENT 'FTE count',
    cost_per_fte DOUBLE COMMENT 'Cost per FTE',
    total_cost DOUBLE COMMENT 'Total staffing cost'
)
USING DELTA
COMMENT 'Staffing and contract labor by hospital/department'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
""")
print(f"Created {SCHEMA}.fact_staffing")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Create fact_ed_wait_times

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {SCHEMA}.fact_ed_wait_times (
    encounter_id STRING COMMENT 'Encounter identifier',
    hospital STRING COMMENT 'Hospital',
    arrival_time TIMESTAMP COMMENT 'Arrival time',
    triage_time TIMESTAMP COMMENT 'Triage completion time',
    provider_seen_time TIMESTAMP COMMENT 'When provider was seen',
    disposition_time TIMESTAMP COMMENT 'Disposition time',
    wait_minutes DOUBLE COMMENT 'Wait time in minutes',
    acuity_level INT COMMENT 'Acuity level (1-5, 1=most urgent)'
)
USING DELTA
COMMENT 'ED wait time events'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
""")
print(f"Created {SCHEMA}.fact_ed_wait_times")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Create fact_operational_kpis

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {SCHEMA}.fact_operational_kpis (
    date TIMESTAMP COMMENT 'Date',
    hospital STRING COMMENT 'Hospital',
    department STRING COMMENT 'Department',
    avg_los DOUBLE COMMENT 'Average length of stay',
    avg_ed_wait_minutes DOUBLE COMMENT 'Average ED wait time (Emergency dept only)',
    bed_utilization_pct DOUBLE COMMENT 'Bed utilization percentage',
    contract_labor_pct DOUBLE COMMENT 'Contract labor percentage',
    drug_cost_per_encounter DOUBLE COMMENT 'Average drug cost per encounter',
    readmission_rate DOUBLE COMMENT 'Readmission rate percentage'
)
USING DELTA
COMMENT 'Daily operational KPIs by hospital and department'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
""")
print(f"Created {SCHEMA}.fact_operational_kpis")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Create hospital_overview VIEW

# COMMAND ----------

spark.sql(f"DROP VIEW IF EXISTS {SCHEMA}.hospital_overview")
spark.sql(f"""
CREATE VIEW {SCHEMA}.hospital_overview AS
SELECT
    e.hospital,
    COUNT(*) as total_encounters,
    ROUND(AVG(e.los_days), 1) as avg_los,
    ROUND(SUM(CASE WHEN e.is_readmission THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as readmission_rate_pct,
    COUNT(DISTINCT e.department) as department_count,
    COUNT(DISTINCT e.attending_physician) as physician_count
FROM {SCHEMA}.dim_encounters e
GROUP BY e.hospital
""")
print(f"Created {SCHEMA}.hospital_overview VIEW")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Verify Tables

# COMMAND ----------

core_tables = [
    f"{SCHEMA}.dim_encounters",
    f"{SCHEMA}.fact_drug_costs",
    f"{SCHEMA}.fact_staffing",
    f"{SCHEMA}.fact_ed_wait_times",
    f"{SCHEMA}.fact_operational_kpis",
]

print("=" * 60)
print("DATA MODEL STATUS")
print("=" * 60)

for table in core_tables:
    exists = spark.catalog.tableExists(table)
    status = "✓ EXISTS" if exists else "✗ MISSING"
    print(f"{status}: {table}")
    
    if exists:
        count = spark.sql(f"SELECT COUNT(*) as cnt FROM {table}").collect()[0][0]
        print(f"  └─ Rows: {count:,}")

view_exists = spark.catalog.tableExists(f"{SCHEMA}.hospital_overview")
print(f"{'✓ EXISTS' if view_exists else '✗ MISSING'}: {SCHEMA}.hospital_overview (VIEW)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

print("=" * 60)
print("DATA MODEL SETUP COMPLETE")
print("=" * 60)
print("")
print("Tables created:")
print("  1. dim_encounters - Patient encounter metadata")
print("  2. fact_drug_costs - Drug/pharmacy costs by encounter")
print("  3. fact_staffing - Staffing and contract labor")
print("  4. fact_ed_wait_times - ED wait time events")
print("  5. fact_operational_kpis - Daily operational KPIs")
print("  6. hospital_overview - VIEW (derived from dim_encounters)")
print("")
print("Next Steps:")
print("  1. Run 00_generate_data.py to populate with sample data")
print("  2. Run 02_setup_vector_search.py to create encounter embeddings")
print("  3. Update agent tools to reference table names")
print("=" * 60)

# COMMAND ----------

# Display final table list
display(spark.sql(f"SHOW TABLES IN {SCHEMA}"))
