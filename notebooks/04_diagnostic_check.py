# Databricks notebook source
# MAGIC %md
# MAGIC # Diagnostic Check for Investment Portfolio Intelligence
# MAGIC Tests tables, permissions, tools, and LLM endpoints.

# COMMAND ----------

# MAGIC %pip install databricks-langchain langgraph langchain-core databricks-vectorsearch -q

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# Configuration -- reads from bundle variables (var.*) when run via DAB jobs
dbutils.widgets.text("var.catalog", "", "Catalog")
dbutils.widgets.text("var.schema", "investment_intel", "Schema")
dbutils.widgets.text("var.app_name", "dev-hospital-control-tower", "App Name")
dbutils.widgets.text("var.warehouse_id", "", "Warehouse ID")
dbutils.widgets.text("var.llm_model_rag", "databricks-claude-sonnet-4-5", "LLM Endpoint")

CATALOG = spark.conf.get("spark.databricks.workflow.parameters.var.catalog", dbutils.widgets.get("var.catalog"))
SCHEMA = spark.conf.get("spark.databricks.workflow.parameters.var.schema", dbutils.widgets.get("var.schema"))
APP_NAME = spark.conf.get("spark.databricks.workflow.parameters.var.app_name", dbutils.widgets.get("var.app_name"))
WAREHOUSE_ID = spark.conf.get("spark.databricks.workflow.parameters.var.warehouse_id", dbutils.widgets.get("var.warehouse_id"))
LLM_ENDPOINT = spark.conf.get("spark.databricks.workflow.parameters.var.llm_model_rag", dbutils.widgets.get("var.llm_model_rag"))

