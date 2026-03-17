# Investment Intelligence Platform -- Quick Reference Card

Print this page or keep it open on a second screen during demos.

## Sample Questions

| Question | Mode | Expected Outcome |
|----------|------|------------------|
| "What's the average performance at Manager A?" | Quick | Specific number + context in 2-5s |
| "Compare fund performance across managers" | Quick | Table of performance by manager |
| "Why did fund performance spike in November for Manager A?" | Deep | Multi-step investigation with IPS citations (30-60s) |
| "What specific actions can I take to reduce concentration in Manager A?" | Deep | Prioritized recommendations tied to IPS |
| "Why is performance lower for funds rebalanced on Mondays?" | Deep | Day-of-week rebalance pattern analysis |
| "How can I improve capital flow efficiency?" | Deep | Flow performance analysis + exposure recommendations |
| "How can I reduce exposure concentration in the growth strategy?" | Deep | Holdings mix analysis + rebalancing ROI |

## Dashboard Tiles

| Tile | What It Shows | Red Flag |
|------|--------------|----------|
| **Investments** | Total fund investments (30 days) | Sudden drop or spike |
| **Avg Performance** | Average performance metric | Below target |
| **Watchlist Rate** | 30-day watchlist/underperformance percentage | > 10% |
| **30-Day Volume** | Daily investment + watchlist bar chart | Red bars = watchlist items |
| **Capital Flows by Type** | Flow metrics per category | Red bars = threshold breaches |
| **Fund Performance** | Total performance + top categories | Large single-category dominance |
| **Exposure Concentration** | % concentrated holdings by strategy | > 25% in any strategy |
| **Active Alerts** | Auto-detected portfolio issues | Click to investigate in chat |
| **Recent Watchlist** | Latest watchlist/underperforming investments | High concentration (red tag) or low performance (amber) |
| **Recommended Actions** | AI-generated action items | Signed off or pending |

## Header Controls

| Control | What It Does |
|---------|-------------|
| **Quick Query / Deep Analysis** | Toggle agent mode. Quick = 2-5s lookups. Deep = 30-90s multi-agent investigation. |
| **Score: XX/100** | Composite portfolio score (40% performance + 30% watchlist + 30% flow breaches). Hover for breakdown. |
| **Check Health** | Triggers a one-shot health check immediately. |
| **Inject Good** | Adds healthy investments (strong performance, no watchlist). Batch size configurable in Settings. |
| **Inject Anomaly** | Adds anomalous investments (underperformance, all watchlist) plus correlated data across all tables. Batch size configurable in Settings. |
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
| Portfolio score shows `--/100` | Click **Inject Good** a few times, wait 5 seconds |
| "No timeline data" | Data tables are empty -- run `generate_data` job or inject data |
| Deep Analysis error / HTML response | Network timeout -- try a simpler question first, then retry |
| Autonomous mode won't start | Open Settings, set interval to 1 minute |
| App returns 502 | Wait 30 seconds and refresh (app may be restarting) |
| Toast says "injection failed" | SQL Warehouse may be stopped -- check Databricks workspace |
