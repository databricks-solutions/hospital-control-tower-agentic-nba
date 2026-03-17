# Lakebase Setup for Investment Intelligence Platform

## Overview

The Investment Intelligence Platform app uses a hybrid data architecture:
- **Unity Catalog**: Analytical tables (funds, performance, holdings, KPIs) for read-heavy operations
- **Lakebase**: Application tables (analysis_outputs) for transactional writes

This separation provides:
- Real-time writes with ACID transactions (Lakebase)
- Efficient analytical queries (Unity Catalog)
- Automatic fallback to Unity Catalog if Lakebase unavailable

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                Investment Intelligence Platform              │
└──────────────┬──────────────────────────┬───────────────────┘
               │                          │
               │ Write                    │ Read
               ▼                          ▼
    ┌──────────────────┐      ┌─────────────────────────┐
    │   Lakebase PG    │      │   Unity Catalog         │
    │  (Transactional) │      │   (Analytical)          │
    ├──────────────────┤      ├─────────────────────────┤
    │ analysis_outputs │      │ dim_funds               │
    │   status         │      │ fact_performance        │
    │   priority       │      │ fact_holdings           │
    │   reviewed_by    │      │ fact_capital_flows      │
    │   reviewed_at    │      │ fact_operational_kpis   │
    └──────────────────┘      └─────────────────────────┘
          │ Fallback                     ▲
          └──────────────────────────────┘
            (if Lakebase unavailable)
```

## Prerequisites

1. Databricks workspace with Lakebase enabled
2. Lakebase instance created
3. Unity Catalog configured

## Configuration

### 1. Get Lakebase Connection Details

In Databricks UI:
1. Navigate to **Data** > **Databases**
2. Find your Lakebase instance
3. Click **Connection details**
4. Note the hostname

### 2. Update Environment Variables

Edit `app/app.yaml`:

```yaml
env:
  - name: CATALOG
    value: "your_catalog"
  - name: SCHEMA
    value: "your_schema"
  - name: LAKEBASE_HOST
    value: "your-lakebase-instance.cloud.databricks.com"
  - name: LAKEBASE_DATABASE
    value: "postgres"
  - name: DATABRICKS_WAREHOUSE_ID
    value: "your_warehouse_id"
```

### 3. Update Variables File

Edit `variables.yml`:

```yaml
variables:
  catalog:
    description: Unity Catalog name
    default: your_catalog
    
  schema:
    description: Schema name
    default: investment_intel
    
  lakebase_host:
    description: Lakebase hostname
    default: ""  # Fill in your Lakebase host
    
  lakebase_database:
    description: Lakebase database name
    default: "postgres"
```

## Database Migration

### Run Migrations

Create a notebook `notebooks/08_setup_lakebase_migrations.py`:

```python
# Install alembic if not present
%pip install alembic --quiet

# Set environment variables
import os
os.environ["LAKEBASE_HOST"] = "your-host.cloud.databricks.com"
os.environ["LAKEBASE_DATABASE"] = "postgres"

# Run migrations
from src.db import get_lakebase_url
from alembic.config import Config
from alembic import command

alembic_cfg = Config("alembic.ini")
alembic_cfg.set_main_option("sqlalchemy.url", get_lakebase_url())
command.upgrade(alembic_cfg, "head")

print("✓ Lakebase tables created successfully")
```

Run the notebook to create tables in Lakebase.

## Fallback Behavior

The app automatically handles Lakebase availability:

### Write Operations

```python
# Agent writes analysis
write_analysis(
    analysis_type="next_best_action_report",
    insights="Critical findings...",
    recommendations="Immediate actions...",
    priority="critical"
)
```

**Flow**:
1. **Try Lakebase**: Attempts SQLAlchemy insert to PostgreSQL
2. **Log Success**: `write_analysis: Saved to Lakebase - {id}`
3. **On Failure**: Falls back to Unity Catalog Delta table
4. **Log Fallback**: `write_analysis: Saved to Unity Catalog - {id}`

### Read Operations

API endpoints check both sources:

```python
# In api_server.py
try:
    # Try Lakebase first
    with session_scope() as session:
        results = session.query(AnalysisOutput).filter_by(status='pending').all()
