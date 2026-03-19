# Hospital Control Tower -- Demo Walkthrough

A structured 15-minute demo guide. Each section includes what to show, what to say, what to expect, and how to recover if something goes wrong.

---

## Pre-Demo Checklist

- Confirm the app is running at its Databricks Apps URL
- Verify the health score is visible in the header (not `--/100`). If missing, click **Inject Good** twice and refresh
- Clear any leftover chat messages (click the trash icon at the bottom of the chat panel)
- Confirm mode is set to **Quick Query** (the default)
- Confirm Autonomous mode is **stopped**

---

## Act 1 -- Frame the Problem (2 min)

**Goal:** Establish context before showing the solution.

### Talking Points

> "Hospital operations teams today manage dozens of disconnected dashboards -- one for ED throughput, another for staffing, another for costs, another for quality. Most are purely reactive: you discover a problem after it has already impacted patient care or increased costs."
>
> "What if your operations platform could proactively monitor everything, identify root causes across data silos, and recommend specific actions grounded in your own SOPs -- all through a conversational interface?"

### What to Show

1. **Health Score** (header, top-left)
   - Point out the composite score (e.g., "72/100 -- Attention needed")
   - Hover over it to reveal the tooltip: 40% LOS + 30% readmission rate + 30% ED breaches

2. **Dashboard Panel** (right side)
   - Walk through the KPI cards: Encounters, Average LOS, Readmission Rate
   - Highlight the trend arrows (week-over-week direction)
   - Briefly call out the 30-Day Encounter Volume chart, ED Wait tiles, Drug Cost breakdown, and Staffing Mix

3. **Active Alerts** (if any are displayed)
   - "These alerts are generated automatically from the latest data -- not manually configured thresholds."

---

## Act 2 -- Quick Query vs. Deep Analysis (6 min)

**Goal:** Demonstrate both agent modes and contrast speed versus depth.

### Quick Query (2 min)

1. Confirm **Quick Query** mode is active
2. Type: **"What is the average LOS at Hospital A?"**
3. Press Enter

**Expected behavior:** A response appears in 2-5 seconds with a specific number and supporting context.

> "Quick Query uses a single-step ReAct agent with pre-selected tools. It classifies your intent -- data lookup, document search, or operational analysis -- and routes to the right tool. You get fast, focused answers."

If the first query takes longer than 10 seconds, note: "The first query warms up the model connection. Subsequent queries are faster."

4. Optionally ask a follow-up: **"Compare that to Hospital B"**

### Deep Analysis (4 min)

1. Switch to **Deep Analysis** mode (click the toggle in the header)
2. Click a suggestion chip, e.g., **"Why did drug costs spike in November?"**

**Expected behavior:** Stage indicators update as the analysis progresses:

| Stage | Typical Duration |
|-------|-----------------|
| Starting | 1-3 seconds |
| Planning | 5-10 seconds |
| Retrieving | 10-30 seconds |
| Analyzing | 10-20 seconds |
| Responding | 5-10 seconds |

While waiting, explain the architecture:

> "Deep Analysis uses a multi-agent graph. An LLM supervisor decides what to do next -- it may plan what data to gather, dispatch a retrieval agent to query SQL tables and vector search, then hand off to an analyst agent that interprets the evidence and writes a structured report."
>
> "Notice the tool calls listed at the bottom of the response. You can see exactly which data sources were queried, including SOP document lookups."

3. **Walk through the response structure:**
   - Evidence citations with specific data points
   - Impact assessment
   - SOP-grounded recommendations

If the analysis errors or times out, say: "Let me try a more targeted question," then ask: **"Analyze the staffing mix in the Cardiology department."**

---

## Act 3 -- Autonomous Agent and Data Injection (5 min)

**Goal:** Show proactive monitoring and the data injection testing workflow.

### Data Injection (2 min)

1. Click **Inject Anomaly** in the Demo Tools bar
   - A toast notification confirms the injected encounters
   - Wait 2-3 seconds for the health score to update (it should drop)

> "For demo purposes, we can inject test data. These encounters have elevated LOS, high costs, and readmission flags. The batch size is configurable in Settings. Watch how the health score responds in real time."

2. If an alert tile appears, **click it**
   - This pre-fills a Deep Analysis query in the chat
   - "The dashboard and the agent are connected -- clicking an alert launches an investigation."

### Autonomous Mode (3 min)

3. Click **Auto Start**
   - Point out the countdown timer (e.g., "2h 0m remaining")

> "The autonomous agent runs on a configurable schedule. It first performs a health check across all metrics, and only if it detects issues does it generate a full recommended actions report. It auto-stops after 2 hours to prevent runaway compute usage."

4. Click **Check Health** to trigger an immediate health check
   - "You do not have to wait for the schedule. This triggers a health check right now."

5. Wait for a recommended action to appear in the Recommended Actions tile (or point to an existing one)

> "Every recommendation is SOP-grounded. The agent searches your standard operating procedures before making suggestions, so you get actionable, institution-specific advice -- not generic suggestions."

6. Click **Stop** to end Autonomous mode before continuing.

---

## Wrap-Up (2 min)

### Architecture Summary

> "Everything runs on Databricks:"

| Component | Role |
|-----------|------|
| **Unity Catalog** | Data governance, table management, and access control |
| **Vector Search** | Encounter similarity search and SOP document retrieval |
| **Foundation Models** | Claude Sonnet for reasoning, GTE for embeddings -- no external API keys required |
| **MLflow** | Agent tracing and observability |
| **Databricks Apps** | Production deployment (Flask + React) |
| **Asset Bundles** | Reproducible, version-controlled deployment |
| **Lakebase** | Optional transactional storage for agent outputs |

### Closing

> "This is a solution accelerator -- a working starting point, not a demo-only prototype. The data model, agent prompts, and SOP documents are all customizable. A customer can adapt this to their specific hospitals, departments, and operating procedures in weeks, not months."

---

## Recovery Playbook

| Symptom | Resolution |
|---------|-----------|
| Health score shows `--/100` | Data tables may be empty. Click **Inject Good** a few times, then refresh the page. |
| Deep Analysis returns an error | Try a simpler question in Quick Query mode to verify connectivity, then retry. |
| Deep Analysis hangs with no stage updates | Wait up to 90 seconds. If still stuck, refresh the page. The 5-minute timeout will surface an error message. |
| Dashboard tiles show "No data" | Click **Inject Good** to seed test encounters, or run `databricks bundle run generate_data -t dev`. |
| Autonomous mode does not start | Check the Settings panel. The interval may be set too high. Set it to 60 seconds for demos. |
| App returns 502 or 503 | The app may be restarting. Wait 30 seconds and refresh. Check Databricks Apps logs if the issue persists. |
