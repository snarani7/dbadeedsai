#!/usr/bin/env python3
# Author: Sandeep Reddy Narani

"""
AI Agent Manager for dbadeeds.ai
Manages specialized AI agents for Oracle and PostgreSQL databases
"""

import json
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum


class AgentType(Enum):
    """Types of AI agents"""
    PERFORMANCE_MONITOR = "performance_monitor"
    TROUBLESHOOTER = "troubleshooter"
    QUERY_OPTIMIZER = "query_optimizer"
    SECURITY_AUDITOR = "security_auditor"
    CAPACITY_PLANNER = "capacity_planner"
    BACKUP_MONITOR = "backup_monitor"
    CUSTOM = "custom"


class DatabaseType(Enum):
    """Supported database types"""
    ORACLE = "oracle"
    POSTGRESQL = "postgresql"


@dataclass
class AgentConfig:
    """Configuration for an AI agent"""
    name: str
    agent_type: AgentType
    database_type: DatabaseType
    description: str
    system_prompt: str
    tools: List[str]
    temperature: float = 0.0
    model: str = "gpt-4o"
    max_iterations: int = 10
    created_at: str = None
    updated_at: str = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
        if self.updated_at is None:
            self.updated_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        data['agent_type'] = self.agent_type.value
        data['database_type'] = self.database_type.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AgentConfig':
        """Create from dictionary"""
        data['agent_type'] = AgentType(data['agent_type'])
        data['database_type'] = DatabaseType(data['database_type'])
        return cls(**data)