except:
    # Fallback to Unity Catalog
    results = execute_uc_query("SELECT * FROM analysis_outputs WHERE status='pending'")
```

## Verification

### Check Lakebase Connection

```python
from src.db.connection import LakebaseConnection

conn = LakebaseConnection()
try:
    with conn.session_scope() as session:
        result = session.execute("SELECT 1")
        print("✓ Lakebase connection successful")
except Exception as e:
    print(f"✗ Lakebase connection failed: {e}")
```

### Verify Tables

```sql
-- In Lakebase
\dt

-- Should show:
-- analysis_outputs
```

## Troubleshooting

### Connection Fails

**Issue**: `LakebaseConnection` raises error

**Solutions**:
1. Verify `LAKEBASE_HOST` is correct
2. Check service principal has permissions
3. Ensure Lakebase instance is running
4. Verify OAuth token refresh is working

### Writes Not Appearing

**Issue**: Data written but not visible

**Solutions**:
1. Check which storage was used (log will show "lakebase" or "unity_catalog")
2. Query both sources to find data:
   ```sql
   -- Lakebase
   SELECT * FROM analysis_outputs ORDER BY created_at DESC LIMIT 5;
   
   -- Unity Catalog
   SELECT * FROM catalog.schema.analysis_outputs ORDER BY created_at DESC LIMIT 5;
   ```
3. Verify transaction committed (check logs for commit messages)

### Migration Errors

**Issue**: Alembic migration fails

**Solutions**:
1. Check current migration version:
   ```python
   alembic current
   ```
2. Manually create tables if needed:
   ```sql
   CREATE TABLE analysis_outputs (
       id VARCHAR(36) PRIMARY KEY,
       encounter_id VARCHAR(50),
       analysis_type VARCHAR(100) NOT NULL,
       insights TEXT NOT NULL,
       recommendations TEXT,
       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
       agent_mode VARCHAR(20) NOT NULL,
       metadata JSONB,
       status VARCHAR(20) DEFAULT 'pending',
       priority VARCHAR(20),
       reviewed_by VARCHAR(255),
       reviewed_at TIMESTAMP,
       engineer_notes TEXT
   );
   
   CREATE INDEX idx_analysis_status ON analysis_outputs(status);
   CREATE INDEX idx_analysis_priority ON analysis_outputs(priority);
   ```

## Performance Considerations

### When to Use Lakebase

**Use Lakebase for**:
- Real-time status updates (pending → approved)
- Concurrent writes from multiple agents
- ACID transaction requirements
- Row-level locking

**Use Unity Catalog for**:
- Read-heavy analytical queries
- Time-series data
- Batch data aggregations
- Historical analysis

### Optimization Tips

1. **Index Strategy**: Lakebase tables have indexes on `status` and `priority` for fast filtering
2. **Connection Pooling**: Connection pool size = 5 (default), adjust based on load
3. **Fallback Path**: Unity Catalog fallback adds ~100ms latency but ensures reliability
4. **Token Refresh**: OAuth tokens auto-refresh every 3600s

## Best Practices

1. **Always Check Logs**: Monitor which storage layer is being used
2. **Test Fallback**: Simulate Lakebase downtime to verify fallback works
3. **Monitor Performance**: Track write latencies (Lakebase ~50ms, UC ~200ms)
4. **Use Transactions**: Wrap related updates in SQLAlchemy transactions
5. **Handle Failures Gracefully**: App continues to work even if Lakebase unavailable

## References

- [Databricks Lakebase Documentation](https://docs.databricks.com/lakebase/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Alembic Migrations](https://alembic.sqlalchemy.org/)
