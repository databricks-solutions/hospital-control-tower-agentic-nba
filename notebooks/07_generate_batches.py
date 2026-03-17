# Databricks notebook source
# MAGIC %md
# MAGIC # Add Incremental Fund Data
# MAGIC
# MAGIC Adds a small number of additional funds and performance data to existing tables for incremental testing.
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
dbutils.widgets.text("var.schema", "investment_intel", "Schema")
CATALOG = dbutils.widgets.get("var.catalog")
SCHEMA = dbutils.widgets.get("var.schema")

dbutils.widgets.text("fund_count", "10", "Number of Funds to Add")
dbutils.widgets.text("months_of_performance", "12", "Months of Performance per Fund")

try:
    FUND_COUNT = int(dbutils.widgets.get("fund_count"))
except:
    FUND_COUNT = 10

try:
    MONTHS_OF_PERFORMANCE = int(dbutils.widgets.get("months_of_performance"))
except:
    MONTHS_OF_PERFORMANCE = 12

print(f"Adding {FUND_COUNT} funds with {MONTHS_OF_PERFORMANCE} months of performance each")
print(f"Target: {CATALOG}.{SCHEMA}")

# COMMAND ----------

spark.sql(f"USE CATALOG {CATALOG}")
spark.sql(f"USE SCHEMA {SCHEMA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Get Max Fund ID (for incremental IDs)

# COMMAND ----------

STRATEGIES = ["Public Equity", "Private Credit", "Venture Capital", "Real Assets", "Hedge Fund"]
SECTORS = ["Healthcare", "Technology", "Energy", "Financial Services", "Industrials"]
DOMICILES = ["Cayman", "Delaware", "Luxembourg", "Ireland", "Bermuda"]

# Get max fund ID from existing data
try:
    result = spark.sql(f"SELECT COALESCE(MAX(CAST(REGEXP_REPLACE(fund_id, '[^0-9]', '') AS BIGINT)), 0) as max_id FROM {SCHEMA}.dim_funds").collect()[0][0]
    START_ID = int(result) + 1
except:
    START_ID = 1

print(f"Starting fund IDs from {START_ID}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Generate New Funds

# COMMAND ----------

funds = []
base_date = date.today() - timedelta(days=30 * MONTHS_OF_PERFORMANCE)

for i in range(FUND_COUNT):
    fund_id = f"FUND_{START_ID + i:06d}"
    strategy = random.choice(STRATEGIES)
    sector = random.choice(SECTORS)
    domicile = random.choice(DOMICILES)
    manager = fake.company()
    inception_date = base_date - timedelta(days=random.randint(365, 3650))
    
    funds.append(Row(
        fund_id=fund_id,
        fund_name=f"{strategy.replace(' ', '_')}_{fund_id}",
        strategy=strategy,
        sector=sector,
        domicile=domicile,
        manager=manager,
        inception_date=datetime.combine(inception_date, datetime.min.time()),
    ))

funds_df = spark.createDataFrame(funds)
funds_df.write.mode("append").saveAsTable(f"{SCHEMA}.dim_funds")
print(f"✓ Inserted {FUND_COUNT} funds into dim_funds")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Add fact_fund_performance for New Funds

# COMMAND ----------

performance_rows = []
for fund in funds:
    nav = round(random.uniform(50_000_000, 2_000_000_000), 2)
    
    for m in range(MONTHS_OF_PERFORMANCE):
        as_of_date = base_date + timedelta(days=30 * m)
        monthly_return = round(random.gauss(0.01, 0.02), 4)
        benchmark_return = round(random.uniform(-0.02, 0.03), 4)
        alpha = round(monthly_return - benchmark_return, 4)
        nav = nav * (1 + monthly_return)
        
        performance_rows.append(Row(
            fund_id=fund.fund_id,
            as_of_date=datetime.combine(as_of_date, datetime.min.time()),
            monthly_return=monthly_return,
            nav=round(nav, 2),
            alpha=alpha,
            benchmark_return=benchmark_return,
        ))

if performance_rows:
    perf_df = spark.createDataFrame(performance_rows)
    perf_df.write.mode("append").saveAsTable(f"{SCHEMA}.fact_fund_performance")
    print(f"✓ Added {len(performance_rows)} fund performance records")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Add fact_portfolio_holdings for New Funds

# COMMAND ----------

holding_rows = []
for fund in funds:
    n_holdings = random.randint(5, 15)
    for h in range(n_holdings):
        ticker = f"TKR{random.randint(100, 999)}"
        weight = round(random.uniform(0.01, 0.15), 4)
        market_value = round(random.uniform(1_000_000, 50_000_000), 2)
        holding_rows.append(Row(
            fund_id=fund.fund_id,
            as_of_date=datetime.combine(base_date + timedelta(days=30 * (MONTHS_OF_PERFORMANCE - 1)), datetime.min.time()),
            ticker=ticker,
            sector=fund.sector,
            weight=weight,
            market_value=market_value,
        ))

if holding_rows:
    holdings_df = spark.createDataFrame(holding_rows)
    holdings_df.write.mode("append").saveAsTable(f"{SCHEMA}.fact_portfolio_holdings")
    print(f"✓ Added {len(holding_rows)} portfolio holding records")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Add fact_fund_flows for New Funds

# COMMAND ----------

flow_rows = []
for fund in funds:
    for m in range(MONTHS_OF_PERFORMANCE):
        as_of_date = base_date + timedelta(days=30 * m)
        subscriptions = round(random.uniform(-5_000_000, 20_000_000), 2)
        redemptions = round(random.uniform(-10_000_000, 5_000_000), 2)
        net_flow = subscriptions + redemptions
        flow_rows.append(Row(
            fund_id=fund.fund_id,
            as_of_date=datetime.combine(as_of_date, datetime.min.time()),
            subscriptions=subscriptions,
            redemptions=redemptions,
            net_flow=net_flow,
        ))

if flow_rows:
    flow_df = spark.createDataFrame(flow_rows)
    flow_df.write.mode("append").saveAsTable(f"{SCHEMA}.fact_fund_flows")
    print(f"✓ Added {len(flow_rows)} fund flow records")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

print("=" * 60)
print("INCREMENTAL FUND GENERATION COMPLETE")
print("=" * 60)
print(f"Added {FUND_COUNT} funds:")
print(f"  - Strategies: {', '.join(set(f.strategy for f in funds))}")
print(f"  - Sectors: {', '.join(set(f.sector for f in funds))}")
print(f"  - Domiciles: {', '.join(set(f.domicile for f in funds))}")
print("")
print("Tables updated:")
print(f"  ✓ dim_funds: +{FUND_COUNT}")
print(f"  ✓ fact_fund_performance: +{len(performance_rows)}")
print(f"  ✓ fact_portfolio_holdings: +{len(holding_rows)}")
print(f"  ✓ fact_fund_flows: +{len(flow_rows)}")
print("=" * 60)

# COMMAND ----------

# Display newly added funds
display(spark.sql(f"""
    SELECT fund_id, fund_name, strategy, sector, domicile, manager
    FROM {SCHEMA}.dim_funds
    WHERE fund_id >= 'FUND_{START_ID:06d}'
    ORDER BY fund_id
"""))
