# Hospital Control Tower -- Quick Reference Card

Print this page or keep it open on a second screen during demos.

## Sample Questions

| Question | Mode | Expected Outcome |
|----------|------|------------------|
| "What's the average LOS at Hospital A?" | Quick | Specific number + context in 2-5s |
| "Compare drug costs across hospitals" | Quick | Table of costs by hospital |
| "Why did drug costs spike in November for Hospital A?" | Deep | Multi-step investigation with SOP citations (30-60s) |
| "What specific actions can I take to reduce LOS in Hospital A?" | Deep | Prioritized recommendations tied to SOPs |
| "Why is LOS higher for patients discharged on Mondays?" | Deep | Day-of-week discharge pattern analysis |
| "How can I reduce wait times in the Emergency Department?" | Deep | ED performance analysis + staffing recommendations |
| "How can I lower contract labor in the Cardiology department?" | Deep | Staffing mix analysis + recruitment ROI |

## Dashboard Tiles

| Tile | What It Shows | Red Flag |
|------|--------------|----------|
| **Encounters** | Total patient encounters (30 days) | Sudden drop or spike |
| **Avg LOS** | Average length of stay in days | > 5 days |
| **Readmit Rate** | 30-day readmission percentage | > 10% |
| **30-Day Volume** | Daily encounter + readmission bar chart | Red bars = readmissions |
| **ED Wait by Acuity** | Wait time per triage level | Red bars = threshold breaches |
| **Drug Costs** | Total pharmacy spend + top categories | Large single-category dominance |
| **Contract Labor** | % contract staff by department | > 25% in any department |
| **Active Alerts** | Auto-detected operational issues | Click to investigate in chat |
| **Recent Readmissions** | Latest readmitted patients | High LOS (red tag) or high drug cost (amber) |
| **Recommended Actions** | AI-generated action items | Signed off or pending |

## Header Controls

| Control | What It Does |
|---------|-------------|
| **Quick Query / Deep Analysis** | Toggle agent mode. Quick = 2-5s lookups. Deep = 30-90s multi-agent investigation. |
| **Health: XX/100** | Composite score (40% LOS + 30% readmit + 30% ED breaches). Hover for breakdown. |
| **Check Health** | Triggers a one-shot health check immediately. |
| **Inject Good** | Adds healthy encounters (short LOS, no readmissions). Batch size configurable in Settings. |
| **Inject Anomaly** | Adds anomalous encounters (long LOS, all readmissions) plus correlated data across all tables. Batch size configurable in Settings. |
| **Auto Start/Stop** | Start or stop the autonomous monitoring agent. Auto-stops after 2 hours. |
| **Settings** | Configure autonomous mode interval and capabilities. |

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Enter | Send message |
| Shift+Enter | New line in message |

## Troubleshooting

| Symptom | Quick Fix |
|---------|-----------|
| Health score shows `--/100` | Click **Inject Good** a few times, wait 5 seconds |
| "No timeline data" | Data tables are empty -- run `generate_data` job or inject data |
| Deep Analysis error / HTML response | Network timeout -- try a simpler question first, then retry |
| Autonomous mode won't start | Open Settings, set interval to 1 minute |
| App returns 502 | Wait 30 seconds and refresh (app may be restarting) |
| Toast says "injection failed" | SQL Warehouse may be stopped -- check Databricks workspace |
