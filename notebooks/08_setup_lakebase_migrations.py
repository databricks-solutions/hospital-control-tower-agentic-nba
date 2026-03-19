# Databricks notebook source
# MAGIC %md
# MAGIC # Setup Lakebase Migrations
# MAGIC
# MAGIC Runs Alembic migrations to create tables in Lakebase PostgreSQL.
# MAGIC
# MAGIC **Prerequisites:**
# MAGIC - Lakebase instance created and running
# MAGIC - `LAKEBASE_HOST` configured in app environment variables

# COMMAND ----------

# MAGIC %pip install alembic psycopg2-binary sqlalchemy --quiet
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

import os
import sys

# Configuration
dbutils.widgets.text("var.catalog", "", "Catalog")
dbutils.widgets.text("var.schema", "med_logistics_nba", "Schema")
dbutils.widgets.text("var.lakebase_host", "", "Lakebase Host")
dbutils.widgets.text("var.lakebase_database", "postgres", "Lakebase Database")
CATALOG = dbutils.widgets.get("var.catalog")
SCHEMA = dbutils.widgets.get("var.schema")
LAKEBASE_HOST = dbutils.widgets.get("var.lakebase_host")
LAKEBASE_DATABASE = dbutils.widgets.get("var.lakebase_database")

if not LAKEBASE_HOST:
    raise ValueError("LAKEBASE_HOST must be configured. Set var.lakebase_host in variables.yml")

print(f"Lakebase Host: {LAKEBASE_HOST}")
print(f"Database: {LAKEBASE_DATABASE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Test Lakebase Connection

# COMMAND ----------

# Test connection
try:
    from databricks.sdk import WorkspaceClient
    import sqlalchemy
    from sqlalchemy import create_engine, text
    
    # Get OAuth token for Lakebase auth
    w = WorkspaceClient()
    token = w.dbutils.secrets.get(scope="oauth", key="token") if hasattr(w.dbutils, 'secrets') else w.api_client.do("GET", "/api/2.0/token/list")
    
    # Simple token from databricks
    import requests
    token_response = requests.get(
        f"https://{os.environ['DATABRICKS_HOST']}/api/2.0/token/create",
        headers={"Authorization": f"Bearer {os.environ['DATABRICKS_TOKEN']}"}
    )
    
    # Build connection URL
    lakebase_url = f"postgresql://token:{os.environ.get('DATABRICKS_TOKEN', 'placeholder')}@{LAKEBASE_HOST}:5432/{LAKEBASE_DATABASE}"
    
    engine = create_engine(lakebase_url)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        print("✓ Lakebase connection successful")
        
except Exception as e:
    print(f"✗ Lakebase connection failed: {e}")
    print("")
    print("Note: This is expected if:")
    print("  1. Lakebase instance is not created yet")
    print("  2. OAuth token refresh is not configured")
    print("  3. Service principal lacks Lakebase permissions")
    print("")
    print("The app will fall back to Unity Catalog automatically.")
    dbutils.notebook.exit("Lakebase not available - app will use Unity Catalog fallback")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Run Alembic Migrations

# COMMAND ----------

# Set up environment for Alembic
os.environ["LAKEBASE_URL"] = lakebase_url

# Add parent directory to path for imports
sys.path.insert(0, "/Workspace/Repos/.../medical_logistics_nba_app")  # Adjust to your repo path

# Run migrations
try:
    from alembic.config import Config
    from alembic import command
    
    # Configure Alembic
    alembic_cfg = Config("/Workspace/Repos/.../medical_logistics_nba_app/alembic.ini")  # Adjust path
    alembic_cfg.set_main_option("sqlalchemy.url", lakebase_url)
    
    # Run upgrade to head
    command.upgrade(alembic_cfg, "head")
    
    print("✓ Migrations completed successfully")
    print("")
    print("Created tables:")
    print("  - analysis_outputs (with sign-off fields)")
    
except Exception as e:
    print(f"✗ Migration failed: {e}")
    raise

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Verify Tables Created

# COMMAND ----------

with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public'
        ORDER BY table_name
    """))
    
    tables = [row[0] for row in result]
    print("Tables in Lakebase:")
    for table in tables:
        print(f"  - {table}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

print("=" * 60)
print("LAKEBASE SETUP COMPLETE")
print("=" * 60)
print("")
print("The app will now write analysis outputs to Lakebase PostgreSQL")
print("with automatic fallback to Unity Catalog if connection fails.")
print("")
print("Next: Deploy the app with Lakebase environment variables configured")
print("=" * 60)
