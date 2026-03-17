# Databricks notebook source
# MAGIC %md
# MAGIC # Generate Investment Intelligence Data
# MAGIC
# MAGIC Creates realistic fund/portfolio data using **dbldatagen** and **faker** for the
# MAGIC Investment Intelligence Platform app.
# MAGIC
# MAGIC **Tables generated:**
# MAGIC 1. `dim_funds` - Fund/manager dimension
# MAGIC 2. `fact_fund_performance` - Monthly returns and NAV
# MAGIC 3. `fact_portfolio_holdings` - Position-level holdings
# MAGIC 4. `fact_fund_flows` - Capital calls and distributions
# MAGIC 5. `fact_portfolio_kpis` - Portfolio-level KPIs
# MAGIC 6. `portfolio_overview` - Summary VIEW
# MAGIC
# MAGIC **Built-in patterns for the agent to discover:**
# MAGIC - MedVenture Alpha (VC): declining returns, watchlisted
# MAGIC - Asclepius Capital (PE Buyout): consistent top-performer
# MAGIC - BioGrowth Partners (Growth Equity): dangerous position concentration
# MAGIC - Genomics Partners / NovaBio (VC): J-curve returns
# MAGIC - PulsePoint Capital (Hedge Fund): style drift, volatility spike
# MAGIC - Q4 capital call spike across portfolio
# MAGIC - Growth Equity: top-5 concentration approaching IPS 30% limit

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
dbutils.widgets.text("var.schema", "investment_intel", "Schema")
CATALOG = dbutils.widgets.get("var.catalog")
SCHEMA = dbutils.widgets.get("var.schema")

dbutils.widgets.text("fund_count", "35", "Number of Funds")
dbutils.widgets.text("months_back", "36", "Months of History")
dbutils.widgets.dropdown("write_mode", "overwrite", ["overwrite", "append"], "Write Mode")

FUND_COUNT = int(dbutils.widgets.get("fund_count"))
MONTHS_BACK = int(dbutils.widgets.get("months_back"))
WRITE_MODE = dbutils.widgets.get("write_mode")

