# Databricks notebook source
# MAGIC %md
# MAGIC # Setup Investment Policy Vector Search
# MAGIC 
# MAGIC This notebook ingests investment policy statements (IPS) and related documents from text files,
# MAGIC chunks the content, and creates a vector search index for RAG-based investment policy retrieval.

# COMMAND ----------

# MAGIC %pip install databricks-vectorsearch --quiet
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# Configuration
dbutils.widgets.text("var.catalog", "", "Catalog")
dbutils.widgets.text("var.schema", "investment_intel", "Schema")
dbutils.widgets.text("var.vector_search_endpoint", "", "Vector Search Endpoint")
CATALOG = dbutils.widgets.get("var.catalog")
SCHEMA = dbutils.widgets.get("var.schema")
VECTOR_ENDPOINT = dbutils.widgets.get("var.vector_search_endpoint")
IPS_VECTOR_INDEX = f"{CATALOG}.{SCHEMA}.investment_policy_vector_index"
IPS_DOCS_TABLE = f"{CATALOG}.{SCHEMA}.investment_policy_docs"
IPS_PARSED_TABLE = f"{CATALOG}.{SCHEMA}.investment_policy_parsed"
IPS_CHUNKS_TABLE = f"{CATALOG}.{SCHEMA}.investment_policy_chunks"

print(f"Catalog: {CATALOG}")
print(f"Schema: {SCHEMA}")
print(f"Vector Endpoint: {VECTOR_ENDPOINT}")
print(f"Investment Policy Vector Index: {IPS_VECTOR_INDEX}")
print(f"IPS Docs Table: {IPS_DOCS_TABLE}")

# COMMAND ----------