print(f"Catalog: {CATALOG}")
print(f"Schema: {SCHEMA}")
print(f"App: {APP_NAME}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Check Table Existence

# COMMAND ----------

spark.sql(f"USE CATALOG {CATALOG}")

tables_to_check = [
    f"{SCHEMA}.dim_funds",
    f"{SCHEMA}.analysis_outputs", 
    f"{SCHEMA}.fund_documents_for_embedding",
]

print("Table Existence Check:")
print("=" * 60)
for table in tables_to_check:
    try:
        count = spark.sql(f"SELECT COUNT(*) FROM {table}").collect()[0][0]
        print(f"  {table}: EXISTS ({count} rows)")
    except Exception as e:
        print(f"  {table}: NOT FOUND - {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Check Table Permissions (as current user)

# COMMAND ----------

print("\nPermissions Check (current user):")
print("=" * 60)

# Test SELECT on dim_funds
try:
    df = spark.sql(f"SELECT * FROM {SCHEMA}.dim_funds LIMIT 1")
    df.collect()
    print(f"  SELECT on dim_funds: OK")
except Exception as e:
    print(f"  SELECT on dim_funds: FAILED - {e}")

# Test SELECT on analysis_outputs
try:
    df = spark.sql(f"SELECT * FROM {SCHEMA}.analysis_outputs LIMIT 1")
    df.collect()
    print(f"  SELECT on analysis_outputs: OK")
except Exception as e:
    print(f"  SELECT on analysis_outputs: FAILED - {e}")

# Test INSERT on analysis_outputs
try:
    spark.sql(f"""
        INSERT INTO {SCHEMA}.analysis_outputs 
        (id, analysis_type, insights, agent_mode)
        VALUES ('test-diagnostic', 'test', 'diagnostic test', 'test')
    """)
    spark.sql(f"DELETE FROM {SCHEMA}.analysis_outputs WHERE id = 'test-diagnostic'")
    print(f"  INSERT/DELETE on analysis_outputs: OK")
except Exception as e:
    print(f"  INSERT/DELETE on analysis_outputs: FAILED - {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Check Vector Search

# COMMAND ----------

from databricks.vector_search.client import VectorSearchClient

dbutils.widgets.text("var.vector_search_endpoint", "", "Vector Search Endpoint")
ENDPOINT_NAME = dbutils.widgets.get("var.vector_search_endpoint")
INDEX_NAME = f"{CATALOG}.{SCHEMA}.fund_documents_vector_index"

print(f"\nVector Search Check:")
print("=" * 60)
print(f"  Endpoint: {ENDPOINT_NAME}")
print(f"  Index: {INDEX_NAME}")

vsc = VectorSearchClient()

try:
    endpoint = vsc.get_endpoint(ENDPOINT_NAME)
    status = endpoint.get("endpoint_status", {}).get("state", "UNKNOWN")
    print(f"  Endpoint status: {status}")
except Exception as e:
    print(f"  Endpoint check failed: {e}")

try:
    index = vsc.get_index(endpoint_name=ENDPOINT_NAME, index_name=INDEX_NAME)
    print(f"  Index exists: YES")
    
    # Test search
    results = index.similarity_search(
        query_text="fund performance and portfolio holdings",
        columns=["fund_id", "text_content"],
        num_results=1,
    )
    print(f"  Search test: OK (found {len(results.get('result', {}).get('data_array', []))} results)")
except Exception as e:
    print(f"  Index check failed: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Check LLM Endpoint

# COMMAND ----------

from databricks_langchain import ChatDatabricks
from langchain_core.messages import HumanMessage

print(f"\nLLM Endpoint Check:")
print("=" * 60)
print(f"  Endpoint: {LLM_ENDPOINT}")

try:
    llm = ChatDatabricks(endpoint=LLM_ENDPOINT)
    response = llm.invoke([HumanMessage(content="Say 'hello' in one word")])
    print(f"  Basic invoke: OK - '{response.content[:50]}...'")
except Exception as e:
    print(f"  Basic invoke: FAILED - {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Check Tool Binding with ChatDatabricks

# COMMAND ----------

from langchain_core.tools import tool
from typing import Optional

@tool
def test_tool(query: str) -> str:
    """A test tool that echoes the query."""
    return f"Echo: {query}"

print(f"\nTool Binding Check:")
print("=" * 60)

try:
    llm = ChatDatabricks(endpoint=LLM_ENDPOINT)
    llm_with_tools = llm.bind_tools([test_tool])
    print(f"  bind_tools: OK")
    
    # Test invocation with tools
    response = llm_with_tools.invoke([HumanMessage(content="Use the test_tool to echo 'hello'")])
    print(f"  Invoke with tools: OK")
    
    if hasattr(response, 'tool_calls') and response.tool_calls:
        print(f"  Tool calls in response: {len(response.tool_calls)}")
        for tc in response.tool_calls:
            print(f"    - {tc}")
    else:
        print(f"  Tool calls in response: None (model didn't call tools)")
        print(f"  Response: {response.content[:100]}...")
except Exception as e:
    print(f"  Tool binding FAILED: {e}")
    import traceback
    traceback.print_exc()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Check LangGraph create_react_agent

# COMMAND ----------

from langgraph.prebuilt import create_react_agent

print(f"\nLangGraph create_react_agent Check:")
print("=" * 60)

try:
    llm = ChatDatabricks(endpoint=LLM_ENDPOINT)
    agent = create_react_agent(llm, [test_tool])
    print(f"  create_react_agent: OK")
    
    # Test invocation
    result = agent.invoke({"messages": [HumanMessage(content="Use test_tool to echo 'diagnostic test'")]})
    print(f"  Agent invoke: OK")
    print(f"  Messages in result: {len(result['messages'])}")
    
    # Show last message
    last_msg = result['messages'][-1]
    print(f"  Last message type: {type(last_msg).__name__}")
    print(f"  Last message content: {last_msg.content[:200] if last_msg.content else 'None'}...")
except Exception as e:
    print(f"  create_react_agent FAILED: {e}")
    import traceback
    traceback.print_exc()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Check SQL Execution via Statement Execution API

# COMMAND ----------

from databricks.sdk import WorkspaceClient

print(f"\nStatement Execution API Check:")
print("=" * 60)
print(f"  Warehouse: {WAREHOUSE_ID}")

w = WorkspaceClient()

try:
    result = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID,
        statement=f"SELECT COUNT(*) as cnt FROM {CATALOG}.{SCHEMA}.dim_funds",
        wait_timeout="30s",
    )
    
    if result.status.state.value == "SUCCEEDED":
        count = result.result.data_array[0][0] if result.result.data_array else 0
        print(f"  Query execution: OK")
        print(f"  Row count from dim_funds: {count}")
    else:
        print(f"  Query execution: FAILED - {result.status.error}")
except Exception as e:
    print(f"  Statement execution FAILED: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Check App Service Principal Permissions

# COMMAND ----------

print(f"\nService Principal Check:")
print("=" * 60)
print(f"  App name: {APP_NAME}")

try:
    sps = list(w.service_principals.list(filter=f"displayName eq '{APP_NAME}'"))
    if sps:
        sp = sps[0]
        print(f"  Service principal found: {sp.display_name} (ID: {sp.id})")
    else:
        print(f"  Service principal NOT FOUND")
        print(f"  Note: The app may not be deployed yet, or the SP name differs.")
except Exception as e:
    print(f"  SP lookup failed: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

print("=" * 60)
print("DIAGNOSTIC SUMMARY")
print("=" * 60)
print("""
Run this notebook to check:
1. Table existence - Ensure dim_funds and analysis_outputs exist
2. Permissions - Verify current user can SELECT/INSERT
3. Vector Search - Endpoint and index are ready
4. LLM Endpoint - ChatDatabricks works
5. Tool Binding - ChatDatabricks.bind_tools works
6. LangGraph - create_react_agent works
7. SQL Execution - Statement Execution API works
8. Service Principal - App SP exists

If any check fails, fix that component before testing the app.
""")