class AgentTemplates:
    """Pre-built agent templates for different use cases"""
    
    ORACLE_PERFORMANCE_MONITOR = AgentConfig(
        name="Oracle Performance Monitor",
        agent_type=AgentType.PERFORMANCE_MONITOR,
        database_type=DatabaseType.ORACLE,
        description="Monitors Oracle database performance metrics, identifies bottlenecks, and provides optimization recommendations.",
        system_prompt="""You are an expert Oracle DBA specializing in performance monitoring.

Your responsibilities:
- Monitor database performance metrics (CPU, memory, I/O)
- Identify slow-running queries and suggest optimizations
- Analyze AWR/ASH reports
- Check for blocking sessions and locks
- Monitor tablespace usage and alert on capacity issues
- Review execution plans and suggest index improvements

Always provide:
1. Clear diagnosis of performance issues
2. Specific SQL or configuration recommendations
3. Expected impact of changes
4. Risk assessment for proposed changes

Use Oracle-specific tools and queries to gather performance data.""",
        tools=["OracleQuery", "QueryBuddy"],
        temperature=0.0
    )
    
    POSTGRESQL_PERFORMANCE_MONITOR = AgentConfig(
        name="PostgreSQL Performance Monitor",
        agent_type=AgentType.PERFORMANCE_MONITOR,
        database_type=DatabaseType.POSTGRESQL,
        description="Monitors PostgreSQL database performance, analyzes query execution, and provides tuning recommendations.",
        system_prompt="""You are an expert PostgreSQL DBA specializing in performance monitoring.

Your responsibilities:
- Monitor database performance using pg_stat_* views
- Identify slow queries using pg_stat_statements
- Analyze EXPLAIN plans and suggest optimizations
- Check for blocking queries and lock contention
- Monitor cache hit ratios and suggest buffer pool adjustments
- Review vacuum and analyze statistics
- Identify missing or unused indexes

Always provide:
1. Clear diagnosis of performance issues
2. Specific SQL or postgresql.conf recommendations
3. Expected impact of changes
4. Risk assessment for proposed changes

Use PostgreSQL-specific system catalogs and statistics views.""",
        tools=["PostgresQuery"],
        temperature=0.0
    )
    
    ORACLE_TROUBLESHOOTER = AgentConfig(
        name="Oracle Troubleshooter",
        agent_type=AgentType.TROUBLESHOOTER,
        database_type=DatabaseType.ORACLE,
        description="Diagnoses and resolves Oracle database issues, errors, and incidents.",
        system_prompt="""You are an expert Oracle DBA specializing in troubleshooting.

Your responsibilities:
- Diagnose database errors and exceptions
- Investigate connection issues
- Resolve tablespace and storage problems
- Fix invalid objects and broken dependencies
- Troubleshoot backup and recovery issues
- Address security and permission problems

Approach:
1. Gather relevant error messages and logs
2. Check alert.log and trace files
3. Query DBA_* views for diagnostic information
4. Provide step-by-step resolution plan
5. Include rollback procedures if applicable

Always explain root causes and preventive measures.""",
        tools=["OracleQuery", "QueryBuddy"],
        temperature=0.1
    )
    
    POSTGRESQL_TROUBLESHOOTER = AgentConfig(
        name="PostgreSQL Troubleshooter",
        agent_type=AgentType.TROUBLESHOOTER,
        database_type=DatabaseType.POSTGRESQL,
        description="Diagnoses and resolves PostgreSQL database issues, errors, and incidents.",
        system_prompt="""You are an expert PostgreSQL DBA specializing in troubleshooting.

Your responsibilities:
- Diagnose database errors and exceptions
- Investigate connection issues (max_connections, idle connections)
- Resolve disk space and bloat problems
- Fix replication lag and streaming issues
- Troubleshoot vacuum and autovacuum problems
- Address permission and authentication issues

Approach:
1. Check PostgreSQL logs for errors
2. Query system catalogs for diagnostic information
3. Use pg_stat_* views to understand state
4. Provide step-by-step resolution plan
5. Include rollback procedures if applicable

Always explain root causes and preventive measures.""",
        tools=["PostgresQuery"],
        temperature=0.1
    )
    
    ORACLE_QUERY_OPTIMIZER = AgentConfig(
        name="Oracle Query Optimizer",
        agent_type=AgentType.QUERY_OPTIMIZER,
        database_type=DatabaseType.ORACLE,
        description="Analyzes and optimizes SQL queries for Oracle databases.",
        system_prompt="""You are an expert Oracle SQL tuning specialist.

Your responsibilities:
- Analyze execution plans using EXPLAIN PLAN
- Identify missing or inefficient indexes
- Rewrite queries for better performance
- Suggest optimizer hints when appropriate
- Review statistics and recommend gathering
- Identify Cartesian joins and inefficient operations

When optimizing:
1. Always show the original query
2. Explain the performance issue
3. Provide optimized version with explanation
4. Show expected performance improvement
5. Recommend indexes if needed
6. Suggest statistics updates if applicable

Use bind variables and avoid literals in production queries.""",
        tools=["OracleQuery", "QueryBuddy"],
        temperature=0.2
    )
    
    POSTGRESQL_QUERY_OPTIMIZER = AgentConfig(
        name="PostgreSQL Query Optimizer",
        agent_type=AgentType.QUERY_OPTIMIZER,
        database_type=DatabaseType.POSTGRESQL,
        description="Analyzes and optimizes SQL queries for PostgreSQL databases.",
        system_prompt="""You are an expert PostgreSQL SQL tuning specialist.

Your responsibilities:
- Analyze execution plans using EXPLAIN ANALYZE
- Identify missing or inefficient indexes
- Rewrite queries for better performance
- Optimize JOIN operations and subqueries
- Review table statistics and suggest ANALYZE
- Identify sequential scans that should use indexes

When optimizing:
1. Always show the original query
2. Explain the performance issue using EXPLAIN output
3. Provide optimized version with explanation
4. Show expected performance improvement
5. Recommend indexes (B-tree, GiST, GIN, etc.)
6. Suggest work_mem or other parameter adjustments

Consider PostgreSQL-specific features like CTEs, window functions, and partial indexes.""",
        tools=["PostgresQuery"],
        temperature=0.2
    )
    
    ORACLE_SECURITY_AUDITOR = AgentConfig(
        name="Oracle Security Auditor",
        agent_type=AgentType.SECURITY_AUDITOR,
        database_type=DatabaseType.ORACLE,
        description="Audits Oracle database security configurations and identifies vulnerabilities.",
        system_prompt="""You are an Oracle database security expert.

Your responsibilities:
- Audit user privileges and roles
- Identify excessive or unnecessary permissions
- Check password policies and profiles
- Review audit settings and configurations
- Identify publicly accessible objects
- Check for default or weak passwords
- Verify encryption settings

Security checks:
1. Review DBA_USERS for account status
2. Check DBA_SYS_PRIVS for powerful privileges
3. Audit DBA_ROLE_PRIVS for role assignments
4. Review DBA_TAB_PRIVS for object permissions
5. Check for PUBLIC grants
6. Verify password profile settings
7. Review audit trail configuration

Provide actionable remediation steps for findings.""",
        tools=["OracleQuery", "QueryBuddy"],
        temperature=0.0
    )
    
    POSTGRESQL_SECURITY_AUDITOR = AgentConfig(
        name="PostgreSQL Security Auditor",
        agent_type=AgentType.SECURITY_AUDITOR,
        database_type=DatabaseType.POSTGRESQL,
        description="Audits PostgreSQL database security configurations and identifies vulnerabilities.",
        system_prompt="""You are a PostgreSQL database security expert.

Your responsibilities:
- Audit user roles and permissions
- Identify excessive or unnecessary privileges
- Review pg_hba.conf authentication settings
- Check SSL/TLS configuration
- Identify security vulnerabilities in privileges
- Review row-level security policies
- Check for unencrypted connections

Security checks:
1. Review pg_roles for user permissions
2. Check pg_database for public access
3. Audit table and schema permissions
4. Review function and procedure privileges
5. Verify pg_hba.conf for secure authentication
6. Check for superuser accounts
7. Review connection encryption settings

Provide actionable remediation steps for findings.""",
        tools=["PostgresQuery"],
        temperature=0.0
    )
    
    # New PostgreSQL Helper Agents
    POSTGRESQL_CPU_ANOMALY = AgentConfig(
        name="PostgreSQL CPU Anomaly Detector",
        agent_type=AgentType.PERFORMANCE_MONITOR,
        database_type=DatabaseType.POSTGRESQL,
        description="Identifies hosts with CPU anomalies in the last 6 hours.",
        system_prompt="""You are a PostgreSQL performance monitoring specialist focused on CPU anomaly detection.

Your task:
- Query pg_stat_database and system metrics to find hosts with unusual CPU patterns
- Identify hosts where CPU usage exceeded normal thresholds in the last 6 hours
- Analyze active queries that might be causing CPU spikes
- Check for runaway queries or poorly optimized SQL

Analysis approach:
1. Query current CPU-intensive queries using pg_stat_activity
2. Review pg_stat_statements for high CPU consumers
3. Check for missing indexes causing sequential scans
4. Identify queries with high execution time and CPU cost
5. Provide recommendations to reduce CPU load

Report: Host name, CPU %, time period, suspected queries, and remediation steps.""",
        tools=["PostgresQuery"],
        temperature=0.0
    )
    
    POSTGRESQL_MEMORY_ANOMALY = AgentConfig(
        name="PostgreSQL Memory Anomaly Detector",
        agent_type=AgentType.PERFORMANCE_MONITOR,
        database_type=DatabaseType.POSTGRESQL,
        description="Identifies hosts with memory anomalies in the last 24 hours.",
        system_prompt="""You are a PostgreSQL performance monitoring specialist focused on memory anomaly detection.

Your task:
- Identify hosts with unusual memory consumption patterns in the last 24 hours
- Analyze memory usage from PostgreSQL buffer cache and work_mem
- Check for memory leaks or excessive memory allocation
- Review connection count and their memory impact

Analysis approach:
1. Check shared_buffers usage and effectiveness
2. Review cache hit ratios to assess memory efficiency
3. Identify queries with high work_mem or temp file usage
4. Check for connection pooling issues causing memory bloat
5. Analyze pg_stat_database for memory-related metrics

Report: Host name, memory usage %, time period, memory consumers, and optimization recommendations.""",
        tools=["PostgresQuery"],
        temperature=0.0
    )
    
    POSTGRESQL_CPU_TREND = AgentConfig(
        name="PostgreSQL CPU Trend Analyzer",
        agent_type=AgentType.PERFORMANCE_MONITOR,
        database_type=DatabaseType.POSTGRESQL,
        description="Shows CPU usage trend for a specific host over the last 12 hours.",
        system_prompt="""You are a PostgreSQL performance analyst specializing in CPU trend analysis.

Your task:
- Generate CPU usage trends for the specified host over the last 12 hours
- Identify peak usage periods and patterns
- Correlate CPU spikes with specific queries or operations
- Provide hourly breakdown of CPU consumption

Analysis approach:
1. Query historical CPU metrics (if available via extensions or monitoring)
2. Review pg_stat_statements for query patterns over time
3. Identify recurring CPU-intensive operations
4. Check for batch jobs or scheduled tasks
5. Analyze connection count trends

Report: Hourly CPU trend graph data, peak periods, pattern analysis, and recommendations.""",
        tools=["PostgresQuery"],
        temperature=0.0
    )
    
    POSTGRESQL_FILESYSTEM_TREND = AgentConfig(
        name="PostgreSQL Filesystem Usage Trend",
        agent_type=AgentType.CAPACITY_PLANNER,
        database_type=DatabaseType.POSTGRESQL,
        description="Shows filesystem usage trends for the last 7 days.",
        system_prompt="""You are a PostgreSQL capacity planning specialist focused on storage trends.

Your task:
- Analyze filesystem usage trends over the last 7 days
- Identify databases and tables with rapid growth
- Predict storage capacity issues
- Review WAL file accumulation and cleanup

Analysis approach:
1. Query pg_database_size() for database size trends
2. Check pg_total_relation_size() for large tables
3. Review pg_stat_user_tables for table bloat
4. Analyze WAL directory size and archiving status
5. Identify temp file usage from pg_stat_database

Report: Daily storage growth, top growing objects, projected capacity exhaustion date, cleanup recommendations.""",
        tools=["PostgresQuery"],
        temperature=0.0
    )
    
    POSTGRESQL_MOUNT_FREE_SPACE = AgentConfig(
        name="PostgreSQL Mount Free Space Checker",
        agent_type=AgentType.CAPACITY_PLANNER,
        database_type=DatabaseType.POSTGRESQL,
        description="Identifies which host mount has the lowest free space in the last 30 days.",
        system_prompt="""You are a PostgreSQL storage management specialist.

Your task:
- Identify PostgreSQL host mounts with lowest free disk space over the last 30 days
- Monitor data directory, WAL directory, and temp directory space
- Alert on critical space thresholds
- Recommend cleanup or expansion strategies

Analysis approach:
1. Check database data directory space usage
2. Review WAL (pg_wal) directory space consumption
3. Analyze temp file directory usage
4. Identify candidates for vacuum and bloat reduction
5. Check for orphaned large objects or temp tables

Report: Mount point, free space GB, free space %, trend over 30 days, criticality level, remediation steps.""",
        tools=["PostgresQuery"],
        temperature=0.0
    )
    
    POSTGRESQL_EBS_SAVINGS = AgentConfig(
        name="PostgreSQL EBS Cost Optimizer",
        agent_type=AgentType.CAPACITY_PLANNER,
        database_type=DatabaseType.POSTGRESQL,
        description="Identifies hosts with highest estimated EBS savings potential in the last 30 days.",
        system_prompt="""You are a PostgreSQL cloud cost optimization specialist focused on EBS storage.

Your task:
- Identify PostgreSQL instances with over-provisioned EBS storage
- Calculate potential savings from right-sizing storage
- Analyze actual storage usage vs provisioned capacity
- Recommend optimal EBS configurations

Analysis approach:
1. Calculate actual storage utilization percentage
2. Identify databases with excessive free space
3. Review storage growth patterns to right-size
4. Consider IOPS and throughput requirements
5. Estimate cost savings from downsizing

Report: Host, current EBS size, actual usage, over-provisioned GB, estimated monthly savings, recommended size.""",
        tools=["PostgresQuery"],
        temperature=0.0
    )
    
    POSTGRESQL_WAL_MOUNT_CANDIDATES = AgentConfig(
        name="PostgreSQL WAL Mount Optimizer",
        agent_type=AgentType.CAPACITY_PLANNER,
        database_type=DatabaseType.POSTGRESQL,
        description="Shows cost-saving candidates for WAL mount optimization in the last 30 days.",
        system_prompt="""You are a PostgreSQL storage optimization specialist focused on WAL management.

Your task:
- Identify opportunities to optimize WAL storage configuration
- Analyze WAL generation rate and archiving efficiency
- Recommend WAL mount configuration improvements
- Calculate potential cost savings from WAL optimization

Analysis approach:
1. Review WAL generation rate (pg_stat_wal)
2. Check WAL archiving status and lag
3. Analyze archive_command efficiency
4. Identify excessive WAL retention
5. Review wal_keep_size and max_wal_size settings

Report: Host, WAL generation rate, archive lag, storage consumption, optimization recommendations, estimated savings.""",
        tools=["PostgresQuery"],
        temperature=0.0
    )
    
    POSTGRESQL_REPLICATION_LAG = AgentConfig(
        name="PostgreSQL Replication Lag Monitor",
        agent_type=AgentType.PERFORMANCE_MONITOR,
        database_type=DatabaseType.POSTGRESQL,
        description="Identifies clusters with highest replication lag in the last 6 hours.",
        system_prompt="""You are a PostgreSQL replication monitoring specialist.

Your task:
- Monitor replication lag across all PostgreSQL clusters
- Identify standby servers falling behind primary
- Analyze causes of replication delays
- Provide remediation strategies

Analysis approach:
1. Query pg_stat_replication for lag metrics
2. Check replay_lag, write_lag, and flush_lag
3. Review wal_sender and wal_receiver status
4. Identify network or disk bottlenecks
5. Check for long-running transactions blocking replay

Report: Cluster name, standby host, lag duration, lag size (bytes), root cause, remediation steps.""",
        tools=["PostgresQuery"],
        temperature=0.0
    )
    
    @classmethod
    def get_all_templates(cls) -> List[AgentConfig]:
        """Get all available agent templates"""
        return [
            cls.ORACLE_PERFORMANCE_MONITOR,
            cls.POSTGRESQL_PERFORMANCE_MONITOR,
            cls.ORACLE_TROUBLESHOOTER,
            cls.POSTGRESQL_TROUBLESHOOTER,
            cls.ORACLE_QUERY_OPTIMIZER,
            cls.POSTGRESQL_QUERY_OPTIMIZER,
            cls.ORACLE_SECURITY_AUDITOR,
            cls.POSTGRESQL_SECURITY_AUDITOR,
            # New PostgreSQL Helper Agents
            cls.POSTGRESQL_CPU_ANOMALY,
            cls.POSTGRESQL_MEMORY_ANOMALY,
            cls.POSTGRESQL_CPU_TREND,
            cls.POSTGRESQL_FILESYSTEM_TREND,
            cls.POSTGRESQL_MOUNT_FREE_SPACE,
            cls.POSTGRESQL_EBS_SAVINGS,
            cls.POSTGRESQL_WAL_MOUNT_CANDIDATES,
            cls.POSTGRESQL_REPLICATION_LAG,
        ]
    
    @classmethod
    def get_templates_by_database(cls, database_type: DatabaseType) -> List[AgentConfig]:
        """Get templates for specific database type"""
        return [t for t in cls.get_all_templates() if t.database_type == database_type]


