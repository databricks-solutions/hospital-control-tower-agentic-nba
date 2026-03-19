# Databricks notebook source
# MAGIC %md
# MAGIC # Add Incremental Encounters
# MAGIC
# MAGIC Adds a small number of additional encounters to existing tables for incremental testing.
# MAGIC Use 00_generate_data.py for full initial data generation.

# COMMAND ----------

# MAGIC %pip install faker --quiet
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

import random
from datetime import datetime, timedelta, date
from pyspark.sql import Row
from faker import Faker

fake = Faker()
Faker.seed(42)
random.seed(42)

# Configuration
dbutils.widgets.text("var.catalog", "", "Catalog")
dbutils.widgets.text("var.schema", "med_logistics_nba", "Schema")
CATALOG = dbutils.widgets.get("var.catalog")
SCHEMA = dbutils.widgets.get("var.schema")

dbutils.widgets.text("encounter_count", "10", "Number of Encounters to Add")
dbutils.widgets.text("readmission_rate", "0.10", "Readmission Rate (0-1)")

try:
    ENCOUNTER_COUNT = int(dbutils.widgets.get("encounter_count"))
except:
    ENCOUNTER_COUNT = 10

try:
    READMISSION_RATE = float(dbutils.widgets.get("readmission_rate"))
except:
    READMISSION_RATE = 0.10

print(f"Adding {ENCOUNTER_COUNT} encounters with {READMISSION_RATE*100}% readmission rate")
print(f"Target: {CATALOG}.{SCHEMA}")

# COMMAND ----------

