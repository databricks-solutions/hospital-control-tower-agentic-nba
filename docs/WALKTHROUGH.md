# Hospital Control Tower -- Demo Walkthrough

A 15-minute guided demo for presenting Hospital Control Tower to customers. Each section includes what to click, what to say, what to expect, and recovery steps.

## Before the Demo

- Confirm the app is running at its Databricks Apps URL
- Verify the health score is visible (not `--/100`). If missing, run `databricks bundle run generate_data -t dev` and wait 2 minutes
- Clear chat history if there are leftover messages from previous demos (click "Clear chat" at the bottom)
- Set mode to **Deep Analysis** (default)
- Confirm Autonomous mode is **stopped**

---

## Act 1 -- The Problem (2 min)

**Goal:** Frame the problem before showing the solution.

### Talking Points

> "Hospital operations teams today manage dozens of disconnected dashboards -- one for ED throughput, one for staffing, one for costs, one for quality metrics. Most are reactive: you discover a problem after it has already impacted patient care or driven up costs."
>
> "What if your operations platform could proactively monitor everything, identify root causes, and recommend specific actions grounded in your own SOPs -- all through a conversational interface?"

### Actions

1. **Point to the health score** in the header (e.g., "72/100 -- Attention needed")
   - "This composite score summarizes LOS, readmission rates, and ED breaches in one number."
   - Hover to show the tooltip breakdown (40% LOS + 30% readmit + 30% ED)

2. **Point to the dashboard panel** on the right
   - Walk through the stat cards: Encounters, Avg LOS, Readmission Rate
   - Point out trend arrows (week-over-week)
   - Briefly note the 30-Day Encounter Volume chart, ED Wait tiles, Drug Cost, and Staffing Mix

3. **Point to Active Alerts** if any are showing
   - "These are automatically generated from the latest data -- not manually configured thresholds."

---

## Act 2 -- Quick Query vs. Deep Analysis (6 min)

**Goal:** Show both agent modes and contrast speed vs. depth.

### Quick Query (2 min)

1. Switch to **Quick Query** mode (click the toggle)
2. Type: **"What's the average LOS at Hospital A?"**
3. Press Enter

**What to expect:** Response in 2-5 seconds with a specific number and context.

**Say:**
> "Quick Query uses a single ReAct agent with pre-selected tools. It classifies your intent -- is this a data lookup, a search, or an analysis? -- and routes to the right tools. Fast, focused answers."

**If it takes longer than 10s:** Say "The first query warms up the connection. Subsequent queries are faster." and wait.

4. Optionally ask a follow-up: **"Compare that to Hospital B"**

### Deep Analysis (4 min)

1. Switch to **Deep Analysis** mode
2. Click the suggestion chip: **"Why did drug costs spike in November?"**

**What to expect:** Stage indicators update as the analysis progresses:
- "Starting..." (1-3s)
- "Planning..." (5-10s)
- "Retrieving..." (10-30s)
- "Analyzing..." (10-20s)
- "Responding..." (5-10s)

**While waiting, explain the architecture:**
> "Deep Analysis uses a multi-agent graph. An LLM supervisor decides what to do next -- it might ask for clarification, plan what data to gather, dispatch a retrieval agent to query SQL and vector search, then hand off to an analyst agent that interprets the evidence and writes a structured report."
>
> "Notice the tool calls at the bottom of the response -- you can see exactly which data sources were queried, including SOP document lookups."

3. **Point out the response structure:**
   - Evidence citations
   - Impact assessment
   - SOP-grounded recommendations

**If it errors or times out:** Say "Let me try a simpler deep analysis" and ask: "Analyze the staffing mix in the Cardiology department."

---

## Act 3 -- Autonomous Agent + Data Injection (5 min)

**Goal:** Show proactive monitoring and the data injection testing flow.

### Data Injection (2 min)

1. Click **Inject Anomaly** (in the Demo Tools section)
   - Watch for the green toast confirming the injected encounters
   - Wait 2-3 seconds for the health score to update (it should drop)

**Say:**
> "For demos, we can inject test data. These encounters have long LOS and are all readmissions. The batch size is configurable in Settings. Watch the health score respond."

2. **Click an alert tile** if one appears
   - This pre-fills a deep analysis query in the chat
   - "Notice how the dashboard and the agent are connected -- clicking an alert starts an investigation."

### Autonomous Mode (3 min)

3. Click **Auto Start**
   - Point out the countdown timer (e.g., "2h 0m")

**Say:**
> "The autonomous agent runs on a schedule -- it first performs a health check, and only if it detects issues does it generate a full recommended actions report. It auto-stops after 2 hours to prevent runaway resource usage."

4. **Click Check Health** to trigger an immediate check
   - "You don't have to wait for the schedule. This triggers a health check right now."

5. Wait for a recommended action to appear in the dashboard (or point to one if already there)

**Say:**
> "Every recommendation is SOP-grounded -- the agent searches your standard operating procedures before making suggestions, so you get actionable advice, not hallucinated generic tips."

6. Stop Autonomous mode (click **Stop**) to keep the demo clean.

---

## Wrap-Up (2 min)

### Architecture Talking Points

> "Everything runs on Databricks:"
> - **Unity Catalog** for data governance and table management
> - **Vector Search** for encounter similarity and SOP document retrieval
> - **Foundation Models** (Claude Sonnet for reasoning, GTE for embeddings) -- no external API keys
> - **MLflow** for agent tracing and observability
> - **Databricks Apps** for deployment -- this is a standard Flask + React app
> - **Asset Bundles** for reproducible deployment
> - **Lakebase** (optional) for transactional storage of agent outputs

### Closing

> "This is a solution accelerator -- a working starting point. The data model, agent prompts, and SOP documents are all customizable. A customer could adapt this to their specific hospitals, departments, and operating procedures in weeks, not months."

---

## Recovery Playbook

| Symptom | Fix |
|---------|-----|
| Health score shows `--/100` | Data tables may be empty. Click **Inject Good** a few times, then refresh the page. |
| Deep Analysis returns an error | Try a simpler question in Quick Query mode to verify connectivity, then retry. |
| Deep Analysis hangs with no stage updates | Wait up to 90 seconds. If still stuck, refresh and retry. The 5-minute timeout will surface an error. |
| Dashboard tiles show "No data" | Run `databricks bundle run generate_data -t dev` or click **Inject Good** to add test data. |
| Autonomous mode doesn't start | Check the Settings panel -- the interval may be set too high. Set to 1 minute for demos. |
| App returns 502/503 | The app may be restarting. Wait 30 seconds and refresh. Check Databricks Apps logs if it persists. |