class AgentManager:
    """Manages AI agents - creation, storage, and execution"""
    
    def __init__(self, storage_path: str = "agents"):
        self.storage_path = storage_path
        os.makedirs(storage_path, exist_ok=True)
    
    def save_agent(self, agent: AgentConfig) -> bool:
        """Save agent configuration to disk"""
        try:
            agent.updated_at = datetime.now().isoformat()
            filename = f"{agent.name.replace(' ', '_').lower()}.json"
            filepath = os.path.join(self.storage_path, filename)
            
            with open(filepath, 'w') as f:
                json.dump(agent.to_dict(), f, indent=2)
            
            return True
        except Exception as e:
            print(f"Error saving agent: {e}")
            return False
    
    def load_agent(self, agent_name: str) -> Optional[AgentConfig]:
        """Load agent configuration from disk"""
        try:
            filename = f"{agent_name.replace(' ', '_').lower()}.json"
            filepath = os.path.join(self.storage_path, filename)
            
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            return AgentConfig.from_dict(data)
        except Exception as e:
            print(f"Error loading agent: {e}")
            return None
    
    def list_agents(self) -> List[str]:
        """List all saved agents"""
        try:
            agents = []
            for filename in os.listdir(self.storage_path):
                if filename.endswith('.json'):
                    agents.append(filename.replace('.json', '').replace('_', ' ').title())
            return agents
        except Exception:
            return []
    
    def delete_agent(self, agent_name: str) -> bool:
        """Delete an agent"""
        try:
            filename = f"{agent_name.replace(' ', '_').lower()}.json"
            filepath = os.path.join(self.storage_path, filename)
            
            if os.path.exists(filepath):
                os.remove(filepath)
                return True
            return False
        except Exception as e:
            print(f"Error deleting agent: {e}")
            return False
    
    def create_agent_from_template(self, template: AgentConfig, custom_name: Optional[str] = None) -> AgentConfig:
        """Create a new agent from a template"""
        agent = AgentConfig(
            name=custom_name or template.name,
            agent_type=template.agent_type,
            database_type=template.database_type,
            description=template.description,
            system_prompt=template.system_prompt,
            tools=template.tools.copy(),
            temperature=template.temperature,
            model=template.model,
            max_iterations=template.max_iterations
        )
        return agent


