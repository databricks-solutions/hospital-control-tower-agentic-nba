# Databricks notebook source
# MAGIC %md
# MAGIC # Generate Medical Logistics Data
# MAGIC
# MAGIC Creates realistic hospital operations data using **dbldatagen** and **faker** for the
# MAGIC Medical Logistics Next Best Action app.
# MAGIC
# MAGIC **Tables generated:**
# MAGIC 1. `dim_encounters` - Patient encounter metadata
# MAGIC 2. `fact_drug_costs` - Drug/pharmacy costs
# MAGIC 3. `fact_staffing` - Staffing and contract labor
# MAGIC 4. `fact_ed_wait_times` - ED wait time events
# MAGIC 5. `fact_operational_kpis` - Daily operational KPIs
# MAGIC 6. `hospital_overview` - Summary VIEW
# MAGIC
# MAGIC **Built-in patterns for the agent to discover:**
# MAGIC - Drug costs spike in November for Hospital A (expensive biologic added)
# MAGIC - Hospital A has higher LOS than others
# MAGIC - Monday discharges have higher LOS (weekend admission backlog)
# MAGIC - ED wait times breach thresholds for low-acuity patients
# MAGIC - Cardiology department has high contract labor percentage

# COMMAND ----------

# MAGIC %pip install dbldatagen faker --quiet
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

import random
from datetime import datetime, timedelta, date
from pyspark.sql import functions as F
from pyspark.sql.types import *
import dbldatagen as dg
from faker import Faker

fake = Faker()
Faker.seed(42)
random.seed(42)

dbutils.widgets.text("var.catalog", "", "Catalog")
dbutils.widgets.text("var.schema", "med_logistics_nba", "Schema")
CATALOG = dbutils.widgets.get("var.catalog")
SCHEMA = dbutils.widgets.get("var.schema")

dbutils.widgets.text("encounter_count", "10000", "Number of Encounters")
dbutils.widgets.text("months_back", "12", "Months of History")
dbutils.widgets.dropdown("write_mode", "overwrite", ["overwrite", "append"], "Write Mode")

ENCOUNTER_COUNT = int(dbutils.widgets.get("encounter_count"))
MONTHS_BACK = int(dbutils.widgets.get("months_back"))
WRITE_MODE = dbutils.widgets.get("write_mode")

