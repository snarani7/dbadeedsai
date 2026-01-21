# Copyright (c) 2024 Sandeep Reddy Narani
#
# All rights reserved.
#
# This software and associated documentation files (the "Software") are the 
# property of Sandeep Reddy Narani and are protected by copyright laws and 
# international copyright treaties.
#
# dbadeeds.com
#
# The Software is provided for use in accordance with the terms of the MIT License.
# See LICENSE file for full license terms.
#
# For inquiries, please contact:
# Owner: Sandeep Reddy Narani
# Website: dbadeeds.com
### Jan 2026 Version v1
## 
import streamlit as st
import pandas as pd
import subprocess
import oracledb
import os


from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
from langchain_openai import ChatOpenAI
from langchain.agents import initialize_agent, Tool, AgentType
##from pages.database_overview import render_database_overview
# ---------------------------------------------------------
# PAGE CONFIG
# ---------------------------------------------------------
st.set_page_config(page_title="dbadeeds.ai", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stSidebar { background-color: #ffffff; border-right: 1px solid #e0e0e0; }
    </style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# BACKEND: BUDDY SHELL TOOL
# ---------------------------------------------------------
def run_buddy(cmd, *args):
    script = "/dbadeeeds/script/oradbabuddy.sh"
    full_cmd = ["bash", script, cmd] + list(args)
    try:
        res = subprocess.check_output(full_cmd, stderr=subprocess.STDOUT).decode()
        return res
    except Exception as e:
        return f"Error executing command: {str(e)}"

# ---------------------------------------------------------
# ORACLE CONNECTION POOL (THIN MODE)
# ---------------------------------------------------------
@st.cache_resource
def get_oracle_pool():
    return oracledb.create_pool(
        user="system",
        password="oracle",
        dsn="192.168.86.244:1521/freepdb1",
        min=1,
        max=5,
        increment=1
    )

def run_oracle_query(sql: str):
    pool = get_oracle_pool()
    try:
        with pool.acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)

                if cur.description:  # SELECT
                    cols = [c[0] for c in cur.description]
                    rows = cur.fetchall()
                    return pd.DataFrame(rows, columns=cols)
                else:  # DML
                    conn.commit()
                    return "Query executed successfully."
    except Exception as e:
        return f"Oracle Error: {str(e)}"

def run_sql_file(name: str):
    path = os.path.join("sql", f"{name}.sql")
    if not os.path.exists(path):
        return f"SQL file not found: {path}"

    try:
        with open(path, "r") as f:
            sql = f.read()
    except Exception as e:
        return f"Error reading SQL file {path}: {e}"

    return run_oracle_query(sql)
# ---------------------------------------------------------
# AI AGENT SETUP
# ---------------------------------------------------------
llm = ChatOpenAI(
    model="gpt-4o",
    #model="gemini-2.5-flash",
    temperature=0,
    openai_api_key=""
    #openai_api_key="",
    #base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
)

tools = [
    Tool(
        name="QueryBuddy",
        func=lambda q: run_buddy("query", q),
        description="Run SQL via buddy"
    ),
    Tool(
        name="GetForm",
        func=lambda q: run_buddy("get_form_name", q),
        description="Find form by ID"
    ),
    Tool(
        name="OracleQuery",
        func=lambda q: (
            run_oracle_query(q).to_string()
            if isinstance(run_oracle_query(q), pd.DataFrame)
            else run_oracle_query(q)
        ),
        description="Run SQL directly on Oracle using python-oracledb"
    )
]

agent = initialize_agent(
    tools,
    llm,
    agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
    verbose=False
)

# ---------------------------------------------------------
# SIDEBAR NAVIGATION
# ---------------------------------------------------------
with st.sidebar:
    st.title("📂 dbadeeds.ai")
    st.sidebar.caption("DATABASE NAVIGATION")

    app_mode = st.radio("Go to", ["Dashboard", "Database Explorer", "AI Assistant", "AskOEM", "DBA Playbooks"])

    st.info(f"**Welcome to dbadeeds.ai**")
    st.info(f"This is a tool that helps to navigate and manage your Oracle database using AI.")

# ---------------------------------------------------------
# APP MODES
# ---------------------------------------------------------

# ---------------------- DASHBOARD ------------------------
if app_mode == "Dashboard":
    ##st.header("🚀 dbadeeds.ai Overview")
    st.header("🚀 dbaAI Overview")
    st.markdown("""
    <div style="padding: 2rem 0;">
        <h1 style="font-size: 2.4rem; font-weight: 700;">
            AI Database Agent for Oracle
        </h1>
        <p style="font-size: 1.1rem; color: #555; max-width: 900px;">
            Designed for Support Desk teams during alerts and incidents, <b>dbadeeds.ai</b> is an autonomous AI DBA assistant that understands your 
            Oracle environment, performs diagnostics, executes operational playbooks, and answers database-related questions in real time — safely and intelligently.
        </p>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("""
    <div style="margin-top: 3rem;">
        <h3>How dbadeeds.ai Works</h3>
        <ol style="font-size: 1rem; color:#444;">
            <li><b>Connect</b> – Securely connect to your Oracle database (PDB / CDB).</li>
            <li><b>Observe</b> – Collect metadata, performance signals, and runtime stats.</li>
            <li><b>Reason</b> – AI agent understands context using DBA logic.</li>
            <li><b>Act</b> – Executes safe SQL or playbooks, or guides the DBA with insights.</li>
        </ol>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("""
    <div style="margin-top: 2rem; padding: 1.5rem; background: #f1f5f9; border-radius: 12px;">
        <h4>Why DBAs Use dbadeeds.ai</h4>
        <ul style="color:#444;">
            <li>⚙️ Reduce MTTR during production incidents</li>
            <li>📊 Eliminate repetitive health-check SQLs</li>
            <li>🧠 Augment junior DBAs with senior-level intelligence</li>
            <li>🚨 Catch problems before users feel them</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)


    col1, col2, col3 = st.columns(3)
    col1.metric("Active Sessions", "14", "+2")
    col2.metric("Long Running Queries", "3", "-1")
    col3.metric("DB Health", "Optimal")

    st.subheader("Copyright 2005-26 dbadeeds.ai")
   ## st.code(run_buddy("application_lrq"))

# ---------------------- DATABASE EXPLORER ----------------
elif app_mode == "Database Explorer":
    st.header("🔌 Oracle Database Connection")

    # -----------------------------------------------------
    # MODE SWITCH: Testing vs Dynamic
    # -----------------------------------------------------
    if "testing_mode" not in st.session_state:
        st.session_state.testing_mode = True  # default ON

    st.session_state.testing_mode = st.checkbox(
        "Use hard‑coded test connection (hr/oracle)",
        value=st.session_state.testing_mode
    )

    # -----------------------------------------------------
    # TESTING MODE (hard-coded)
    # -----------------------------------------------------
    TEST_USER = "hr"
    TEST_PASS = "oracle"
    TEST_DSN = "192.168.86.244:1521/freepdb1"

    # -----------------------------------------------------
    # DYNAMIC MODE (user input)
    # -----------------------------------------------------
    if "db_host" not in st.session_state:
        st.session_state.db_host = ""
    if "db_port" not in st.session_state:
        st.session_state.db_port = ""
    if "db_service" not in st.session_state:
        st.session_state.db_service = ""
    if "db_user" not in st.session_state:
        st.session_state.db_user = ""
    if "db_pass" not in st.session_state:
        st.session_state.db_pass = ""

    col1, col2 = st.columns(2)

    with col1:
        st.session_state.db_host = st.text_input(
            "Hostname",
            st.session_state.db_host,
            disabled=st.session_state.testing_mode
        )
        st.session_state.db_port = st.text_input(
            "Port",
            st.session_state.db_port,
            disabled=st.session_state.testing_mode
        )
        st.session_state.db_service = st.text_input(
            "Service Name",
            st.session_state.db_service,
            disabled=st.session_state.testing_mode
        )

    with col2:
        st.session_state.db_user = st.text_input(
            "Username",
            st.session_state.db_user,
            disabled=st.session_state.testing_mode
        )
        st.session_state.db_pass = st.text_input(
            "Password",
            st.session_state.db_pass,
            type="password",
            disabled=st.session_state.testing_mode
        )

    # Build DSN dynamically
    dynamic_dsn = (
        f"{st.session_state.db_host}:"
        f"{st.session_state.db_port}/"
        f"{st.session_state.db_service}"
    )

    st.markdown("---")
    st.subheader("Test Connection")

    if st.button("Connect to Database"):
        try:
            if st.session_state.testing_mode:
                conn = oracledb.connect(
                    user=TEST_USER,
                    password=TEST_PASS,
                    dsn=TEST_DSN
                )
            else:
                conn = oracledb.connect(
                    user=st.session_state.db_user,
                    password=st.session_state.db_pass,
                    dsn=dynamic_dsn
                )

            with conn.cursor() as cur:
                cur.execute("SELECT 'Connection Successful' FROM dual")
                st.success(cur.fetchone()[0])

        except Exception as e:
            st.error(f"Connection failed: {e}")

    st.markdown("---")
    st.subheader("Run SQL Query")

    sql = st.text_area("Enter SQL", "SELECT * FROM dual")

    if st.button("Execute SQL"):
        try:
            if st.session_state.testing_mode:
                conn = oracledb.connect(
                    user=TEST_USER,
                    password=TEST_PASS,
                    dsn=TEST_DSN
                )
            else:
                conn = oracledb.connect(
                    user=st.session_state.db_user,
                    password=st.session_state.db_pass,
                    dsn=dynamic_dsn
                )

            with conn.cursor() as cur:
                cur.execute(sql)

                if cur.description:
                    cols = [c[0] for c in cur.description]
                    rows = cur.fetchall()
                    df = pd.DataFrame(rows, columns=cols)
                    st.dataframe(df)
                else:
                    conn.commit()
                    st.success("Query executed successfully.")

        except Exception as e:
            st.error(f"Oracle Error: {e}")

# ---------------------- AI ASSISTANT ---------------------
elif app_mode == "AI Assistant":
    st.header("🤖 Ask DeedsAI")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Ex: Show me long running queries for the last hour"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            response = agent.run(prompt)
            st.markdown(response)
            st.session_state.messages.append({"role": "assistant", "content": response})

# ---------------------- DBA PLAYBOOKS --------------------
elif app_mode == "DBA Playbooks":
    st.header("⚙️ DBA Playbooks")

    # --- PDB STATUS ---
    if st.button("Check PDB Status"):
        result = run_sql_file("pdb_status")   # reads sql/pdb_status.sql

        if isinstance(result, pd.DataFrame):
            st.subheader("PDB Status")
            st.dataframe(result)
        else:
            st.error(result)

    st.markdown("---")
    st.subheader("Choose a Playbook to Run")

    playbooks = {
        "1) Long Running SQLs": "long_running_sqls",
        "2) SQL Monitoring": "sql_monitoring",
        "3) Blocking Sessions": "blocking_sessions",
        "4) Find Blocking SQL Text": "find_blocking_sql_text",
        "5) Invalid Objects": "invalid_objects",
        "6) Unusable Indexes": "unusable_indexes",
        "7) Failed Jobs": "failed_jobs",
        "8) Datapump Jobs": "datapump_jobs",
        "9) Sessions per Machine": "sessions_per_machine",
        "10) Application Long Running Queries": "application_lrq",
        "11) Database Size": "db_size",
        "12) Tablespace Usage High": "tablespace_usage_high",
        "13) FRA Usage (DBA)": "fra_usage_dba",
        "14) SGA/PGA Advisor": "sga_pga_advisor",
        "15) Check Profile Idle": "check_profile_idle",
        "16) Check Triggers": "check_triggers",
    }

    choice_label = st.selectbox(
        "Prebuilt DBA Playbooks",
        list(playbooks.keys())
    )

    if st.button("Run Selected Playbook"):
        key = playbooks[choice_label]
        result = run_sql_file(key)   # reads sql/<key>.sql

        if isinstance(result, pd.DataFrame):
            st.subheader(f"Results: {choice_label}")
            st.dataframe(result)
        else:
            if isinstance(result, str) and result.lower().startswith("oracle error"):
                st.error(result)
            elif isinstance(result, str) and result.lower().startswith("sql file not found"):
                st.error(result)
            else:
                st.success(result)