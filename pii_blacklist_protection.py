"""
Enhanced PII Protection with Blacklist
Blocks/redacts specific tables and columns based on configuration
"""

import json
import re
import pandas as pd
from typing import Tuple, List, Dict, Any, Set
import hashlib

class PIIBlacklist:
    """
    Manages PII blacklist from configuration file
    """
    
    def __init__(self, config_file: str = 'pii_blacklist.json'):
        """Initialize with blacklist configuration"""
        try:
            with open(config_file, 'r') as f:
                self.config = json.load(f)
        except FileNotFoundError:
            print(f"Warning: {config_file} not found. Using default protection.")
            self.config = self._get_default_config()
    
    def _get_default_config(self) -> dict:
        """Default configuration if file not found"""
        return {
            "pii_protection": {"enabled": True, "mode": "block_and_redact"},
            "blocked_tables": {"oracle": [], "postgresql": []},
            "pii_tables_and_columns": {"oracle": {}, "postgresql": {}},
            "pii_column_patterns": {"patterns": []},
            "allowed_operations": {"allow_aggregated_pii": True},
            "exemptions": {"exempt_users": [], "exempt_roles": []},
            "actions": {
                "on_blocked_table": "block_query",
                "on_pii_column": "redact_data",
                "on_select_star": "warn_and_redact"
            }
        }
    
    def is_enabled(self) -> bool:
        """Check if PII protection is enabled"""
        return self.config.get('pii_protection', {}).get('enabled', True)
    
    def is_user_exempt(self, username: str) -> bool:
        """Check if user is exempt from PII restrictions"""
        exempt_users = self.config.get('exemptions', {}).get('exempt_users', [])
        return username in exempt_users
    
    def is_table_blocked(self, table_name: str, db_type: str = 'postgresql') -> bool:
        """Check if table is completely blocked"""
        blocked = self.config.get('blocked_tables', {}).get(db_type.lower(), [])
        
        # Case-insensitive comparison
        table_upper = table_name.upper()
        blocked_upper = [t.upper() for t in blocked]
        
        return table_upper in blocked_upper
    
    def get_pii_columns_for_table(self, table_name: str, db_type: str = 'postgresql') -> List[str]:
        """Get list of PII columns for a specific table"""
        pii_tables = self.config.get('pii_tables_and_columns', {}).get(db_type.lower(), {})
        
        # Try exact match first
        if table_name in pii_tables:
            return pii_tables[table_name]
        
        # Try case-insensitive match
        for table, columns in pii_tables.items():
            if table.upper() == table_name.upper():
                return columns
        
        return []
    
    def is_column_pii_by_pattern(self, column_name: str) -> bool:
        """Check if column name matches PII patterns"""
        patterns = self.config.get('pii_column_patterns', {}).get('patterns', [])
        
        column_lower = column_name.lower().replace('_', '').replace(' ', '')
        
        for pattern in patterns:
            pattern_clean = pattern.lower().replace('_', '').replace(' ', '')
            if pattern_clean in column_lower:
                return True
        
        return False
    
    def is_aggregated_query(self, sql: str) -> bool:
        """Check if query uses only aggregation functions (safe for PII)"""
        if not self.config.get('allowed_operations', {}).get('allow_aggregated_pii', True):
            return False
        
        sql_upper = sql.upper()
        
        # Check for aggregation functions
        agg_functions = self.config.get('allowed_operations', {}).get('aggregations', [
            'COUNT', 'AVG', 'SUM', 'MIN', 'MAX', 'STDDEV'
        ])
        
        has_aggregation = any(f'{func}(' in sql_upper for func in agg_functions)
        has_group_by = 'GROUP BY' in sql_upper
        
        # Does NOT select individual rows with *
        select_part = sql_upper.split('FROM')[0] if 'FROM' in sql_upper else sql_upper
        has_select_star = re.search(r'SELECT\s+\*', select_part)
        
        # Aggregated if: has aggregation OR has group by, AND doesn't have SELECT *
        return (has_aggregation or has_group_by) and not has_select_star