spark.sql(f"USE CATALOG {CATALOG}")
spark.sql(f"USE SCHEMA {SCHEMA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Get Max Encounter ID (for incremental IDs)

# COMMAND ----------

HOSPITALS = ["Hospital_A", "Hospital_B", "Hospital_C"]
DEPARTMENTS = [
    "Cardiology", "Orthopedics", "General_Medicine", "Neurology",
    "Oncology", "Emergency", "Pediatrics", "Pulmonology"
]
PAYERS = ["Medicare", "Medicaid", "BlueCross", "Aetna", "UnitedHealth", "Self_Pay"]
DRUG_CATEGORIES = {
    "Antibiotics": ["Amoxicillin", "Vancomycin", "Ceftriaxone", "Azithromycin"],
    "Analgesics": ["Acetaminophen", "Morphine", "Hydrocodone", "Ketorolac"],
    "Cardiovascular": ["Metoprolol", "Lisinopril", "Heparin", "Warfarin"],
}
ACUITY_LEVELS = [1, 2, 3, 4, 5]

# Get max encounter ID from existing data
try:
    result = spark.sql(f"SELECT COALESCE(MAX(CAST(REGEXP_REPLACE(encounter_id, '[^0-9]', '') AS BIGINT)), 0) as max_id FROM {SCHEMA}.dim_encounters").collect()[0][0]
    START_ID = int(result) + 1
except:
    START_ID = 1

print(f"Starting encounter IDs from {START_ID}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Generate New Encounters

# COMMAND ----------

encounters = []
base_date = date.today() - timedelta(days=7)

for i in range(ENCOUNTER_COUNT):
    encounter_id = f"ENC_{START_ID + i:06d}"
    patient_id = f"PAT_{random.randint(1, 5000):06d}"
    hospital = random.choice(HOSPITALS)
    department = random.choice(DEPARTMENTS)
    payer = random.choice(PAYERS)
    attending = fake.name()
    
    admit_date = base_date + timedelta(days=random.randint(0, 7))
    los_days = random.choice([1, 2, 3, 4, 5, 6, 7])
    discharge_date = admit_date + timedelta(days=los_days)
    discharge_dow = discharge_date.strftime("%A")
    is_readmission = random.random() < READMISSION_RATE
    drg_code = f"DRG_{random.randint(100, 999)}"
    
    encounters.append(Row(
        encounter_id=encounter_id,
        patient_id=patient_id,
        hospital=hospital,
        department=department,
        admit_date=datetime.combine(admit_date, datetime.min.time()),
        discharge_date=datetime.combine(discharge_date, datetime.min.time()),
        los_days=los_days,
        discharge_day_of_week=discharge_dow,
        payer=payer,
        drg_code=drg_code,
        attending_physician=attending,
        is_readmission=is_readmission,
    ))

encounters_df = spark.createDataFrame(encounters)
encounters_df.write.mode("append").saveAsTable(f"{SCHEMA}.dim_encounters")
print(f"✓ Inserted {ENCOUNTER_COUNT} encounters into dim_encounters")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Add fact_drug_costs for New Encounters

# COMMAND ----------

drug_rows = []
for enc in encounters:
    n_drugs = random.randint(2, 5)
    for _ in range(n_drugs):
        category = random.choice(list(DRUG_CATEGORIES.keys()))
        drug_name = random.choice(DRUG_CATEGORIES[category])
        unit_cost = round(random.uniform(5, 150), 2)
        quantity = random.randint(1, 20)
        drug_date = enc.admit_date + timedelta(days=random.randint(0, max(1, enc.los_days - 1)))
        drug_rows.append(Row(
            encounter_id=enc.encounter_id,
            date=drug_date,
            hospital=enc.hospital,
            department=enc.department,
            drug_name=drug_name,
            drug_category=category,
            unit_cost=unit_cost,
            quantity=quantity,
            total_cost=round(unit_cost * quantity, 2),
        ))

if drug_rows:
    drug_df = spark.createDataFrame(drug_rows)
    drug_df.write.mode("append").saveAsTable(f"{SCHEMA}.fact_drug_costs")
    print(f"✓ Added {len(drug_rows)} drug cost records")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Add fact_ed_wait_times for ED Encounters

# COMMAND ----------

ed_rows = []
for enc in encounters:
    if enc.department == "Emergency":
        arrival = enc.admit_date + timedelta(hours=random.randint(0, 23), minutes=random.randint(0, 59))
        acuity = random.choice(ACUITY_LEVELS)
        wait_min = max(5, random.gauss(45, 25))
        triage_time = arrival + timedelta(minutes=random.randint(2, 15))
        provider_seen = triage_time + timedelta(minutes=int(wait_min))
        disposition_time = provider_seen + timedelta(minutes=random.randint(30, 120))
        ed_rows.append(Row(
            encounter_id=enc.encounter_id,
            hospital=enc.hospital,
            arrival_time=arrival,
            triage_time=triage_time,
            provider_seen_time=provider_seen,
            disposition_time=disposition_time,
            wait_minutes=round(wait_min, 1),
            acuity_level=acuity,
        ))

if ed_rows:
    ed_df = spark.createDataFrame(ed_rows)
    ed_df.write.mode("append").saveAsTable(f"{SCHEMA}.fact_ed_wait_times")
    print(f"✓ Added {len(ed_rows)} ED wait time records")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

print("=" * 60)
print("INCREMENTAL ENCOUNTER GENERATION COMPLETE")
print("=" * 60)
print(f"Added {ENCOUNTER_COUNT} encounters:")
print(f"  - Hospitals: {', '.join(set(e.hospital for e in encounters))}")
print(f"  - Departments: {', '.join(set(e.department for e in encounters))}")
print(f"  - Readmissions: {sum(1 for e in encounters if e.is_readmission)}/{ENCOUNTER_COUNT}")
print("")
print("Tables updated:")
print(f"  ✓ dim_encounters: +{ENCOUNTER_COUNT}")
print(f"  ✓ fact_drug_costs: +{len(drug_rows)}")
print(f"  ✓ fact_ed_wait_times: +{len(ed_rows)}")
print("=" * 60)

# COMMAND ----------

# Display newly added encounters
display(spark.sql(f"""
    SELECT encounter_id, hospital, department, admit_date, los_days, is_readmission
    FROM {SCHEMA}.dim_encounters
    WHERE encounter_id >= 'ENC_{START_ID:06d}'
    ORDER BY admit_date DESC
"""))