spark.sql(f"USE CATALOG {CATALOG}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Ingest IPS Documents from Volume

# COMMAND ----------

IPS_VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/sop_samples"

# Create volume if it doesn't exist
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.sop_samples")

# Generate sample IPS docs if volume is empty
import os
vol_base = IPS_VOLUME_PATH
existing = dbutils.fs.ls(vol_base) if any(True for _ in [1]) else []
try:
    existing = [f.name for f in dbutils.fs.ls(vol_base) if f.name.endswith(".txt")]
except:
    existing = []

if not existing:
    print("No IPS files found — generating sample investment policy documents...")
    sample_docs = {

        "IPS_001_Investment_Policy_Statement.txt": """INVESTMENT POLICY STATEMENT
Meridian Capital Partners — Healthcare & Life Sciences Alternatives Fund
Effective: January 2026 | Version 4.2 | Board Approved: December 2025

SECTION 1 — PURPOSE, GOVERNANCE, AND FIDUCIARY FRAMEWORK
1.1 Purpose. This Investment Policy Statement (IPS) establishes the binding investment objectives, risk tolerances, and operational constraints governing the Meridian Capital Partners Healthcare & Life Sciences Alternatives Fund (the "Fund"). All investment decisions, portfolio construction activities, and risk management actions must conform to this document. Deviations require written approval from the Investment Committee with documentation filed within 48 hours.
1.2 Governance Structure. The Investment Committee (IC) meets biweekly and comprises the CIO, Head of Research, Head of Risk, and two independent board members. Quorum requires 4 of 5 members. The IC has sole authority over: (a) new fund commitments exceeding $25M, (b) strategy allocation changes beyond 3 percentage points, (c) watchlist additions/removals, (d) co-investment approvals, (e) any IPS exceptions.
1.3 Fiduciary Standard. The Fund operates under a prudent expert standard. All personnel must prioritize LP interests, avoid conflicts of interest, and document the rationale for every material investment decision in the deal memo system within 5 business days of execution.

SECTION 2 — INVESTMENT OBJECTIVES AND RETURN TARGETS
2.1 Primary Objective. Achieve a net-of-fees annualized return of 14-18% (gross 18-22%) over rolling 10-year periods, measured against the Cambridge Associates Healthcare PE Index.
2.2 Risk-Adjusted Target. Maintain a portfolio Sharpe ratio above 1.2 and a Sortino ratio above 1.5 on a rolling 3-year basis. Maximum drawdown tolerance: 25% peak-to-trough.
2.3 Income Component. Target a 3-5% annual yield from credit and royalty strategies to support distribution obligations without forced asset sales.
2.4 Benchmark Composite.
- 40% Cambridge Associates Healthcare PE Index
- 25% HFRI Healthcare Index
- 20% Cliffwater Direct Lending Healthcare Index
- 15% S&P Healthcare Select Sector (public market equivalent)
Benchmark rebalancing: quarterly, using trailing 12-month weights.
2.5 2026 Outlook and Objectives. For fiscal year 2026, the IC has approved the following tactical tilts relative to strategic targets:
- Overweight Venture Capital (+3%) to capture late-stage biotech IPO pipeline recovery
- Underweight Credit (-2%) given tightening spreads reducing relative value
- New allocation: Digital Health / AI-enabled diagnostics sleeve (5% target from VC and Growth Equity budgets)
- Manager consolidation: reduce total GP relationships from 45 to 38 by year-end, reallocating to top-quartile performers
Key 2026 priorities: (1) deploy $800M in new commitments across 8-12 funds, (2) harvest 3-5 mature PE positions at or above target IRR, (3) complete build-out of Asian healthcare exposure to 12% of NAV.

SECTION 3 — ASSET ALLOCATION AND STRATEGY GUIDELINES
3.1 Strategic Allocation with Tactical Ranges.
Strategy | Target | Min | Max | Rebalance Trigger
Private Equity (Buyout) | 28% | 20% | 36% | +/-5pp from target
Venture Capital (Early + Late) | 18% | 12% | 25% | +/-4pp from target
Growth Equity | 12% | 8% | 18% | +/-3pp from target
Hedge Funds (L/S Healthcare) | 15% | 8% | 22% | +/-4pp from target
Credit / Royalties | 12% | 5% | 18% | +/-4pp from target
Real Assets (MedTech RE, Labs) | 8% | 3% | 12% | +/-3pp from target
Cash / Liquid Reserves | 7% | 5% | 15% | Below 5% triggers mandatory liquidity raise
3.2 Rebalancing Protocol. When any allocation breaches its trigger band: (a) Risk team flags within 24 hours, (b) IC reviews within 5 business days, (c) rebalancing plan executed within 30 calendar days. Rebalancing via secondary market sales, commitment pacing adjustments, or tactical overlay hedges.
3.3 Vintage Year Diversification. No more than 20% of PE/VC commitments in any single vintage year. Rolling 5-year deployment target: $150-200M per vintage.
3.4 Geographic Allocation.
Region | Target | Maximum
North America | 60% | 75%
Europe | 20% | 30%
Asia-Pacific | 12% | 20%
Rest of World | 5% | 10%
3.5 Sub-Sector Diversification within Healthcare.
Sub-Sector | Target Range
Biopharma / Drug Development | 25-35%
Medical Devices / MedTech | 15-25%
Healthcare Services / Delivery | 15-20%
Digital Health / Health IT | 10-18%
Healthcare Real Estate / Labs | 5-12%
Diagnostics / Life Sciences Tools | 5-10%""",

        "IPS_002_Manager_Selection_Due_Diligence.txt": """MANAGER SELECTION AND DUE DILIGENCE FRAMEWORK
Meridian Capital Partners — Version 3.1 | Updated January 2026

SECTION 1 — INVESTMENT DUE DILIGENCE (QUANTITATIVE)
1.1 Track Record Requirements.
- Minimum 5 full years of audited performance history (3 years for emerging managers with team track record)
- Returns verified by independent fund administrator and cross-referenced with auditor
- Performance must be presented net of all fees using ILPA reporting standards
- For PE/VC: vintages must include at least one economic downturn period
1.2 Risk-Adjusted Performance Thresholds.
Metric | Minimum | Target
Net IRR (PE/VC) | 15% | 20%+
Gross MOIC (PE/VC) | 1.8x | 2.5x+
DPI (PE/VC, vintage >5yr) | 0.8x | 1.2x+
Sharpe Ratio (Hedge Funds) | 0.8 | 1.2+
Sortino Ratio (Hedge Funds) | 1.0 | 1.5+
Max Drawdown (Hedge Funds) | <20% | <12%
Loss Ratio (Credit) | <3% | <1.5%
1.3 Attribution and Consistency Analysis.
- Alpha decomposition: separate beta, factor, and idiosyncratic return components
- Return persistence: must demonstrate top-quartile ranking in at least 3 of last 5 reporting periods
- Dispersion analysis: fund-level return dispersion across vintages (PE) or annual periods (HF)
- Loss attribution: categorize all realized losses >5% by root cause (market, execution, thesis, fraud)
1.4 Strategy Evaluation Criteria.
- Clear articulation of competitive advantage and why it is sustainable (3-5 year forward view)
- Defined deal sourcing pipeline with proprietary origination metrics (target: >50% proprietary deals)
- Portfolio construction discipline: position sizing rules, concentration limits, sector allocation framework
- Exit strategy framework: defined hold period targets, exit route preferences, contingency plans

SECTION 2 — OPERATIONAL DUE DILIGENCE
2.1 Infrastructure Requirements.
- Independent fund administrator: required for all funds (no self-administered vehicles)
- Auditor: Big Four or nationally recognized specialist auditor with healthcare fund experience
- Prime broker(s): minimum 2 prime broker relationships for hedge fund strategies
- Legal counsel: independent counsel for fund formation, separate from GP personal counsel
- Valuation: independent third-party valuation agent for all Level 3 assets
2.2 Compliance and Controls.
- SEC or equivalent registration current; Form ADV Parts 1 and 2A reviewed
- Chief Compliance Officer: dedicated CCO (not dual-hatted with investment roles)
- Code of Ethics: written personal trading policy with pre-clearance and reporting requirements
- Insider Trading Policy: written policies and annual certification by all investment personnel
- AML/KYC: Bank Secrecy Act compliant program with documented procedures
2.3 Technology and Cybersecurity.
- SOC 2 Type II certification or equivalent for all managers with AUM > $500M
- Penetration testing: annual by independent third party
- Business continuity: documented DR plan tested at least annually
- Data classification: investor data handled per CCPA/GDPR requirements
2.4 Key Person and Succession.
- Key person clause: identify named principals whose departure triggers suspension of investment period
- Succession plan: documented leadership transition plan reviewed annually
- Retention: key investment professionals must have significant co-investment and deferred compensation alignment
2.5 ESG and Responsible Investing.
- PRI signatory status required for managers with AUM > $1B; preferred for all
- ESG integration: documented framework for incorporating ESG factors into investment analysis
- Exclusion screening: controversial weapons, thermal coal (>25% revenue), OFAC-sanctioned entities
- Climate risk: TCFD-aligned disclosure for real asset and infrastructure strategies
- Impact measurement: quantitative impact metrics required for any fund marketed as "impact"

SECTION 3 — MANAGER MONITORING AND WATCHLIST PROCEDURES
3.1 Ongoing Monitoring Cadence.
Review Type | Frequency
Performance Review | Monthly
Operational Compliance Check | Quarterly
On-site Visit / Deep Dive | Annual
Full Re-underwrite | Every 3 years or at re-up decision
3.2 Watchlist Criteria. A fund is placed on the watchlist when any of:
- Returns underperform benchmark by >500bps on trailing 12-month basis
- Key person departure or significant organizational change
- Regulatory action, litigation, or material compliance breach
- Material style drift (strategy allocation >10pp from stated mandate)
- Liquidity terms change materially (gate imposition, side pocket creation, redemption suspension)
- Operational incident (cybersecurity breach, valuation error, NAV restatement)
3.3 Watchlist Escalation Protocol.
Level 1 (Watch): Enhanced monitoring, monthly IC reporting. Duration: 6 months max before escalation or resolution.
Level 2 (Review): No new capital deployment, quarterly on-site review, demand remediation plan. Duration: 12 months max.
Level 3 (Exit): Initiate orderly redemption/secondary sale. Document lessons learned for future DD enhancement.
3.4 Redemption and Exit Procedures.
- Hedge funds: submit redemption notice per fund terms; stagger across quarters if >$50M to minimize market impact
- PE/VC: engage secondary market advisor for positions >$20M; target transfer at 85-100% of NAV
- Co-investments: coordinate exit timing with lead GP; independent valuation required for any transfer""",

        "IPS_003_Risk_Management_Framework.txt": """RISK MANAGEMENT FRAMEWORK
Meridian Capital Partners — Version 5.0 | Effective January 2026

SECTION 1 — MARKET RISK
1.1 Value-at-Risk.
- 95% daily VaR: not to exceed 1.5% of total portfolio NAV
- 99% monthly VaR: not to exceed 6% of total portfolio NAV
- VaR methodology: historical simulation using 5-year lookback with exponential decay (lambda=0.97)
- VaR exceedances: 3+ exceedances in any rolling 30-day period triggers IC emergency review
1.2 Stress Testing and Scenario Analysis.
Quarterly stress tests must model the following scenarios with full attribution:
Scenario | Expected Max Loss | Action Trigger
2008 GFC Replay | -20% to -30% | If >-25%: reduce equity beta to <0.2
COVID-19 Replay (2020) | -15% to -25% | If >-20%: activate liquidity reserve protocol
Rising Rates (+400bps over 18mo) | -8% to -15% | If >-12%: reduce duration, increase floating rate credit
Healthcare Regulatory Shock | -10% to -20% | If >-15%: review single-sector concentration
Biotech Pipeline Failure Cascade | -12% to -22% | If >-18%: reduce VC overweight, increase hedge fund allocation
Pandemic 2.0 (novel pathogen) | -5% to +10% | Evaluate long healthcare positioning benefit
1.3 Beta and Correlation Management.
- Portfolio beta to S&P 500: target <0.35, maximum 0.50
- Portfolio beta to S&P Healthcare: target <0.55, maximum 0.70
- Average pairwise strategy correlation: target <0.35, action required if >0.50
- Correlation regime monitoring: switch to stressed correlation matrix when VIX >30
1.4 Currency Risk.
- Non-USD exposure: maximum 25% of NAV unhedged
- Hedging requirement: mandatory for any single-currency exposure >8% of NAV
- Hedging instruments: forward contracts and options only (no exotic derivatives)
- Hedging cost budget: maximum 0.5% of NAV annually

SECTION 2 — LIQUIDITY RISK
2.1 Liquidity Classification Framework.
Tier 1 — Immediate (0-30 days): Cash, money markets, liquid listed equities. Target: minimum 7% of NAV.
Tier 2 — Near-term (30-90 days): Hedge fund redemptions (quarterly), liquid credit. Target: minimum 15% cumulative.
Tier 3 — Medium-term (90-365 days): Annual redemptions, co-investment secondaries. Target: minimum 30% cumulative.
Tier 4 — Illiquid (>1 year): PE/VC fund interests, lock-up positions. Maximum: 70% of NAV.
2.2 Liquidity Stress Test.
Model simultaneous: (a) 15% LP redemption across all liquid strategies, (b) 2 consecutive quarters of capital calls at 125% of forecast, (c) 50% reduction in distribution pace. Portfolio must survive this scenario without forced sales of Tier 4 assets for at least 18 months.
2.3 Cash Flow Forecasting.
- Capital call projections: 24-month forward forecast updated monthly using GP-provided estimates +20% buffer
- Distribution projections: 12-month forward using conservative assumptions (60% of GP guidance)
- Net cash flow: must be positive on a rolling 12-month basis; 3+ months negative triggers liquidity committee review
2.4 Credit Facility.
- Subscription credit line: maximum 15% of uncalled commitments, maximum 180-day draw period
- NAV-based credit line: maximum 10% of NAV, used only for bridge financing of secondary transactions
- Total leverage: combined credit facility utilization must not exceed 20% of NAV

SECTION 3 — CONCENTRATION RISK
3.1 Manager Concentration.
- Single GP exposure: maximum 8% of total portfolio NAV (reduced from 10% per 2025 IC review)
- Top-5 GP exposure: maximum 30% of NAV
- Emerging manager allocation: maximum 15% of NAV to GPs with <$500M AUM
3.2 Strategy Concentration.
- No single strategy may exceed its maximum allocation per Section 3.1 of the IPS
- Within PE, maximum 60% in any single deal stage (early, growth, buyout)
- Within Hedge Funds, maximum 50% in any single sub-strategy (L/S equity, event-driven, etc.)
3.3 Sector Concentration.
- Within healthcare: no single sub-sector to exceed 35% of total portfolio
- Non-healthcare exposure (via multi-sector funds): maximum 15% of NAV
3.4 Geographic Concentration.
- Single country maximum: 65% (US). All other countries: maximum 15% each.
- Emerging market healthcare: maximum 8% of NAV
3.5 Vintage Concentration.
- PE/VC commitments: maximum 20% of total PE/VC allocation in any single vintage year
- Target: 5-7 vintage year spread across active commitments
3.6 Single-Position Concentration.
- Any single underlying portfolio company (direct or via funds): maximum 3% of total NAV
- Co-investment concentration: maximum 5% of NAV in any single co-investment

SECTION 4 — COUNTERPARTY AND OPERATIONAL RISK
4.1 Counterparty Limits.
- Prime broker: minimum A- credit rating; diversified across at least 2 brokers
- OTC derivative counterparty: minimum A rating; daily margin settlement
- Fund administrator: annual SOC 1 Type II report required
4.2 Valuation Risk.
- Level 3 assets: independent valuation by qualified appraiser at least annually
- Valuation committee: quarterly review of all Level 3 marks and methodology
- NAV restatement threshold: any correction >1% of fund NAV triggers investor notification within 5 business days
4.3 Cybersecurity Risk.
- Annual penetration testing for all GPs managing >$1B
- Incident response: mandatory 72-hour notification to Meridian of any breach affecting investor data
- Insurance: GPs must carry cyber liability insurance with minimum $10M coverage

SECTION 5 — REPORTING AND ESCALATION
5.1 Risk Reporting Cadence.
Report | Frequency | Recipients
Flash Risk Summary | Daily | CIO, Head of Risk
Liquidity Dashboard | Weekly | IC, Portfolio Managers
Full Risk Report | Monthly | IC, Board, LPs (summary)
Stress Test Results | Quarterly | IC, Board, LP Advisory Committee
IPS Compliance Review | Quarterly | IC, Board, External Auditor
5.2 Escalation Matrix.
Severity 1 (Critical): VaR breach >2x limit, counterparty default, fraud suspicion. Action: immediate CIO notification, IC emergency meeting within 4 hours, LP notification within 24 hours.
Severity 2 (High): Single-name concentration breach, liquidity tier 1 below minimum, benchmark underperformance >800bps trailing 12mo. Action: IC review within 48 hours, remediation plan within 5 business days.
Severity 3 (Medium): Watchlist trigger, allocation drift approaching trigger band, operational incident at GP. Action: documented in next scheduled IC meeting, monitoring enhanced.""",

        "IPS_004_Capital_Flows_Liquidity_Policy.txt": """CAPITAL CALL, DISTRIBUTION, AND LIQUIDITY MANAGEMENT POLICY
Meridian Capital Partners — Version 3.3 | Effective January 2026

SECTION 1 — CAPITAL CALL MANAGEMENT
1.1 Call Scheduling and Forecasting.
- Capital call forecast: 24-month rolling projection updated monthly by each GP relationship manager
- Forecast methodology: GP guidance + 20% buffer for unscheduled calls (historically 15-25% of calls are unscheduled)
- Seasonal patterns: Q1 and Q3 historically represent 60% of annual capital calls; maintain higher Tier 1 liquidity in these periods
1.2 Call Processing Procedures.
- Notice period: minimum 10 business days (contractual); internal target: 15 business days advance preparation
- Maximum single call: 25% of unfunded commitment per call (unless fund documents permit higher for follow-on investments)
- Call priority: when multiple calls conflict with liquidity targets, prioritize by: (1) contractual obligation, (2) IC-rated fund priority tier, (3) call amount as % of unfunded
- Default provisions: 30-day cure period; default interest at SOFR + 400bps compounding daily; after cure period, LP interest may be reduced by 50% at GP discretion
1.3 Commitment Pacing.
- Annual commitment budget: set by IC in Q4 for following year based on projected distributions and dry powder
- 2026 commitment budget: $800M across 8-12 funds (approximately $200M per quarter)
- Overcommitment ratio: total unfunded commitments must not exceed 35% of total portfolio NAV
- Commitment reserves: maintain liquid assets equal to at least 40% of unfunded commitments due within 24 months

SECTION 2 — DISTRIBUTION MANAGEMENT
2.1 Distribution Waterfall.
Tier 1: Return of contributed capital (on a fund-by-fund basis)
Tier 2: Preferred return at 8% IRR compounding annually
Tier 3: GP catch-up to 20% of total profits
Tier 4: 80/20 split (LP/GP) on remaining profits
2.2 Distribution Processing.
- Cash distributions: deposited within 3 business days of receipt into the Fund's operating account
- In-kind distributions: accepted only with IC approval; must be valued by independent appraiser within 15 business days; liquidation plan required within 90 days unless IC approves hold
- Tax distributions: quarterly estimated tax distributions based on allocated taxable income per K-1 estimates
- Recallable distributions: track separately; maintain reserve for potential GP clawback (2-year escrow of 30% of carried interest distributions)
2.3 Distribution Reinvestment vs Payout.
- Default policy: 70% of distributions reinvested into new commitments; 30% available for LP payouts
- LP payout schedule: semi-annual (June and December), subject to minimum $10M aggregate payout
- Reinvestment priority: first to strategies below target allocation, then to highest-conviction new opportunities

SECTION 3 — CASH MANAGEMENT AND TREASURY
3.1 Operating Cash Reserve.
- Minimum: 5% of NAV in overnight / next-day liquidity instruments
- Target: 7% of NAV
- Maximum: 15% of NAV (excess above 15% must be deployed or distributed within 60 days)
3.2 Permitted Cash Investments.
- US Treasury bills and notes (maturity <1 year)
- Investment-grade commercial paper (A-1/P-1 rated, maturity <90 days)
- Money market funds (SEC Rule 2a-7 compliant, government or prime)
- Bank deposits: FDIC-insured accounts only, maximum $250K per institution or fully collateralized
3.3 Currency Management.
- Non-USD cash positions exceeding $5M equivalent: mandatory hedging within 10 business days
- Hedging instruments: forward contracts preferred; options permitted for uncertain commitment amounts
- Currency P&L: tracked separately and attributed to currency management, not investment performance

SECTION 4 — LIQUIDITY CONTINGENCY PROCEDURES
4.1 Liquidity Alert Levels.
Green: Tier 1 liquidity >7% of NAV, net cash flow positive 12mo forward. Normal operations.
Yellow: Tier 1 liquidity 5-7% of NAV, or net cash flow negative for 2+ consecutive months. Actions: weekly liquidity committee meetings, defer new commitments pending review, prepare secondary market list.
Red: Tier 1 liquidity <5% of NAV, or inability to meet capital calls within notice period. Actions: daily liquidity meetings, suspend all new commitments, activate credit facility, initiate secondary sales of lowest-priority positions, notify LP Advisory Committee.
4.2 Secondary Market Sales.
- Initiation authority: IC approval required for any secondary sale >$10M
- Pricing: independent valuation required; minimum acceptable discount: 85% of NAV for performing assets, 70% for watchlist assets
- Broker selection: minimum 2 competitive bids for positions >$25M
- Tax efficiency: coordinate with tax counsel to optimize timing and structure
4.3 Credit Facility Drawdown.
- First resort: subscription credit line (lower cost, limited duration)
- Second resort: NAV-based facility (higher cost, more flexible)
- IC notification: required within 24 hours of any drawdown >$25M
- Repayment: mandatory repayment from next available distribution proceeds

SECTION 5 — REPORTING
5.1 Cash Flow Reporting.
Report | Frequency | Content
Cash Flow Forecast | Monthly | 24-month projection of calls, distributions, and net flow
Liquidity Dashboard | Weekly | Tier 1-4 breakdown, alert level, credit facility status
Capital Call Summary | Monthly | Calls received, calls projected, calls funded, aging
Distribution Log | Monthly | Distributions received by fund, reinvestment allocation
5.2 LP Reporting.
- Capital account statements: quarterly, delivered within 60 days of quarter-end
- Distribution notices: 5 business days advance notice with detailed waterfall calculation
- Annual K-1 delivery: target March 15; extension notice if >April 1
- Semi-annual LP letter: qualitative commentary on portfolio, market outlook, and capital management""",

        "IPS_005_Compliance_Regulatory_Framework.txt": """COMPLIANCE AND REGULATORY FRAMEWORK
Meridian Capital Partners — Version 4.0 | Effective January 2026

SECTION 1 — REGULATORY REGISTRATION AND REPORTING
1.1 Fund Registration.
- Primary fund: organized as Delaware limited partnership, exempt under Section 3(c)(7) of the Investment Company Act (qualified purchasers only)
- Feeder funds: Cayman Islands exempted limited partnership (offshore investors), Delaware LLC (tax-exempt investors)
- Regulatory filings: Form PF (quarterly for large fund advisers), Form D (annual), CFTC exemption (if applicable)
1.2 Adviser Registration.
- SEC-registered investment adviser under the Investment Advisers Act of 1940
- Form ADV Parts 1, 2A, and 2B: updated annually (within 90 days of fiscal year-end) and promptly for material changes
- State registrations: as required for marketing in specific states
1.3 ERISA and Tax-Exempt Compliance.
- "Significant participation" test: ERISA plan assets must not exceed 25% of any fund class
- VCOC qualification: maintain at least one portfolio company with management rights
- UBTI monitoring: quarterly assessment of debt-financed income and operating income allocable to tax-exempt LPs

SECTION 2 — INVESTMENT RESTRICTIONS AND PROHIBITED ACTIVITIES
2.1 Absolute Prohibitions.
- No investments in entities on OFAC Specially Designated Nationals (SDN) list
- No investments in controversial weapons manufacturers (cluster munitions, anti-personnel mines, biological/chemical weapons)
- No direct investments in cannabis (federal legality constraints)
- No principal transactions between fund and GP-affiliated entities without full LP Advisory Committee disclosure and consent
2.2 Restricted Activities (Require IC + Compliance Approval).
- Cryptocurrency and digital asset investments: requires IC supermajority (4/5) approval and dedicated operational framework
- Leverage at fund level: GP subscription credit line only; no margin borrowing against fund assets
- Public market investments: permitted up to 10% of NAV (for PIPE transactions, post-IPO positions); holding period >6 months requires IC review
- Cross-fund investments: prohibited without independent pricing, full disclosure, and LP Advisory Committee consent
2.3 Concentration and Exposure Limits (Regulatory).
- Single-issuer exposure (registered fund holdings): maximum 5% at time of purchase (1940 Act diversification)
- Illiquid assets: maximum 70% of NAV (aligned with SEC proposed guidance)
- Affiliated transactions: zero tolerance without documented compliance review

SECTION 3 — CONFLICTS OF INTEREST AND CODE OF ETHICS
3.1 Personal Trading Policy.
- All investment personnel: pre-clearance required for any personal securities transaction >$10,000
- Blackout periods: no personal trading in healthcare securities during 5 business days preceding/following fund transactions in same sector
- Holding period: minimum 30-day hold for any personal investment in healthcare sector
- Reporting: quarterly personal holdings reports; annual certification of compliance
3.2 Gift and Entertainment.
- Receiving: maximum $250 per person per year from any single business counterparty
- Giving: maximum $100 per person per year to any single business counterparty
- Meals/events: pre-approval required for any event >$150 per person; all events logged in compliance system
3.3 Outside Activities.
- Board memberships: pre-approval required; annual conflict review
- Speaking engagements: pre-approval for any compensated engagement; review for material non-public information risk
- Political contributions: monitored under SEC pay-to-play rule (Rule 206(4)-5)
3.4 LP Advisory Committee.
- Composition: 5-7 LP representatives, no GP affiliates
- Approval authority: related-party transactions, valuation disputes >1% of fund NAV, IPS material amendments, GP removal
- Meeting frequency: quarterly, with special sessions as needed

SECTION 4 — VALUATION GOVERNANCE
4.1 Fair Value Hierarchy (ASC 820 Compliant).
Level 1: Quoted prices in active markets for identical assets. Used for listed equity positions, money markets.
Level 2: Observable inputs other than Level 1 quotes. Used for credit instruments with dealer quotes, OTC derivatives with observable underlyings.
Level 3: Unobservable inputs based on internal models. Used for PE/VC fund interests, illiquid co-investments, real assets.
4.2 Valuation Frequency and Methodology.
- Level 1 assets: daily mark-to-market
- Level 2 assets: monthly, using median of 3+ dealer quotes
- Level 3 assets: quarterly marks by GP; annual independent valuation by qualified appraiser (ASA or CFA Charter holder with 10+ years alternative asset experience)
4.3 Valuation Committee.
- Composition: CIO (chair), Head of Risk, CFO, independent board member
- Meeting frequency: quarterly (after receipt of GP quarterly NAV statements)
- Authority: approve all Level 3 valuations, resolve pricing disputes, approve methodology changes
- Documentation: detailed minutes with rationale for all material valuation judgments
4.4 NAV Restatement Protocol.
- Material threshold: any correction exceeding 1% of fund-level NAV
- Notification: LP written notice within 5 business days of discovery
- Remediation: root cause analysis within 15 business days; process improvement plan within 30 days

SECTION 5 — DATA PRIVACY, CYBERSECURITY, AND RECORD RETENTION
5.1 Investor Data Protection.
- CCPA compliance: California investor opt-out rights honored within 30 days
- GDPR compliance: EU/UK investor data processing per documented legal basis; DPO appointed
- Data minimization: collect only information necessary for KYC/AML, tax reporting, and investor servicing
5.2 Cybersecurity Program.
- Written information security policy: reviewed annually by CISO and external consultant
- Employee training: mandatory annual cybersecurity awareness training with phishing simulation
- Incident response plan: documented playbook with <4-hour initial response SLA
- Vendor risk management: annual cybersecurity assessment questionnaire for all Tier 1 service providers (administrator, auditor, prime broker, cloud providers)
5.3 Record Retention.
- Investor records: minimum 7 years post-relationship termination
- Investment records: minimum 10 years post-fund liquidation
- Communications: all electronic communications retained for 5 years; archived and searchable
- Trade records: minimum 7 years per SEC Rule 204-2""",

        "IPS_006_Performance_Attribution_Benchmarking.txt": """PERFORMANCE ATTRIBUTION AND BENCHMARKING STANDARDS
Meridian Capital Partners — Version 2.1 | Effective January 2026

SECTION 1 — PERFORMANCE MEASUREMENT METHODOLOGY
1.1 Return Calculation Standards.
- Time-weighted returns (TWR): used for portfolio-level and strategy-level performance reporting
- Internal rate of return (IRR): used for individual fund and co-investment performance
- Modified Dietz method: used for interim period calculations between full valuations
- All returns reported net of management fees and carried interest; gross returns reported in supplemental schedules
1.2 Performance Periods.
- Monthly: TWR for total portfolio and each strategy bucket
- Quarterly: IRR for each fund investment, updated with GP-provided NAV
- Annual: comprehensive attribution including vintage year, strategy, geography, and sector decomposition
- Since-inception: cumulative performance from fund launch to current period
1.3 Survivorship and Selection Bias.
- Terminated/exited positions: included in historical performance for full holding period
- Unrealized positions: marked at most recent fair value per valuation policy
- Index comparison: use funds-of-funds indices where available to capture selection effects

SECTION 2 — ATTRIBUTION FRAMEWORK
2.1 Multi-Level Attribution.
Level 1 — Asset Allocation Effect: Measures the contribution of strategy allocation decisions relative to benchmark weights. Calculated as: (actual weight - benchmark weight) x (benchmark strategy return - benchmark total return).
Level 2 — Manager Selection Effect: Measures the contribution of individual GP selection within each strategy. Calculated as: benchmark weight x (actual manager return - benchmark strategy return).
Level 3 — Interaction Effect: Residual capturing the combined impact of allocation and selection decisions.
2.2 Factor Decomposition (for Hedge Fund and Public Market Components).
Required factors for regression-based attribution:
- Market factor: S&P 500 Healthcare Index beta
- Size factor: Russell 2000 Healthcare minus Russell 1000 Healthcare
- Value factor: healthcare value minus healthcare growth (Fama-French methodology)
- Momentum factor: healthcare 12-1 month momentum
- Quality factor: healthcare ROE quintile spread
- Volatility factor: CBOE Healthcare VIX proxy
Target: idiosyncratic alpha (unexplained by factors) should represent >60% of excess returns
2.3 Private Market Attribution.
- Vintage year attribution: compare each vintage to Cambridge Associates Healthcare PE Index same-vintage
- Value creation decomposition: revenue growth, margin expansion, multiple expansion, leverage effect
- PME (Public Market Equivalent): Long-Nickels PME using S&P Healthcare as public benchmark for each PE/VC fund
- Quartile ranking: each fund ranked within strategy-specific peer group (Cambridge, Preqin, or Burgiss)

SECTION 3 — BENCHMARK SELECTION AND MAINTENANCE
3.1 Composite Benchmark Construction.
The fund's composite benchmark blends public and private market indices:
Component | Weight | Index
Private Equity Healthcare | 40% | Cambridge Associates US Healthcare PE/VC Index
Healthcare Hedge Funds | 25% | HFRI Healthcare Index (or HFR custom if available)
Healthcare Credit | 20% | Cliffwater Direct Lending HC Sub-Index
Public Healthcare Equivalent | 15% | S&P Healthcare Select Sector Index (total return)
3.2 Benchmark Rebalancing.
- Frequency: quarterly, on the first business day of each quarter
- Methodology: rebalance to target weights using trailing 12-month actual allocation as adjustment signal
- Lag adjustment: private market benchmark returns reported with 1-quarter lag; address by using interpolated quarterly estimates from Cambridge preliminary data
3.3 Benchmark Review.
- Annual review: IC evaluates benchmark appropriateness during Q4 IPS review
- Change criteria: benchmark change requires IC supermajority vote; effective date is next calendar year
- Historical treatment: benchmark changes applied prospectively only; prior periods retain original benchmark

SECTION 4 — UNDERPERFORMANCE PROCEDURES
4.1 Underperformance Thresholds.
Level | Definition | Action
Watch | Fund trails benchmark by >300bps trailing 12 months | Monthly monitoring, GP engagement call
Review | Fund trails benchmark by >500bps trailing 12 months OR bottom quartile for 2 consecutive years | Watchlist addition, enhanced DD, no new commitments
Exit | Fund trails benchmark by >800bps trailing 12 months OR bottom decile any period >18 months | Initiate redemption/secondary sale process
4.2 Portfolio-Level Underperformance.
- Total portfolio underperforms composite benchmark by >200bps over any rolling 3-year period: IC review of strategy allocation and manager selection
- Total portfolio underperforms composite benchmark by >400bps over any rolling 3-year period: engage external consultant for independent portfolio review
4.3 Peer Comparison Context.
- All underperformance assessments consider peer group context (market conditions, strategy dispersion)
- No automatic action for underperformance during periods of extreme market stress (VIX >40, pandemic, financial crisis)
- IC retains discretion to override mechanical watchlist triggers with documented rationale""",

        "IPS_007_ESG_Responsible_Investment.txt": """ESG AND RESPONSIBLE INVESTMENT POLICY
Meridian Capital Partners — Version 2.0 | Effective January 2026

SECTION 1 — ESG INTEGRATION FRAMEWORK
1.1 Policy Commitment.
Meridian Capital Partners is a signatory to the UN Principles for Responsible Investment (PRI) and integrates environmental, social, and governance (ESG) factors into all stages of the investment lifecycle: due diligence, portfolio construction, monitoring, and exit.
1.2 Materiality-Based Approach.
ESG integration is materiality-driven, focusing on factors most relevant to healthcare and life sciences investing:
Environmental: pharmaceutical waste disposal, clinical trial environmental impact, supply chain sustainability, energy efficiency in manufacturing, climate resilience of research facilities.
Social: patient safety and drug efficacy, clinical trial ethics and diversity, healthcare access and affordability, employee health and safety, data privacy (HIPAA, patient data), community health impact.
Governance: board independence and expertise, executive compensation alignment, regulatory compliance history, transparency in drug pricing, lobbying and political activity disclosure.
1.3 ESG Scoring Methodology.
Each fund investment is scored on a 1-5 scale across E, S, and G dimensions:
5 — Industry leader with comprehensive ESG program and measurable outcomes
4 — Above average with clear ESG integration and reporting
3 — Meets minimum expectations; room for improvement
2 — Below expectations; engagement required
1 — Material ESG concerns; watchlist consideration
Composite ESG score: weighted average (E: 25%, S: 40%, G: 35%) reflecting healthcare sector materiality.
Minimum score for new investments: 2.5 composite (no individual dimension below 2.0)

SECTION 2 — EXCLUSION AND RESTRICTION SCREENING
2.1 Absolute Exclusions.
- Controversial weapons: cluster munitions, anti-personnel mines, biological/chemical weapons, nuclear weapons (dedicated manufacturers)
- Tobacco: companies deriving >10% revenue from tobacco products
- OFAC-sanctioned entities and individuals
- Companies with verified involvement in forced labor or human trafficking
2.2 Conditional Restrictions (Require IC + ESG Committee Approval).
- Fossil fuel companies: excluded from direct investment; permitted in diversified fund portfolios if <5% of fund NAV
- Animal testing: permitted only where required by FDA or equivalent regulatory authority for drug/device approval
- Opioid manufacturers: case-by-case review; excluded if company subject to material litigation without credible remediation plan
- Private prisons / detention: excluded from direct investment
2.3 Controversy Monitoring.
- Screen all portfolio exposures quarterly against MSCI ESG Controversies, RepRisk, and Sustainalytics incident databases
- Red flag threshold: any "severe" controversy rating triggers IC review and potential watchlist consideration
- Engagement first: preference for constructive engagement over divestment where Meridian has meaningful influence

SECTION 3 — CLIMATE AND ENVIRONMENTAL RISK
3.1 TCFD-Aligned Disclosure.
- Portfolio-level carbon footprint: calculated annually using Scope 1 and 2 data (Scope 3 where material and available)
- Climate scenario analysis: biennial assessment of portfolio resilience under IEA Net Zero 2050 and Current Policies scenarios
- Physical risk assessment: annual review of portfolio company exposure to extreme weather, water scarcity, and pandemic risk
3.2 Net Zero Alignment.
- Interim target: 30% reduction in portfolio-weighted carbon intensity by 2030 (vs 2022 baseline)
- Long-term target: net zero portfolio emissions by 2050, aligned with Science Based Targets initiative (SBTi) framework
- Transition pathway: annual IC review of progress; prioritize engagement with highest-emitting portfolio companies

SECTION 4 — DIVERSITY, EQUITY, AND INCLUSION
4.1 GP Diversity Assessment.
- Track and report: percentage of investment professionals who are women, underrepresented minorities, and veterans
- Minimum expectation: 30% diverse representation at senior investment level by 2028
- Emerging diverse managers: dedicate minimum 10% of annual commitment budget to diverse-owned or diverse-led GPs
4.2 Portfolio Company DEI.
- Board diversity: encourage portfolio companies to achieve >30% diverse board representation
- Pay equity: request annual pay equity audit from portfolio companies with >500 employees
- Inclusive hiring: support portfolio companies in implementing structured interview processes and diverse candidate slates

SECTION 5 — IMPACT MEASUREMENT AND REPORTING
5.1 Impact Metrics (for Impact-Designated Allocations).
All investments in the impact sleeve (target: 10-15% of NAV) must report:
- Lives impacted: patients served, clinical outcomes improved, healthcare access expanded
- Access metrics: underserved populations reached, geographic reach into healthcare deserts
- Innovation metrics: FDA approvals, breakthrough therapy designations, novel mechanism-of-action drugs
- Economic metrics: jobs created, healthcare cost savings achieved
5.2 Reporting Framework.
- IRIS+ (Global Impact Investing Network) aligned metrics where applicable
- Annual Impact Report: published alongside financial annual report
- Third-party verification: biennial independent impact audit by qualified ESG consultant"""
    }
    for fname, content in sample_docs.items():
        path = f"{vol_base}/{fname}"
        dbutils.fs.put(path, content.strip(), overwrite=True)
        print(f"  Created {fname}")
    print(f"Generated {len(sample_docs)} sample IPS documents")

# Build docs table from volume
spark.sql(f"""
CREATE OR REPLACE TABLE {IPS_DOCS_TABLE} AS
SELECT 
    path,
    decode(content, 'UTF-8') as content,
    regexp_extract(path, '[^/]+$', 0) as filename
FROM read_files('{IPS_VOLUME_PATH}/*.txt', format => 'binaryFile')
WHERE content IS NOT NULL
""")

try:
    count = spark.sql(f"SELECT COUNT(*) FROM {IPS_DOCS_TABLE}").collect()[0][0]
    print(f"IPS documents table created with {count} documents")
    display(spark.sql(f"SELECT filename, LENGTH(content) as content_length FROM {IPS_DOCS_TABLE} LIMIT 5"))
except Exception as e:
    print(f"ERROR: Could not create IPS docs table: {e}")
    print(f"Ensure IPS files exist in {IPS_VOLUME_PATH}")
    print("Expected files: IPS_001_Investment_Policy_Statement.txt, IPS_002_Due_Diligence_Checklist.txt, etc.")
    dbutils.notebook.exit("IPS documents not found")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Prepare Parsed Content for Chunking

# COMMAND ----------

# IPS files are already text - use content directly (no ai_parse_document needed)
spark.sql(f"""
CREATE OR REPLACE TABLE {IPS_PARSED_TABLE} AS
SELECT 
    path as source_path,
    filename,
    content as parsed_text,
    current_timestamp() as parsed_at
FROM {IPS_DOCS_TABLE}
WHERE content IS NOT NULL AND LENGTH(content) > 0
""")

parsed_count = spark.sql(f"SELECT COUNT(*) FROM {IPS_PARSED_TABLE}").collect()[0][0]
print(f"Prepared {parsed_count} investment policy documents for chunking")

# COMMAND ----------

# Display sample of parsed content
display(spark.sql(f"""
SELECT 
    filename, 
    LENGTH(parsed_text) as text_length,
    LEFT(parsed_text, 500) as text_preview
FROM {IPS_PARSED_TABLE}
LIMIT 5
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Chunk Documents for Embedding

# COMMAND ----------

# Create chunks table with proper chunking strategy
# Using paragraph-based splitting with overlap
spark.sql(f"""
CREATE OR REPLACE TABLE {IPS_CHUNKS_TABLE}
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
    FROM {IPS_PARSED_TABLE}
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

chunk_count = spark.sql(f"SELECT COUNT(*) FROM {IPS_CHUNKS_TABLE}").collect()[0][0]
print(f"Created {chunk_count} chunks from investment policy documents")

# COMMAND ----------

# Display chunk distribution
display(spark.sql(f"""
SELECT 
    filename,
    COUNT(*) as chunk_count,
    AVG(chunk_length) as avg_chunk_length,
    MIN(chunk_length) as min_length,
    MAX(chunk_length) as max_length
FROM {IPS_CHUNKS_TABLE}
GROUP BY filename
ORDER BY chunk_count DESC
"""))

# COMMAND ----------

# Sample chunks
display(spark.sql(f"""
SELECT chunk_id, filename, section_title, chunk_length, LEFT(chunk_text, 300) as preview
FROM {IPS_CHUNKS_TABLE}
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
    existing_index = vsc.get_index(endpoint_name=VECTOR_ENDPOINT, index_name=IPS_VECTOR_INDEX)
    index_exists = True
    print(f"Index {IPS_VECTOR_INDEX} already exists")
except Exception as e:
    print(f"Index does not exist: {e}")

if index_exists:
    print(f"Syncing existing index {IPS_VECTOR_INDEX}...")
    try:
        vsc.get_index(VECTOR_ENDPOINT, IPS_VECTOR_INDEX).sync()
        print("Sync triggered successfully")
    except Exception as e:
        print(f"Sync status: {e}")
else:
    print(f"Creating investment policy vector index {IPS_VECTOR_INDEX}...")
    try:
        vsc.create_delta_sync_index(
            endpoint_name=VECTOR_ENDPOINT,
            index_name=IPS_VECTOR_INDEX,
            source_table_name=IPS_CHUNKS_TABLE,
            pipeline_type="TRIGGERED",
            primary_key="chunk_id",
            embedding_source_column="chunk_text",
            embedding_model_endpoint_name="databricks-gte-large-en"
        )
        print(f"Index {IPS_VECTOR_INDEX} created successfully")
    except BadRequest as e:
        if "already exists" in str(e):
            print(f"Index already exists (UC entity), syncing instead...")
            try:
                vsc.get_index(VECTOR_ENDPOINT, IPS_VECTOR_INDEX).sync()
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
    index = vsc.get_index(endpoint_name=VECTOR_ENDPOINT, index_name=IPS_VECTOR_INDEX)
    results = index.similarity_search(
        query_text="asset allocation guidelines and rebalancing policy",
        columns=["chunk_id", "chunk_text", "source_doc", "section_title"],
        num_results=3
    )
    print("Test search results for 'asset allocation guidelines and rebalancing policy':")
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
print("INVESTMENT POLICY VECTOR SEARCH SETUP COMPLETE")
print("=" * 60)
print(f"Source Docs: {IPS_DOCS_TABLE}")
print(f"Parsed Table: {IPS_PARSED_TABLE}")
print(f"Chunks Table: {IPS_CHUNKS_TABLE}")
print(f"Vector Index: {IPS_VECTOR_INDEX}")
print(f"Vector Endpoint: {VECTOR_ENDPOINT}")
print("")
print(f"Total chunks indexed: {chunk_count}")
print("")
print("The index may take a few minutes to fully sync.")
print("Agents can now use search_investment_policies tool to query investment policy documents.")
print("=" * 60)