class PIIQueryValidator:
    """
    Validates SQL queries against PII blacklist
    """
    
    def __init__(self, blacklist: PIIBlacklist):
        self.blacklist = blacklist
    
    def extract_tables_from_query(self, sql: str) -> List[str]:
        """Extract table names from SQL query"""
        tables = []
        
        # Simple regex to find table names after FROM and JOIN
        from_pattern = r'FROM\s+([a-zA-Z0-9_]+)'
        join_pattern = r'JOIN\s+([a-zA-Z0-9_]+)'
        
        from_matches = re.finditer(from_pattern, sql, re.IGNORECASE)
        join_matches = re.finditer(join_pattern, sql, re.IGNORECASE)
        
        for match in from_matches:
            tables.append(match.group(1))
        
        for match in join_matches:
            tables.append(match.group(1))
        
        return list(set(tables))  # Remove duplicates
    
    def extract_columns_from_query(self, sql: str) -> List[str]:
        """Extract column names from SELECT clause"""
        columns = []
        
        # Extract SELECT clause
        select_match = re.search(r'SELECT\s+(.*?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
        if not select_match:
            return columns
        
        select_clause = select_match.group(1)
        
        # Check for SELECT *
        if '*' in select_clause:
            return ['*']
        
        # Split by comma and extract column names
        parts = re.split(r',\s*', select_clause)
        
        for part in parts:
            # Remove table aliases (table.column -> column)
            if '.' in part:
                column = part.split('.')[-1].strip()
            else:
                column = part.strip()
            
            # Remove AS aliases
            column = re.split(r'\s+AS\s+', column, flags=re.IGNORECASE)[0].strip()
            
            # Remove function calls (e.g., COUNT(column) -> column)
            func_match = re.search(r'\w+\((.*?)\)', column)
            if func_match:
                column = func_match.group(1).strip()
            
            if column and column != '*':
                columns.append(column)
        
        return columns
    
    def validate_query(self, sql: str, username: str, db_type: str = 'postgresql') -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validate SQL query against PII blacklist
        
        Returns:
            (is_allowed, message, details)
        """
        if not self.blacklist.is_enabled():
            return True, "PII protection disabled", {}
        
        # Check if user is exempt
        if self.blacklist.is_user_exempt(username):
            return True, f"User {username} exempt from PII restrictions", {'exempt': True}
        
        # Extract tables and columns
        tables = self.extract_tables_from_query(sql)
        columns = self.extract_columns_from_query(sql)
        
        # Check for blocked tables
        blocked_tables = []
        for table in tables:
            if self.blacklist.is_table_blocked(table, db_type):
                blocked_tables.append(table)
        
        if blocked_tables:
            message = f"""
🚫 QUERY BLOCKED - PII TABLE ACCESS

The following tables are blocked due to PII content:
{', '.join(blocked_tables)}

These tables contain sensitive personally identifiable information (PII) 
and cannot be accessed through AI assistants.

ALTERNATIVES:
1. Use aggregated queries (COUNT, AVG, SUM)
2. Query specific non-PII columns only
3. Contact your DBA for direct access
4. Use views that pre-filter PII data

Your query: {sql[:100]}...
            """
            
            return False, message.strip(), {
                'blocked': True,
                'blocked_tables': blocked_tables,
                'reason': 'blocked_table_access'
            }
        
        # Check for PII columns
        pii_columns_found = []
        
        # Check SELECT *
        if '*' in columns:
            # SELECT * might include PII columns
            for table in tables:
                table_pii_cols = self.blacklist.get_pii_columns_for_table(table, db_type)
                if table_pii_cols:
                    pii_columns_found.extend([f"{table}.{col}" for col in table_pii_cols])
            
            if pii_columns_found:
                # Check if aggregated query
                if self.blacklist.is_aggregated_query(sql):
                    return True, "Aggregated query - individual PII not exposed", {
                        'aggregated': True,
                        'warning': 'SELECT * with aggregation'
                    }
                
                message = f"""
⚠️ PII WARNING - SELECT * DETECTED

SELECT * may include PII columns:
{', '.join(pii_columns_found[:10])}{'...' if len(pii_columns_found) > 10 else ''}

ACTION: Query allowed but PII data will be REDACTED before sending to LLM

RECOMMENDATION: Select only needed columns instead of using SELECT *

Your query: {sql[:100]}...
                """
                
                return True, message.strip(), {
                    'pii_warning': True,
                    'pii_columns': pii_columns_found,
                    'action': 'redact',
                    'reason': 'select_star_with_pii'
                }
        
        # Check individual columns
        for column in columns:
            # Check against table-specific PII columns
            for table in tables:
                table_pii_cols = self.blacklist.get_pii_columns_for_table(table, db_type)
                table_pii_upper = [c.upper() for c in table_pii_cols]
                
                if column.upper() in table_pii_upper:
                    pii_columns_found.append(f"{table}.{column}")
            
            # Check against pattern-based PII detection
            if self.blacklist.is_column_pii_by_pattern(column):
                if column not in pii_columns_found:
                    pii_columns_found.append(column)
        
        if pii_columns_found:
            # Check if aggregated
            if self.blacklist.is_aggregated_query(sql):
                return True, "Aggregated query - individual PII not exposed", {
                    'aggregated': True,
                    'pii_columns': pii_columns_found
                }
            
            message = f"""
⚠️ PII WARNING - SENSITIVE COLUMNS DETECTED

PII columns in query:
{', '.join(pii_columns_found)}

ACTION: Query allowed but PII data will be REDACTED before sending to LLM

All PII access is logged for audit compliance.

Your query: {sql[:100]}...
            """
            
            return True, message.strip(), {
                'pii_warning': True,
                'pii_columns': pii_columns_found,
                'action': 'redact'
            }
        
        # No PII detected
        return True, "No PII detected", {'clean': True}


def redact_pii_dataframe(df: pd.DataFrame, pii_columns: List[str], blacklist: PIIBlacklist, 
                         db_type: str = 'postgresql') -> Tuple[pd.DataFrame, str]:
    """
    Redact PII columns from DataFrame based on blacklist
    
    Args:
        df: DataFrame with query results
        pii_columns: List of PII columns to redact
        blacklist: PIIBlacklist instance
        db_type: Database type
        
    Returns:
        (redacted_df, summary_message)
    """
    if df is None or df.empty:
        return df, "No data to redact"
    
    if not pii_columns:
        return df, "No PII columns to redact"
    
    redacted_df = df.copy()
    redacted_count = 0
    
    # Get table names from column list (if formatted as table.column)
    tables_in_query = set()
    for col_spec in pii_columns:
        if '.' in col_spec:
            table = col_spec.split('.')[0]
            tables_in_query.add(table)
    
    # Redact each column
    for col in df.columns:
        should_redact = False
        
        # Check if column is in PII list
        if col in pii_columns:
            should_redact = True
        elif any(pii_col.endswith(f'.{col}') for pii_col in pii_columns):
            should_redact = True
        
        # Check against blacklist for each table
        for table in tables_in_query:
            table_pii_cols = blacklist.get_pii_columns_for_table(table, db_type)
            if col.upper() in [c.upper() for c in table_pii_cols]:
                should_redact = True
                break
        
        # Check pattern-based detection
        if blacklist.is_column_pii_by_pattern(col):
            should_redact = True
        
        if should_redact:
            # Redact with hash
            redacted_df[col] = df[col].apply(
                lambda x: hashlib.sha256(str(x).encode()).hexdigest()[:16] if pd.notna(x) else x
            )
            redacted_count += 1
    
    summary = f"""
🛡️ PII PROTECTION APPLIED

Redacted {redacted_count} column(s):
{', '.join([col for col in df.columns if col in pii_columns or blacklist.is_column_pii_by_pattern(col)][:10])}

Original rows: {len(df)}
Redaction method: SHA256 Hash (preserves uniqueness)

✓ Safe to send to LLM
    """
    
    return redacted_df, summary.strip()


# Logging function
def log_pii_access(event_type: str, username: str, details: Dict[str, Any], 
                   log_file: str = 'logs/pii_access.log'):
    """Log PII access attempt"""
    import os
    from datetime import datetime
    
    # Ensure log directory exists
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    
    log_entry = {
        'timestamp': datetime.now().isoformat(),
        'event_type': event_type,
        'username': username,
        **details
    }
    
    with open(log_file, 'a') as f:
        f.write(json.dumps(log_entry) + '\n')


# ─────────────────────────────────────────────────────────────────────────────
# Flask adapter layer — module-level singletons + convenience functions
# The functions below are called by query.py / ai.py
# ─────────────────────────────────────────────────────────────────────────────

import os as _os
from pathlib import Path as _Path

_DEFAULT_CONFIG = _os.getenv("PII_BLACKLIST_FILE", "data/pii_blacklist.json")
_bl_singleton: 'PIIBlacklist | None' = None
_val_singleton: 'PIIQueryValidator | None' = None


def _get_bl() -> 'PIIBlacklist':
    global _bl_singleton
    if _bl_singleton is None:
        _bl_singleton = PIIBlacklist(_DEFAULT_CONFIG)
    return _bl_singleton


def _get_validator() -> 'PIIQueryValidator':
    global _val_singleton
    if _val_singleton is None:
        _val_singleton = PIIQueryValidator(_get_bl())
    return _val_singleton


def validate_pii(sql: str, username: str, db_type: str = 'postgresql'):
    """Convenience wrapper: returns (is_allowed, message, details)."""
    return _get_validator().validate_query(sql, username, db_type)


def redact_pii_rows(columns: list, rows: list, pii_col_specs: list, db_type: str = 'postgresql'):
    """
    List-based redaction (no pandas) for Flask query results.
    Returns (redacted_rows, summary_message).
    """
    if not columns or not rows:
        return rows, "No data to redact"

    bl = _get_bl()

    # Build set of bare column names (lowercase) that must be redacted
    redact_names: set = set()
    for spec in pii_col_specs:
        redact_names.add(spec.split('.')[-1].lower())

    # Also catch any column matching a PII pattern
    for col in columns:
        if bl.is_column_pii_by_pattern(col):
            redact_names.add(col.lower())

    redact_idx = {i for i, c in enumerate(columns) if c.lower() in redact_names}
    if not redact_idx:
        return rows, "No matching PII columns found in result set"

    import hashlib as _hashlib
    redacted_rows = [
        [_hashlib.sha256(str(v).encode()).hexdigest()[:16] if (i in redact_idx and v is not None) else v
         for i, v in enumerate(row)]
        for row in rows
    ]
    redacted_cols = [columns[i] for i in sorted(redact_idx)]
    summary = (f"🛡️ PII REDACTED: {len(redact_idx)} column(s) hashed "
               f"({', '.join(redacted_cols[:8])}{'…' if len(redacted_cols) > 8 else ''}). "
               f"{len(rows)} rows. Method: SHA-256 (16-char prefix).")
    return redacted_rows, summary


def get_pii_status() -> dict:
    """Return config summary for the admin UI."""
    bl = _get_bl()
    return {
        "enabled":          bl.is_enabled(),
        "mode":             bl.config.get("pii_protection", {}).get("mode", "block_and_redact"),
        "blocked_oracle":   bl.config.get("blocked_tables", {}).get("oracle", []),
        "blocked_postgres": bl.config.get("blocked_tables", {}).get("postgresql", []),
        "pii_map_oracle":   bl.config.get("pii_tables_and_columns", {}).get("oracle", {}),
        "pii_map_postgres": bl.config.get("pii_tables_and_columns", {}).get("postgresql", {}),
        "patterns":         bl.config.get("pii_column_patterns", {}).get("patterns", []),
        "exempt_users":     bl.config.get("exemptions", {}).get("exempt_users", []),
    }


def reload_blacklist() -> None:
    """Force reload from disk after admin config change."""
    global _bl_singleton, _val_singleton
    _bl_singleton = PIIBlacklist(_DEFAULT_CONFIG)
    _val_singleton = PIIQueryValidator(_bl_singleton)
