# Demo Quality Polish Roadmap

Target repo: `hospital-control-tower-agentic-nba`

---

## Phase 1: Domain Terminology Cleanup (High impact, low risk)

Leftover hospital-operations names that destroy domain credibility.

### 1A. Bundle name and seed data managers

- **`databricks.yml`**: Change `bundle.name` from `medical_logistics_nba_app` to `investment_intel_nba_app`
- **`app/api_server.py` line ~203-206**: Seed data uses real firm names (`"Blackstone Partners"`, `"KKR Capital"`, etc.). Replace with fictional but plausible names (e.g., `"Meridian Capital Partners"`, `"Northpoint Asset Management"`, `"Crestview Advisors"`, etc.)
- **`app/api_server.py` line ~224**: Hardcoded `2025` in `inception = (now - timedelta(days=365 * (2025 - vintage)))`. Change to `datetime.utcnow().year`

### 1B. cleanup.sh table list

- **`cleanup.sh` lines 63-73**: Drop-table list still references old hospital tables:
  - `dim_encounters`, `fact_drug_costs`, `fact_staffing`, `fact_ed_wait_times`, `fact_operational_kpis`, `encounters_for_embedding`, `sop_pdfs`, `sop_parsed`, `sop_chunks`
- Replace with actual investment tables:
  - `dim_funds`, `fact_fund_performance`, `fact_portfolio_holdings`, `fact_fund_flows`, `fact_portfolio_kpis`, `analysis_outputs`, `fund_documents_for_embedding`, `fund_documents_vector_index`, `investment_policy_docs`, `investment_policy_chunks`, `investment_policy_vector_index`

### 1C. API route names (backward-compatible approach)

- **`app/api_server.py`**: Routes still use `/api/encounters/*` naming (lines 1038-1144). Add investment-named aliases:
  - `/api/portfolio/summary` aliasing `/api/encounters/summary`
  - `/api/portfolio/by-manager` aliasing `/api/encounters/by-hospital`
  - `/api/portfolio/by-strategy` aliasing `/api/encounters/by-department`
  - `/api/portfolio/timeline` aliasing `/api/encounters/timeline`
  - `/api/portfolio/watchlist` aliasing `/api/encounters/readmissions`
- Rename SQL column aliases inside these functions:
  - `hospital` -> `manager`
  - `encounter_count` -> `fund_count`
  - `readmission_count` -> `watchlist_count`
  - `avg_los` -> `total_aum`
  - `readmissions` -> `avg_return`

### 1D. Frontend stale tool labels

- **`app/src/components/ConversationView.jsx`**: `TOOL_DESCRIPTIONS` (lines 36-54) still contains stale hospital tool names:
  - Remove: `search_encounters`, `analyze_cost_drivers`, `analyze_los_factors`, `check_ed_performance`, `check_staffing_efficiency`, `check_operational_kpis`
  - Keep only the investment equivalents: `search_fund_documents`, `search_investment_policies`, `analyze_performance_drivers`, `analyze_concentration`, `check_fund_flows`, `check_exposure_shifts`, `check_portfolio_kpis`, etc.

### 1E. DashboardPanel stale type labels

- **`app/src/components/DashboardPanel.jsx`** lines 107-118: `TYPE_LABELS` and `typeColors` still contain hospital terms:
  - Remove: `cost_monitoring`, `los_analysis`, `ed_performance`, `staffing_analysis`, `compliance_monitoring`
  - Replace with:
    - `performance_monitoring` -> "Performance Alert"
    - `concentration_analysis` -> "Concentration Risk"
    - `flow_analysis` -> "Capital Flow Alert"
    - `exposure_analysis` -> "Exposure Shift"
    - `policy_compliance` -> "Policy Compliance"
  - Keep existing investment entries (`performance_alert`, `concentration_risk`, `rebalance_suggestion`)

### 1F. Jobs parameter names

- **`resources/jobs.yml`** line 152: `"encounter_count": "10000"` -> `"fund_count": "10000"`
- Same file line 178: `"encounter_count": "200"` -> `"fund_count": "200"`
- Ensure `notebooks/00_generate_data.py` accepts `fund_count` as the parameter name (or both for backward compat)

### 1G. analysis_outputs DDL column name

- **`app/api_server.py` line 137**: Column named `encounter_id` with comment `'Related fund_id or entity ID'`. Rename column to `entity_id` in the DDL.
  - Non-breaking since it's `CREATE TABLE IF NOT EXISTS` and schema only matters on first creation.
  - Note: if table already exists in a deployed workspace, this change only takes effect after a `DROP TABLE` + recreate.

---

## Phase 2: Agent Architecture Fixes (High impact, moderate risk)

### 2A. Fix autonomous mode="rag" call