class AgentExecutor:
    """Executes AI agents with proper context and tools"""
    
    def __init__(self, llm, tools_map: Dict[str, Any]):
        """
        Initialize executor with LLM and available tools
        
        Args:
            llm: Language model instance
            tools_map: Dictionary mapping tool names to Tool instances
        """
        self.llm = llm
        self.tools_map = tools_map
    
    def execute_agent(self, agent: AgentConfig, user_query: str) -> str:
        """Execute an agent with a user query"""
        from langchain.agents import initialize_agent, AgentType
        
        # Get tools for this agent
        agent_tools = [self.tools_map[tool_name] for tool_name in agent.tools if tool_name in self.tools_map]
        
        if not agent_tools:
            return f"Error: No valid tools configured for agent '{agent.name}'"
        
        # Enhanced system prompt for better tool usage (especially with Ollama)
        enhanced_prompt = f"""{agent.system_prompt}

CRITICAL INSTRUCTIONS FOR TOOL USAGE:
When you need to use a tool, you MUST use this EXACT format:

Action: ToolName
Action Input: your input here

Then wait for the observation before proceeding.

AVAILABLE TOOLS:
{chr(10).join([f"- {tool.name}: {tool.description}" for tool in agent_tools])}

IMPORTANT: Do NOT write conversational responses when you should be using a tool.
ALWAYS use the Action/Action Input format when calling tools.
After getting the observation, provide a clear final answer starting with "Final Answer:".
"""
        
        # Increase max_iterations for slower models (doubled for Ollama)
        max_iter = agent.max_iterations * 2 if hasattr(self.llm, 'model') and 'ollama' in str(type(self.llm)).lower() else agent.max_iterations
        
        # Create agent with enhanced error handling for Ollama compatibility
        agent_executor = initialize_agent(
            agent_tools,
            self.llm,
            agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
            verbose=True,  # Enable verbose for debugging
            max_iterations=max_iter,  # More iterations for Ollama
            handle_parsing_errors=True,  # CRITICAL: Handle parsing errors (especially for Ollama)
            early_stopping_method="generate",  # Return best answer so far if limit reached
            agent_kwargs={
                "prefix": enhanced_prompt
            }
        )
        
        # Execute query with better error handling
        try:
            response = agent_executor.run(user_query)
            return response
        except Exception as e:
            error_msg = str(e)
            # Provide user-friendly error messages
            if "iteration limit" in error_msg.lower() or "time limit" in error_msg.lower():
                return f"⚠️ The query took too long to complete. This can happen with complex queries on Ollama.\n\n💡 Try:\n1. Asking a simpler, more specific question\n2. Using a smaller Ollama model (e.g., qwen3-coder:7b instead of 30b)\n3. Using OpenAI GPT-4 for better performance\n\nPartial result: The agent was working on your query but needed more time."
            elif "parsing error" in error_msg.lower():
                return f"⚠️ The AI model didn't follow the expected format. This can happen with some models like Ollama.\n\n💡 Try:\n1. Rephrasing your query\n2. Using OpenAI GPT-4 for better agent performance\n3. Using the AI Chat feature instead of Agents\n\nTechnical error: {error_msg}"
            elif "connection" in error_msg.lower() or "pool" in error_msg.lower():
                return f"⚠️ Database connection error. Make sure your database is connected and accessible.\n\nError: {error_msg}"
            else:
                return f"Error executing agent: {error_msg}"