print(f"Generating {FUND_COUNT} funds over {MONTHS_BACK} months ({WRITE_MODE} mode)")
print(f"Target: {CATALOG}.{SCHEMA}")

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
spark.sql(f"USE CATALOG {CATALOG}")
spark.sql(f"USE SCHEMA {SCHEMA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Constants

# COMMAND ----------

# IPS-aligned strategies (Section 3.1)
STRATEGIES = ["PE Buyout", "Venture Capital", "Growth Equity", "Hedge Fund L/S", "Credit & Royalties", "Real Assets"]
# Weights for random assignment — matches IPS target allocation roughly
STRATEGY_WEIGHTS = [28, 18, 12, 15, 12, 8]

STATUSES = ["active", "prospect", "watchlist"]
DOMICILES = ["Delaware", "Cayman Islands", "Luxembourg", "Ireland", "United Kingdom"]

# Healthcare sub-sectors (IPS Section 3.5)
SECTORS = ["Biopharma", "Medical Devices", "Healthcare Services", "Digital Health", "Healthcare RE & Labs", "Diagnostics & Tools"]
SECTOR_WEIGHTS = [30, 20, 18, 15, 10, 7]

# Geography per IPS Section 3.4 (NA 60%, Europe 20%, APAC 12%, RoW 5%)
GEOGRAPHIES = ["North America", "Europe", "Asia-Pacific", "Emerging Markets"]
GEO_WEIGHTS = [60, 20, 12, 8]

LIQUIDITY_TERMS = ["Monthly", "Quarterly", "Annual", "Semi-Annual", "Locked"]

# Named GPs -- each has a story arc the agent can discover
MANAGER_PROFILES = {
    "MedVenture Alpha":       {"strategy": "Venture Capital",     "aum_range": (180, 280), "story": "declining_returns"},
    "Asclepius Capital":      {"strategy": "PE Buyout",           "aum_range": (250, 400), "story": "top_performer"},
    "BioGrowth Partners":     {"strategy": "Growth Equity",       "aum_range": (120, 220), "story": "concentration_risk"},
    "HealthBridge Investments":{"strategy": "Credit & Royalties", "aum_range": (100, 180), "story": "steady"},
    "Pharma Equity Group":    {"strategy": "Hedge Fund L/S",      "aum_range": (150, 300), "story": "volatile"},
    "LifeScience Capital":    {"strategy": "PE Buyout",           "aum_range": (200, 350), "story": "steady"},
    "WellSpring Advisors":    {"strategy": "Real Assets",         "aum_range": (80, 160),  "story": "steady"},
    "MedTech Growth Fund":    {"strategy": "Growth Equity",       "aum_range": (100, 200), "story": "recent_surge"},
    "CarePoint Capital":      {"strategy": "Credit & Royalties",  "aum_range": (60, 140),  "story": "steady"},
    "Genomics Partners":      {"strategy": "Venture Capital",     "aum_range": (60, 150),  "story": "j_curve"},
    "HealthFirst Capital":    {"strategy": "PE Buyout",           "aum_range": (150, 300), "story": "steady"},
    "NovaBio Investments":    {"strategy": "Venture Capital",     "aum_range": (40, 120),  "story": "j_curve"},
    "PulsePoint Capital":     {"strategy": "Hedge Fund L/S",      "aum_range": (100, 200), "story": "style_drift"},
    "MedAlliance Partners":   {"strategy": "PE Buyout",           "aum_range": (200, 380), "story": "nearing_exit"},
    "VitalSign Advisors":     {"strategy": "Growth Equity",       "aum_range": (80, 180),  "story": "steady"},
    "CurePoint Capital":      {"strategy": "Credit & Royalties",  "aum_range": (70, 150),  "story": "steady"},
    "BioFrontier Partners":   {"strategy": "Venture Capital",     "aum_range": (30, 100),  "story": "early_stage"},
    "HealthAxis Capital":     {"strategy": "Hedge Fund L/S",      "aum_range": (80, 160),  "story": "steady"},
    "MedLedger Advisors":     {"strategy": "Real Assets",         "aum_range": (60, 130),  "story": "steady"},
    "SynapsePoint Capital":   {"strategy": "Growth Equity",       "aum_range": (50, 140),  "story": "prospect_new"},
}

COMPANY_NAMES = [
    "Moderna Inc", "Illumina Corp", "Intuitive Surgical", "Edwards Lifesciences", "Danaher Corp",
    "Thermo Fisher Scientific", "Abbott Laboratories", "Medtronic PLC", "UnitedHealth Group",
    "Humana Inc", "Centene Corp", "Molina Healthcare", "HCA Healthcare", "Tenet Healthcare",
    "Vertex Pharmaceuticals", "Regeneron Pharma", "BioMarin Pharma", "Alnylam Pharma",
    "Exact Sciences", "Guardant Health", "Pacific Biosciences", "10x Genomics",
    "Veeva Systems", "Doximity Inc", "Phreesia Inc", "Health Catalyst", "Schrodinger Inc",
    "Recursion Pharma", "AbCellera Biologics", "Certara Inc", "Quanterix Corp",
    "Butterfly Network", "Nuvation Bio", "Sana Biotechnology", "Ginkgo Bioworks",
]

END_DATE = date.today()
if WRITE_MODE == "append":
    START_DATE = END_DATE - timedelta(days=30)
    FUND_COUNT = min(FUND_COUNT, 10)
else:
    START_DATE = END_DATE - timedelta(days=MONTHS_BACK * 30)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Generate dim_funds
# MAGIC
# MAGIC Each manager has a named profile with story arc, strategy, and AUM range.

# COMMAND ----------

from pyspark.sql import Row

funds = []
manager_names = list(MANAGER_PROFILES.keys())
id_offset = int(datetime.now().timestamp()) if WRITE_MODE == "append" else 0

for i in range(FUND_COUNT):
    fund_id = f"FUND_{id_offset + i + 1:06d}"

    # First pass through named managers, then fill with random picks
    if i < len(manager_names):
        manager = manager_names[i]
    else:
        manager = random.choice(manager_names)

    profile = MANAGER_PROFILES[manager]
    strategy = profile["strategy"]
    story = profile["story"]
    lo, hi = profile["aum_range"]
    aum = float(round(random.uniform(lo, hi), 1))

    # Vintage year — older for PE/VC (longer fund life), newer for hedge funds
    if strategy in ("PE Buyout", "Venture Capital"):
        vintage = random.randint(2017, 2024)
    elif strategy == "Growth Equity":
        vintage = random.randint(2019, 2025)
    else:
        vintage = random.randint(2020, 2025)

    # Commitment = AUM * overcommitment factor (PE/VC have larger unfunded)
    if strategy in ("PE Buyout", "Venture Capital", "Growth Equity"):
        commitment = float(round(aum * random.uniform(1.2, 1.6), 1))
    else:
        commitment = float(round(aum * random.uniform(1.0, 1.15), 1))

    # Status based on story arc
    if story == "declining_returns":
        status = "watchlist"
    elif story == "prospect_new":
        status = "prospect"
    elif story == "style_drift":
        status = random.choice(["watchlist", "active"])
    elif story == "early_stage":
        status = random.choice(["active", "prospect"])
    else:
        status = random.choices(["active", "prospect", "watchlist"], weights=[75, 15, 10])[0]

    # Domicile weighted by geography
    if strategy in ("Hedge Fund L/S",):
        domicile = random.choices(["Cayman Islands", "Delaware"], weights=[60, 40])[0]
    elif strategy == "Real Assets":
        domicile = random.choices(["Delaware", "Luxembourg"], weights=[70, 30])[0]
    else:
        domicile = random.choices(DOMICILES, weights=[40, 25, 15, 10, 10])[0]

    inception_days = random.randint(365, max(366, MONTHS_BACK * 30))
    inception_date = END_DATE - timedelta(days=inception_days)

    fund_num = random.choice(["I", "II", "III", "IV", "V", "VI"])
    fund_name = f"{manager} Fund {fund_num}"

    funds.append(Row(
        fund_id=fund_id, fund_name=fund_name, manager_name=manager,
        strategy=strategy, vintage_year=vintage, aum=aum, commitment=commitment,
        status=status, domicile=domicile,
        inception_date=datetime.combine(inception_date, datetime.min.time()),
    ))

funds_df = spark.createDataFrame(funds)
funds_df.write.option("mergeSchema", "true").mode(WRITE_MODE).saveAsTable(f"{SCHEMA}.dim_funds")
print(f"Created dim_funds: {FUND_COUNT} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Generate fact_fund_performance
# MAGIC
# MAGIC Story-arc-aware returns: J-curve for early VC, declining for watchlist funds,
# MAGIC style drift for PulsePoint, exit markups for MedAlliance, etc.

# COMMAND ----------

perf_rows = []
fund_df = spark.table(f"{SCHEMA}.dim_funds").collect()

# Lookup story arc for each manager
story_lookup = {m: p["story"] for m, p in MANAGER_PROFILES.items()}

for fund in fund_df:
    current = START_DATE.replace(day=1)
    cumulative_return = 0.0
    ytd_return = 0.0
    story = story_lookup.get(fund.manager_name, "steady")
    total_months = (END_DATE.year - START_DATE.year) * 12 + (END_DATE.month - START_DATE.month)

    while current <= END_DATE:
        months_ago = (END_DATE.year - current.year) * 12 + (END_DATE.month - current.month)
        month_idx = total_months - months_ago

        # Base return by strategy
        if fund.strategy == "PE Buyout":
            monthly_ret = random.gauss(0.012, 0.02)     # ~15% annual, moderate vol
        elif fund.strategy == "Venture Capital":
            monthly_ret = random.gauss(0.014, 0.05)      # ~18% annual, high vol
        elif fund.strategy == "Growth Equity":
            monthly_ret = random.gauss(0.011, 0.03)      # ~14% annual
        elif fund.strategy == "Hedge Fund L/S":
            monthly_ret = random.gauss(0.006, 0.025)     # ~7% annual, lower vol
        elif fund.strategy == "Credit & Royalties":
            monthly_ret = random.gauss(0.007, 0.012)     # ~9% annual, low vol
        else:  # Real Assets
            monthly_ret = random.gauss(0.005, 0.015)     # ~6% annual, low vol

        # Story-arc overlays
        if story == "declining_returns" and months_ago < 6:
            monthly_ret -= random.uniform(0.015, 0.035)  # significant underperformance
        elif story == "j_curve" and month_idx < total_months * 0.4:
            monthly_ret = random.gauss(-0.005, 0.02)     # negative early, then recovery
        elif story == "top_performer":
            monthly_ret += random.uniform(0.002, 0.008)  # consistent outperformance
        elif story == "concentration_risk":
            monthly_ret *= random.choice([0.7, 1.0, 1.0, 1.5])  # lumpy returns
        elif story == "volatile":
            monthly_ret = random.gauss(monthly_ret, 0.04)  # extra vol
        elif story == "recent_surge" and months_ago < 4:
            monthly_ret += random.uniform(0.01, 0.025)   # strong recent run
        elif story == "nearing_exit" and months_ago < 8:
            monthly_ret += random.uniform(0.005, 0.015)  # exit markups
        elif story == "early_stage":
            monthly_ret = random.gauss(-0.002, 0.03)     # pre-revenue, mostly flat/negative
        elif story == "style_drift":
            # Drift: was low-vol hedge fund, recently acting like high-vol equity
            if months_ago < 6:
                monthly_ret = random.gauss(0.008, 0.05)  # much higher vol than expected

        # Benchmark: Cambridge HC PE composite proxy
        benchmark_ret = random.gauss(0.007, 0.02)

        cumulative_return += monthly_ret
        if current.month == 1:
            ytd_return = monthly_ret
        else:
            ytd_return += monthly_ret

        nav = fund.aum * (1 + cumulative_return)

        perf_rows.append(Row(
            fund_id=fund.fund_id,
            date=datetime.combine(current, datetime.min.time()),
            nav=round(nav, 2),
            monthly_return=round(monthly_ret, 6),
            ytd_return=round(ytd_return, 6),
            itd_return=round(cumulative_return, 6),
            benchmark_return=round(benchmark_ret, 6),
            alpha=round(monthly_ret - benchmark_ret, 6),
        ))

        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

perf_df = spark.createDataFrame(perf_rows)
perf_df.write.option("mergeSchema", "true").mode(WRITE_MODE).saveAsTable(f"{SCHEMA}.fact_fund_performance")
print(f"Created fact_fund_performance: {len(perf_rows)} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Generate fact_portfolio_holdings
# MAGIC
# MAGIC BioGrowth Partners has dangerously high top-position concentration.

# COMMAND ----------

holdings_rows = []

for fund in fund_df:
    n_positions = random.randint(8, 25)
    positions = random.sample(COMPANY_NAMES, min(n_positions, len(COMPANY_NAMES)))

    # Generate quarterly snapshots
    current = START_DATE.replace(day=1)
    while current <= END_DATE:
        if current.month not in (3, 6, 9, 12):
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
            continue

        remaining_pct = 100.0
        fund_story = story_lookup.get(fund.manager_name, "steady")
        for j, pos in enumerate(positions):
            # Pattern: BioGrowth Partners has dangerously high top-position concentration
            if fund_story == "concentration_risk" and j < 3:
                pct = round(random.uniform(12, 22), 2)
            elif fund.strategy in ("PE Buyout", "Growth Equity") and j < 3:
                pct = round(random.uniform(8, 16), 2)
            else:
                max_pct = min(remaining_pct / max(1, len(positions) - j), 12)
                pct = round(random.uniform(1, max(1.5, max_pct)), 2)

            remaining_pct -= pct
            if remaining_pct < 0:
                pct += remaining_pct
                remaining_pct = 0.0

            mv = round(fund.aum * pct / 100, 2)
            change = round(random.gauss(0, 0.05), 4)

            holdings_rows.append(Row(
                fund_id=fund.fund_id,
                date=datetime.combine(current, datetime.min.time()),
                position_name=pos,
                sector=random.choices(SECTORS, weights=SECTOR_WEIGHTS)[0],
                geography=random.choices(GEOGRAPHIES, weights=GEO_WEIGHTS)[0],
                pct_nav=pct,
                market_value=mv,
                change_from_prior=change,
            ))

        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

holdings_df = spark.createDataFrame(holdings_rows)
holdings_df.write.option("mergeSchema", "true").mode(WRITE_MODE).saveAsTable(f"{SCHEMA}.fact_portfolio_holdings")
print(f"Created fact_portfolio_holdings: {len(holdings_rows)} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Generate fact_fund_flows
# MAGIC
# MAGIC Key pattern: Q4 capital call spike across portfolio.

# COMMAND ----------

flow_rows = []

for fund in fund_df:
    current = START_DATE.replace(day=1)
    commitment_remaining = fund.commitment - fund.aum

    while current <= END_DATE:
        # Base flows
        base_call = round(random.uniform(0, fund.commitment * 0.02), 2)
        base_dist = round(random.uniform(0, fund.aum * 0.01), 2)

        # Pattern: Q4 capital call spike
        if current.month in (10, 11, 12):
            base_call *= random.uniform(1.5, 3.0)

        capital_calls = round(base_call, 2)
        distributions = round(base_dist, 2)
        net_flow = round(distributions - capital_calls, 2)
        commitment_remaining = max(0.0, commitment_remaining - capital_calls)

        # Liquidity terms by strategy (IPS-aligned)
        if fund.strategy == "Venture Capital":
            liquidity = "Locked"
        elif fund.strategy in ("PE Buyout", "Growth Equity"):
            liquidity = random.choice(["Annual", "Locked"])
        elif fund.strategy == "Hedge Fund L/S":
            liquidity = random.choice(["Monthly", "Quarterly"])
        elif fund.strategy == "Credit & Royalties":
            liquidity = random.choice(["Quarterly", "Semi-Annual"])
        else:
            liquidity = random.choice(["Quarterly", "Annual"])

        flow_rows.append(Row(
            fund_id=fund.fund_id,
            date=datetime.combine(current, datetime.min.time()),
            capital_calls=capital_calls, distributions=distributions,
            net_flow=net_flow, commitment_remaining=round(commitment_remaining, 2),
            liquidity_terms=liquidity,
        ))

        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

flow_df = spark.createDataFrame(flow_rows)
flow_df.write.option("mergeSchema", "true").mode(WRITE_MODE).saveAsTable(f"{SCHEMA}.fact_fund_flows")
print(f"Created fact_fund_flows: {len(flow_rows)} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Generate fact_portfolio_kpis

# COMMAND ----------

kpi_rows = []
current = START_DATE

while current <= END_DATE:
    for strategy in STRATEGIES:
        strategy_funds = [f for f in fund_df if f.strategy == strategy]
        if not strategy_funds:
            continue

        total_aum = sum(f.aum for f in strategy_funds)

        # Weighted avg return by strategy (IPS-aligned)
        ret_params = {
            "PE Buyout":         (0.012, 0.018),
            "Venture Capital":   (0.014, 0.04),
            "Growth Equity":     (0.011, 0.025),
            "Hedge Fund L/S":    (0.006, 0.02),
            "Credit & Royalties":(0.007, 0.01),
            "Real Assets":       (0.005, 0.012),
        }
        mu, sigma = ret_params.get(strategy, (0.006, 0.02))
        wav_ret = round(random.gauss(mu, sigma), 6)

        # Pattern: Growth Equity top-5 concentration creeping above IPS 30% limit
        if strategy == "Growth Equity":
            conc = round(random.uniform(28, 45), 1)
        elif strategy == "PE Buyout":
            conc = round(random.uniform(22, 38), 1)
        else:
            conc = round(random.uniform(12, 30), 1)

        bench_spread = round(wav_ret - random.gauss(0.005, 0.01), 6)

        kpi_rows.append(Row(
            date=datetime.combine(current, datetime.min.time()),
            portfolio_segment=strategy,
            total_aum=round(total_aum, 1),
            weighted_avg_return=wav_ret,
            concentration_top5_pct=conc,
            benchmark_spread=bench_spread,
            manager_count=len(strategy_funds),
        ))
    current += timedelta(days=1)

kpi_df = spark.createDataFrame(kpi_rows)
kpi_df.write.option("mergeSchema", "true").mode(WRITE_MODE).saveAsTable(f"{SCHEMA}.fact_portfolio_kpis")
print(f"Created fact_portfolio_kpis: {len(kpi_rows)} rows")

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
print("Created portfolio_overview VIEW")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

tables = [
    "dim_funds", "fact_fund_performance", "fact_portfolio_holdings",
    "fact_fund_flows", "fact_portfolio_kpis"
]

print("=" * 60)
print("DATA GENERATION COMPLETE")
print("=" * 60)
for t in tables:
    count = spark.sql(f"SELECT COUNT(*) as cnt FROM {SCHEMA}.{t}").collect()[0][0]
    print(f"  {t}: {count:,} rows")
print(f"  portfolio_overview: VIEW")
print("=" * 60)
print()
print("Built-in patterns for the agent to discover:")
print("  - MedVenture Alpha (VC): declining returns last 6mo, on watchlist")
print("  - Asclepius Capital (PE Buyout): consistent top-performer, positive alpha")
print("  - BioGrowth Partners (Growth Equity): dangerous position concentration in top 3 holdings")
print("  - Genomics Partners / NovaBio (VC): J-curve — negative early returns, recovering")
print("  - PulsePoint Capital (Hedge Fund): style drift — recent vol spike vs historical profile")
print("  - MedTech Growth Fund: strong recent surge last 4 months")
print("  - MedAlliance Partners (PE Buyout): nearing exit with markups")
print("  - Q4 capital call spike across portfolio")
print("  - Growth Equity: top-5 concentration approaching IPS 30% limit")
print("  - SynapsePoint Capital: prospect fund under evaluation")

# COMMAND ----------

display(spark.table(f"{SCHEMA}.portfolio_overview"))
