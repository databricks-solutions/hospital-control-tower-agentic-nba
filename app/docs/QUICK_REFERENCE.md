# Investment Intelligence Platform -- Quick Reference Card

Print this page or keep it open on a second screen during demos.

## Sample Questions

| Question | Mode | Expected Outcome |
|----------|------|------------------|
| "What's the average holding period at Fund A?" | Quick | Specific number + context in 2-5s |
| "Compare fund performance across funds" | Quick | Table of performance by fund |
| "Why did fund performance spike in November for Fund A?" | Deep | Multi-step investigation with IPS/investment policy citations (30-60s) |
| "What specific actions can I take to improve fund performance in Fund A?" | Deep | Prioritized recommendations tied to IPS/investment policies |
| "Why is holding period higher for funds redeemed on Mondays?" | Deep | Day-of-week redemption pattern analysis |
| "How can I improve capital flows?" | Deep | Capital flows analysis + portfolio holdings recommendations |
| "How can I optimize portfolio holdings in the Growth strategy?" | Deep | Portfolio holdings mix analysis + allocation ROI |

## Dashboard Tiles

| Tile | What It Shows | Red Flag |
|------|--------------|----------|
| **Funds** | Total fund investments (30 days) | Sudden drop or spike |
| **Avg Holding Period** | Average holding period in days | > 5 days |
| **Watchlist Rate** | 30-day watchlist percentage | > 10% |
| **30-Day Volume** | Daily fund + watchlist bar chart | Red bars = watchlist |
| **Capital Flows by Tier** | Capital flow time per priority level | Red bars = threshold breaches |
| **Fund Performance** | Total fund performance + top categories | Large single-category dominance |
| **Portfolio Holdings** | % portfolio holdings by strategy | > 25% in any strategy |
| **Active Alerts** | Auto-detected operational issues | Click to investigate in chat |
| **Recent Watchlist** | Latest watchlisted funds | Long holding period (red tag) or high fund cost (amber) |
| **Recommended Actions** | AI-generated action items | Signed off or pending |

## Header Controls

| Control | What It Does |
|---------|-------------|
| **Quick Query / Deep Analysis** | Toggle agent mode. Quick = 2-5s lookups. Deep = 30-90s multi-agent investigation. |
| **Performance: XX/100** | Composite score (40% holding period + 30% watchlist + 30% capital flow breaches). Hover for breakdown. |
| **Check Performance** | Triggers a one-shot performance check immediately. |
| **Inject Good** | Adds high-performing fund investments (short holding period, no watchlist). Batch size configurable in Settings. |
| **Inject Anomaly** | Adds anomalous fund investments (long holding period, all watchlisted) plus correlated data across all tables. Batch size configurable in Settings. |
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
| Performance score shows `--/100` | Click **Inject Good** a few times, wait 5 seconds |
| "No timeline data" | Data tables are empty -- run `generate_data` job or inject data |
| Deep Analysis error / HTML response | Network timeout -- try a simpler question first, then retry |
| Autonomous mode won't start | Open Settings, set interval to 1 minute |
| App returns 502 | Wait 30 seconds and refresh (app may be restarting) |
| Toast says "injection failed" | SQL Warehouse may be stopped -- check Databricks workspace |
