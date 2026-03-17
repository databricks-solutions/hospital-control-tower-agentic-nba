# Databricks notebook source
# MAGIC %md
# MAGIC # Setup Data Model for Investment Intelligence Platform
# MAGIC
# MAGIC Creates the investment analytics data model tables and portfolio_overview VIEW.
# MAGIC
# MAGIC **Tables created:**
# MAGIC - `dim_funds` - Fund/manager dimension
# MAGIC - `fact_fund_performance` - Monthly fund returns and NAV
# MAGIC - `fact_portfolio_holdings` - Position-level holdings
# MAGIC - `fact_fund_flows` - Capital calls, distributions, net flows
# MAGIC - `fact_portfolio_kpis` - Daily portfolio-level KPIs
# MAGIC - `portfolio_overview` - Summary VIEW

# COMMAND ----------

# Configuration
dbutils.widgets.text("var.catalog", "", "Catalog")
dbutils.widgets.text("var.schema", "investment_intel", "Schema")
CATALOG = dbutils.widgets.get("var.catalog")
SCHEMA = dbutils.widgets.get("var.schema")

print(f"Unity Catalog: {CATALOG}.{SCHEMA}")

# COMMAND ----------

spark.sql(f"USE CATALOG {CATALOG}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
spark.sql(f"USE SCHEMA {SCHEMA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Create dim_funds

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {SCHEMA}.dim_funds (
    fund_id STRING COMMENT 'Unique fund identifier',
    fund_name STRING COMMENT 'Fund display name',
    manager_name STRING COMMENT 'Portfolio manager / GP name',
    strategy STRING COMMENT 'Investment strategy (Public Equity, Private Credit, Venture, etc.)',
    vintage_year INT COMMENT 'Fund vintage year',
    aum DOUBLE COMMENT 'Assets under management (USD millions)',
    commitment DOUBLE COMMENT 'Total commitment (USD millions)',
    status STRING COMMENT 'Fund status: active, prospect, watchlist',
    domicile STRING COMMENT 'Fund domicile / jurisdiction',
    inception_date TIMESTAMP COMMENT 'Fund inception date'
)
USING DELTA
COMMENT 'Fund and manager dimension table'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
""")
print(f"Created {SCHEMA}.dim_funds")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Create fact_fund_performance

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {SCHEMA}.fact_fund_performance (
    fund_id STRING COMMENT 'Fund identifier',
    date TIMESTAMP COMMENT 'Reporting date',
    nav DOUBLE COMMENT 'Net asset value (USD millions)',
    monthly_return DOUBLE COMMENT 'Monthly return (decimal, e.g. 0.02 = 2%)',
    ytd_return DOUBLE COMMENT 'Year-to-date return (decimal)',
    itd_return DOUBLE COMMENT 'Inception-to-date return (decimal)',
    benchmark_return DOUBLE COMMENT 'Benchmark monthly return (decimal)',
    alpha DOUBLE COMMENT 'Excess return vs benchmark (decimal)'
)
USING DELTA
COMMENT 'Monthly fund performance and returns'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
""")
print(f"Created {SCHEMA}.fact_fund_performance")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Create fact_portfolio_holdings

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {SCHEMA}.fact_portfolio_holdings (
    fund_id STRING COMMENT 'Fund identifier',
    date TIMESTAMP COMMENT 'Reporting date',
    position_name STRING COMMENT 'Position / company name',
    sector STRING COMMENT 'Sector (Healthcare, Technology, Energy, etc.)',
    geography STRING COMMENT 'Geography (North America, Europe, Asia, etc.)',
    pct_nav DOUBLE COMMENT 'Position as percentage of fund NAV',
    market_value DOUBLE COMMENT 'Position market value (USD millions)',
    change_from_prior DOUBLE COMMENT 'Change from prior period (decimal)'
)
USING DELTA
COMMENT 'Position-level portfolio holdings'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
""")
print(f"Created {SCHEMA}.fact_portfolio_holdings")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Create fact_fund_flows

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {SCHEMA}.fact_fund_flows (
    fund_id STRING COMMENT 'Fund identifier',
    date TIMESTAMP COMMENT 'Flow date',
    capital_calls DOUBLE COMMENT 'Capital called (USD millions)',
    distributions DOUBLE COMMENT 'Capital distributed (USD millions)',
    net_flow DOUBLE COMMENT 'Net flow (distributions - calls, USD millions)',
    commitment_remaining DOUBLE COMMENT 'Unfunded commitment remaining (USD millions)',
    liquidity_terms STRING COMMENT 'Liquidity terms (Monthly, Quarterly, Annual, Locked)'
)
USING DELTA
COMMENT 'Fund capital calls, distributions, and flows'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
""")
print(f"Created {SCHEMA}.fact_fund_flows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Create fact_portfolio_kpis

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {SCHEMA}.fact_portfolio_kpis (
    date TIMESTAMP COMMENT 'Date',
    portfolio_segment STRING COMMENT 'Strategy segment',
    total_aum DOUBLE COMMENT 'Total AUM for segment (USD millions)',
    weighted_avg_return DOUBLE COMMENT 'AUM-weighted average return (decimal)',
    concentration_top5_pct DOUBLE COMMENT 'Top-5 fund concentration percentage',
    benchmark_spread DOUBLE COMMENT 'Spread over benchmark (decimal)',
    manager_count INT COMMENT 'Number of active managers in segment'
)
USING DELTA
COMMENT 'Daily portfolio-level KPIs by strategy segment'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
""")
print(f"Created {SCHEMA}.fact_portfolio_kpis")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Create portfolio_overview VIEW

# COMMAND ----------

spark.sql(f"DROP VIEW IF EXISTS {SCHEMA}.portfolio_overview")
spark.sql(f"""
CREATE VIEW {SCHEMA}.portfolio_overview AS
SELECT
    f.strategy,
    COUNT(*) as fund_count,
    ROUND(SUM(f.aum), 1) as total_aum,
    ROUND(AVG(f.aum), 1) as avg_aum,
    COUNT(DISTINCT f.manager_name) as manager_count,
    SUM(CASE WHEN f.status = 'watchlist' THEN 1 ELSE 0 END) as watchlist_count
FROM {SCHEMA}.dim_funds f
GROUP BY f.strategy
""")
print(f"Created {SCHEMA}.portfolio_overview VIEW")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Verify Tables

# COMMAND ----------

core_tables = [
    f"{SCHEMA}.dim_funds",
    f"{SCHEMA}.fact_fund_performance",
    f"{SCHEMA}.fact_portfolio_holdings",
    f"{SCHEMA}.fact_fund_flows",
    f"{SCHEMA}.fact_portfolio_kpis",
]

print("=" * 60)
print("DATA MODEL STATUS")
print("=" * 60)

for table in core_tables:
    exists = spark.catalog.tableExists(table)
    status = "EXISTS" if exists else "MISSING"
    print(f"{status}: {table}")
    
    if exists:
        count = spark.sql(f"SELECT COUNT(*) as cnt FROM {table}").collect()[0][0]
        print(f"  Rows: {count:,}")

view_exists = spark.catalog.tableExists(f"{SCHEMA}.portfolio_overview")
print(f"{'EXISTS' if view_exists else 'MISSING'}: {SCHEMA}.portfolio_overview (VIEW)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

print("=" * 60)
print("DATA MODEL SETUP COMPLETE")
print("=" * 60)
print("")
print("Tables created:")
print("  1. dim_funds - Fund/manager dimension")
print("  2. fact_fund_performance - Monthly returns and NAV")
print("  3. fact_portfolio_holdings - Position-level holdings")
print("  4. fact_fund_flows - Capital calls and distributions")
print("  5. fact_portfolio_kpis - Portfolio-level KPIs")
print("  6. portfolio_overview - VIEW (derived from dim_funds)")
print("")
print("Next Steps:")
print("  1. Run 00_generate_data.py to populate with sample data")
print("  2. Run 02_setup_vector_search.py to create fund document embeddings")
print("  3. Update agent tools to reference table names")
print("=" * 60)

# COMMAND ----------

display(spark.sql(f"SHOW TABLES IN {SCHEMA}"))