- **`app/agent/autonomous.py` line 273**: `invoke_agent(message=capability.prompt, mode="rag")`
- `"rag"` is the deep analysis path (multi-agent graph, 30-90s, expensive). Autonomous background checks should use `mode="quick"` instead.
- Deep analysis should only be triggered by explicit user requests.

### 2B. Fix clarify node dead end

- **`app/agent/graph.py`** lines 410-431 + 462: The `clarify` node sets `needs_clarification=True` and routes to `respond`, which returns the question to the user. The graph then hits `END`.
- Problem: the user's follow-up answer starts a brand-new graph invocation with no memory of the clarification context.
- Fix: Include the original question + clarification Q&A as conversation history when the user replies. The `clarify` node should format its output so the respond node includes context like "I previously asked you to clarify X, and you said Y."
- In `ConversationView.jsx`, when a clarification response is detected, prepend the prior clarification exchange to the history sent with the next message.

### 2C. Fix table allowlist regex for subqueries/CTEs

- **`app/agent/tools.py`** lines 51-62: `_check_table_allowlist` uses:
  ```python
  re.findall(r'\bfrom\s+(\w+)|\bjoin\s+(\w+)', q)
  ```
  This false-positives on subquery aliases and CTE names.
- Fix: After stripping known `CATALOG.SCHEMA.table` prefixes, also strip content inside parentheses (subqueries) before matching, and skip CTE names defined via `WITH ... AS`.

---

## Phase 3: UI/UX Fixes (Moderate impact, low risk)

### 3A. Make dashboard responsive

- **`app/src/components/DashboardPanel.jsx`** lines 359, 370: Fixed `w-[480px]` width.
- Change to responsive: `w-[480px] min-w-[320px] max-w-[520px]` with proper `flex-shrink` so the panel shrinks on smaller screens.
- Update loading skeleton (line 359) to match.

### 3B. Fix modal accessibility

- **`app/src/components/DemoGuide.jsx`** and **`app/src/components/DocsViewer.jsx`**:
  - Add `aria-modal="true"` and `role="dialog"` to modal container
  - Add keyboard `Escape` listener to close
  - Add click-on-backdrop to close

### 3C. Remove global `*` transition rule

- Check `app/src/tailwind.config.js` or any global CSS for a `* { transition: ... }` rule.
- If present, remove it (causes unintended layout animation on every DOM change).
- Replace with targeted transitions on interactive elements only.

### 3D. Auto-resize chat textarea

- **`app/src/components/ConversationView.jsx`**: The chat input should auto-grow with content.
- If currently a single-line `<input>`, convert to `<textarea>` with `rows={1}` and an `onInput` handler that adjusts `style.height` based on `scrollHeight`, capped at ~120px.

---

## Phase 4: React Code Quality (Lower demo risk, improves maintainability)

### 4A. Extract DashboardPanel sub-components

- **`app/src/components/DashboardPanel.jsx`** contains ~445 lines with 12+ inline component definitions.
- Extract tile components into `app/src/components/tiles/` subfolder:
  - `StatCard`, `FundPerformanceTile`, `CapitalFlowsTile`, `WatchlistFundItem`
  - `AlertTile`, `EmptyTile`, `AUMTrendTile`, `SectorExposureTile`
  - `ReturnsByStrategyTile`, `StrategyAllocationTile`, `PortfolioHealthTrendTile`
  - `CollapsibleSection`, `RecommendationItem`
- Main `DashboardPanel` imports from `./tiles/`.

### 4B. Fix stale closure in ConversationView

- **`app/src/components/ConversationView.jsx`** line ~331: `sendMessage` reads `messages` from closure state, but `messages` may be stale.
- The `history` variable captures `messages` at function definition time, not call time.
- Fix: Use a `useRef` to track latest messages (same pattern as `modeRef` already at line 260-261):
  ```jsx
  const messagesRef = useRef(messages)
  useEffect(() => { messagesRef.current = messages }, [messages])
  // then in sendMessage:
  const history = messagesRef.current.map(m => ({ role: m.role, content: m.content }))
  ```

### 4C. Header prop count reduction

- **`app/src/components/Header.jsx`** line 21: Takes 14 props.
- Consolidate into objects:
  - `demoActions = { onInjectAnomaly, onInjectGoodData, onResetData, onBackfillData }`
  - `navActions = { onOpenSettings, onOpenGuide, onOpenDocs }`
- Update `App.jsx` to pass these objects instead of individual props.

### 4D. Add error boundary

- Create `app/src/components/ErrorBoundary.jsx` -- a class component wrapping main `App` content.
- On catch, show a "Something went wrong" message with a reload button instead of a blank screen.
- Wrap in `App.jsx`:
  ```jsx
  <ErrorBoundary>
    <Header ... />
    <main>...</main>
  </ErrorBoundary>
  ```