print(f"Generating {ENCOUNTER_COUNT} encounters over {MONTHS_BACK} months ({WRITE_MODE} mode)")
print(f"Target: {CATALOG}.{SCHEMA}")

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
spark.sql(f"USE CATALOG {CATALOG}")
spark.sql(f"USE SCHEMA {SCHEMA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Constants

# COMMAND ----------

HOSPITALS = ["Hospital_A", "Hospital_B", "Hospital_C"]
DEPARTMENTS = [
    "Cardiology", "Orthopedics", "General_Medicine", "Neurology",
    "Oncology", "Emergency", "Pediatrics", "Pulmonology"
]
PAYERS = ["Medicare", "Medicaid", "BlueCross", "Aetna", "UnitedHealth", "Self_Pay"]
STAFF_TYPES = ["full_time", "contract", "per_diem"]
ACUITY_LEVELS = [1, 2, 3, 4, 5]  # 1=most urgent, 5=least

DRUG_CATEGORIES = {
    "Antibiotics": ["Amoxicillin", "Vancomycin", "Ceftriaxone", "Azithromycin"],
    "Analgesics": ["Acetaminophen", "Morphine", "Hydrocodone", "Ketorolac"],
    "Cardiovascular": ["Metoprolol", "Lisinopril", "Heparin", "Warfarin"],
    "Biologics": ["Infliximab", "Rituximab", "Adalimumab"],
    "Oncology": ["Pembrolizumab", "Nivolumab", "Carboplatin"],
}

# Base costs per category
DRUG_BASE_COSTS = {
    "Antibiotics": (5, 80),
    "Analgesics": (2, 50),
    "Cardiovascular": (10, 120),
    "Biologics": (500, 5000),
    "Oncology": (200, 3000),
}

END_DATE = date.today()
if WRITE_MODE == "append":
    START_DATE = END_DATE - timedelta(days=1)
    ENCOUNTER_COUNT = min(ENCOUNTER_COUNT, 200)
else:
    START_DATE = END_DATE - timedelta(days=MONTHS_BACK * 30)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Generate dim_encounters
# MAGIC
# MAGIC Key pattern: Hospital A has higher LOS. Monday discharges have higher LOS.

# COMMAND ----------

from pyspark.sql import Row

encounters = []
current_date = START_DATE

id_offset = int(datetime.now().timestamp()) if WRITE_MODE == "append" else 0
for i in range(ENCOUNTER_COUNT):
    encounter_id = f"ENC_{id_offset + i + 1:010d}"
    patient_id = f"PAT_{random.randint(1, ENCOUNTER_COUNT // 3):06d}"
    hospital = random.choices(HOSPITALS, weights=[45, 35, 20])[0]
    department = random.choice(DEPARTMENTS)
    payer = random.choice(PAYERS)
    attending = fake.name()

    # Admit date spread across the date range
    days_offset = random.randint(0, (END_DATE - START_DATE).days)
    admit_date = START_DATE + timedelta(days=days_offset)

    # LOS with built-in patterns
    base_los = random.choices([1, 2, 3, 4, 5, 6, 7, 8, 10, 14], 
                               weights=[15, 20, 20, 15, 10, 8, 5, 3, 2, 2])[0]
    
    # Pattern: Hospital A has higher LOS (+1-2 days)
    if hospital == "Hospital_A":
        base_los += random.choice([1, 1, 2])
    
    # Pattern: Monday discharges have higher LOS (weekend backlog)
    discharge_date = admit_date + timedelta(days=base_los)
    if discharge_date.weekday() == 0:  # Monday
        base_los += random.choice([1, 2, 2, 3])
        discharge_date = admit_date + timedelta(days=base_los)

    los_days = max(1, base_los)
    discharge_date = admit_date + timedelta(days=los_days)
    discharge_dow = discharge_date.strftime("%A")

    # Readmission: ~8% base, higher for Hospital A
    readmit_rate = 0.12 if hospital == "Hospital_A" else 0.06
    is_readmission = random.random() < readmit_rate

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
encounters_df.write.option("mergeSchema", "true").mode(WRITE_MODE).saveAsTable(f"{SCHEMA}.dim_encounters")
print(f"Created dim_encounters: {ENCOUNTER_COUNT} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Generate fact_drug_costs
# MAGIC
# MAGIC Key pattern: Hospital A has a drug cost spike in November (expensive biologic).

# COMMAND ----------

drug_rows = []
enc_df = spark.table(f"{SCHEMA}.dim_encounters").collect()

for enc in enc_df:
    # Each encounter gets 2-8 drug orders
    n_drugs = random.randint(2, 8)
    for _ in range(n_drugs):
        category = random.choice(list(DRUG_CATEGORIES.keys()))
        drug_name = random.choice(DRUG_CATEGORIES[category])
        low, high = DRUG_BASE_COSTS[category]
        unit_cost = round(random.uniform(low, high), 2)
        quantity = random.randint(1, 30)

        # Pattern: Hospital A November spike - add expensive biologics
        admit_month = enc.admit_date.month
        if enc.hospital == "Hospital_A" and admit_month == 11:
            if random.random() < 0.35:
                category = "Biologics"
                drug_name = random.choice(DRUG_CATEGORIES["Biologics"])
                unit_cost = round(random.uniform(2000, 8000), 2)
                quantity = random.randint(1, 5)

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

drug_df = spark.createDataFrame(drug_rows)
drug_df.write.option("mergeSchema", "true").mode(WRITE_MODE).saveAsTable(f"{SCHEMA}.fact_drug_costs")
print(f"Created fact_drug_costs: {len(drug_rows)} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Generate fact_staffing
# MAGIC
# MAGIC Key pattern: Cardiology has high contract labor percentage.

# COMMAND ----------

staffing_rows = []
current = START_DATE

while current <= END_DATE:
    for hospital in HOSPITALS:
        for dept in DEPARTMENTS:
            for staff_type in STAFF_TYPES:
                # Base FTE counts
                if staff_type == "full_time":
                    base_fte = random.uniform(15, 40)
                elif staff_type == "contract":
                    base_fte = random.uniform(2, 8)
                else:  # per_diem
                    base_fte = random.uniform(1, 5)

                # Pattern: Cardiology has high contract labor
                if dept == "Cardiology" and staff_type == "contract":
                    base_fte = random.uniform(12, 25)
                elif dept == "Cardiology" and staff_type == "full_time":
                    base_fte = random.uniform(10, 20)

                fte_count = round(base_fte, 1)
                cost_per_fte = round(random.uniform(300, 800) if staff_type == "full_time"
                                     else random.uniform(600, 1500) if staff_type == "contract"
                                     else random.uniform(400, 900), 2)

                staffing_rows.append(Row(
                    date=datetime.combine(current, datetime.min.time()),
                    hospital=hospital,
                    department=dept,
                    staff_type=staff_type,
                    fte_count=fte_count,
                    cost_per_fte=cost_per_fte,
                    total_cost=round(fte_count * cost_per_fte, 2),
                ))
    # Weekly granularity to keep size manageable
    current += timedelta(days=7)

staffing_df = spark.createDataFrame(staffing_rows)
staffing_df.write.option("mergeSchema", "true").mode(WRITE_MODE).saveAsTable(f"{SCHEMA}.fact_staffing")
print(f"Created fact_staffing: {len(staffing_rows)} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Generate fact_ed_wait_times
# MAGIC
# MAGIC Key pattern: Low-acuity (4-5) patients have wait times above threshold.

# COMMAND ----------

ed_encounters = [e for e in enc_df if e.department == "Emergency"]
# Also generate some standalone ED visits
extra_ed = ENCOUNTER_COUNT // 5

ed_rows = []
for i, enc in enumerate(ed_encounters):
    arrival = enc.admit_date + timedelta(hours=random.randint(0, 23), minutes=random.randint(0, 59))
    acuity = random.choices(ACUITY_LEVELS, weights=[5, 15, 30, 30, 20])[0]

    # Base wait time by acuity
    if acuity <= 2:
        wait_min = max(1.0, random.gauss(15, 8))
    elif acuity == 3:
        wait_min = max(5.0, random.gauss(45, 20))
    else:
        # Pattern: Low acuity has long waits (above 60-min threshold)
        wait_min = max(10.0, random.gauss(90, 35))

    triage_time = arrival + timedelta(minutes=random.randint(2, 15))
    provider_seen = triage_time + timedelta(minutes=int(wait_min))
    disposition_time = provider_seen + timedelta(minutes=random.randint(30, 180))

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

# Extra standalone ED visits
for i in range(extra_ed):
    hospital = random.choice(HOSPITALS)
    days_offset = random.randint(0, (END_DATE - START_DATE).days)
    arrival_date = START_DATE + timedelta(days=days_offset)
    arrival = datetime.combine(arrival_date, datetime.min.time()) + timedelta(
        hours=random.randint(0, 23), minutes=random.randint(0, 59))
    acuity = random.choices(ACUITY_LEVELS, weights=[5, 15, 30, 30, 20])[0]

    if acuity <= 2:
        wait_min = max(1.0, random.gauss(15, 8))
    elif acuity == 3:
        wait_min = max(5.0, random.gauss(45, 20))
    else:
        wait_min = max(10.0, random.gauss(90, 35))

    triage_time = arrival + timedelta(minutes=random.randint(2, 15))
    provider_seen = triage_time + timedelta(minutes=int(wait_min))
    disposition_time = provider_seen + timedelta(minutes=random.randint(30, 180))

    ed_rows.append(Row(
        encounter_id=f"ED_{i+1:06d}",
        hospital=hospital,
        arrival_time=arrival,
        triage_time=triage_time,
        provider_seen_time=provider_seen,
        disposition_time=disposition_time,
        wait_minutes=round(wait_min, 1),
        acuity_level=acuity,
    ))

ed_df = spark.createDataFrame(ed_rows)
ed_df.write.option("mergeSchema", "true").mode(WRITE_MODE).saveAsTable(f"{SCHEMA}.fact_ed_wait_times")
print(f"Created fact_ed_wait_times: {len(ed_rows)} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Generate fact_operational_kpis

# COMMAND ----------

kpi_rows = []
current = START_DATE

while current <= END_DATE:
    for hospital in HOSPITALS:
        for dept in DEPARTMENTS:
            # Base LOS by hospital (pattern: Hospital A higher)
            if hospital == "Hospital_A":
                avg_los = round(random.gauss(5.8, 1.2), 1)
            elif hospital == "Hospital_B":
                avg_los = round(random.gauss(4.2, 0.9), 1)
            else:
                avg_los = round(random.gauss(4.0, 0.8), 1)

            avg_ed_wait = round(random.gauss(55, 20), 1) if dept == "Emergency" else None
            bed_util = round(random.uniform(65, 95), 1)

            # Contract labor % - high for Cardiology
            if dept == "Cardiology":
                contract_pct = round(random.uniform(30, 55), 1)
            else:
                contract_pct = round(random.uniform(5, 20), 1)

            # Drug cost per encounter - spike in Nov for Hospital A
            base_drug_cost = random.uniform(800, 2500)
            if hospital == "Hospital_A" and current.month == 11:
                base_drug_cost *= random.uniform(1.8, 3.0)

            readmit_rate = round(random.uniform(8, 15) if hospital == "Hospital_A"
                                 else random.uniform(4, 9), 1)

            kpi_rows.append(Row(
                date=datetime.combine(current, datetime.min.time()),
                hospital=hospital,
                department=dept,
                avg_los=max(0.5, avg_los),
                avg_ed_wait_minutes=max(5.0, avg_ed_wait) if avg_ed_wait else None,
                bed_utilization_pct=bed_util,
                contract_labor_pct=contract_pct,
                drug_cost_per_encounter=round(base_drug_cost, 2),
                readmission_rate=readmit_rate,
            ))
    current += timedelta(days=1)

kpi_df = spark.createDataFrame(kpi_rows)
kpi_df.write.option("mergeSchema", "true").mode(WRITE_MODE).saveAsTable(f"{SCHEMA}.fact_operational_kpis")
print(f"Created fact_operational_kpis: {len(kpi_rows)} rows")

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
print("Created hospital_overview VIEW")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

tables = [
    "dim_encounters", "fact_drug_costs", "fact_staffing",
    "fact_ed_wait_times", "fact_operational_kpis"
]

print("=" * 60)
print("DATA GENERATION COMPLETE")
print("=" * 60)
for t in tables:
    count = spark.sql(f"SELECT COUNT(*) as cnt FROM {SCHEMA}.{t}").collect()[0][0]
    print(f"  {t}: {count:,} rows")
print(f"  hospital_overview: VIEW")
print("=" * 60)
print()
print("Built-in patterns:")
print("  - Hospital A: higher LOS, higher readmission rate")
print("  - Hospital A November: drug cost spike (biologics)")
print("  - Monday discharges: higher LOS (weekend backlog)")
print("  - Low-acuity ED: wait times above 60-min threshold")
print("  - Cardiology: high contract labor (30-55%)")

# COMMAND ----------

display(spark.table(f"{SCHEMA}.hospital_overview"))