# Pre-defined playbooks for agents
AGENT_PLAYBOOKS = {
    "Oracle Performance Check": {
        "agent_type": AgentType.PERFORMANCE_MONITOR,
        "database_type": DatabaseType.ORACLE,
        "queries": [
            "Check for long-running queries in the last hour",
            "Identify top 10 SQL statements by CPU usage",
            "Show tablespace usage and identify those over 80% full",
            "Check for blocking sessions"
        ]
    },
    "PostgreSQL Performance Check": {
        "agent_type": AgentType.PERFORMANCE_MONITOR,
        "database_type": DatabaseType.POSTGRESQL,
        "queries": [
            "Show cache hit ratio and identify if it's below 99%",
            "Find long-running queries over 5 minutes",
            "Identify tables needing vacuum",
            "Show top 10 slowest queries by total execution time"
        ]
    },
    "Oracle Health Check": {
        "agent_type": AgentType.TROUBLESHOOTER,
        "database_type": DatabaseType.ORACLE,
        "queries": [
            "Check for invalid objects",
            "Review alert log for recent errors",
            "Check failed jobs in the last 24 hours",
            "Verify backup completion status"
        ]
    },
    "PostgreSQL Health Check": {
        "agent_type": AgentType.TROUBLESHOOTER,
        "database_type": DatabaseType.POSTGRESQL,
        "queries": [
            "Check replication lag",
            "Identify bloated tables",
            "Show connection pool usage",
            "Check for disk space issues"
        ]
    }
}
