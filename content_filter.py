"""
Content Filter Module
Blocks inappropriate questions in AI Agent chat
Does NOT affect SQL execution safety - that remains unchanged
"""

from typing import Tuple

class ChatContentFilter:
    """
    Filter inappropriate content from user chat questions
    Only affects what users can ASK, not SQL execution
    """
    
    # Restricted keywords in questions
    RESTRICTED_KEYWORDS = [
        # Adult/Inappropriate content
        'adult', 'porn', 'sex', 'sexual', 'nude', 'naked', 'xxx', 'erotic',

        # Abuse/Violence
        'abuse', 'violence', 'violent', 'kill', 'murder', 'torture', 'harm', 'hurt',

        # Political content
        'political', 'politics', 'election', 'vote', 'democrat', 'republican',
        'liberal', 'conservative', 'trump', 'biden', 'government conspiracy',

        # Hate speech
        'racist', 'racism', 'sexist', 'sexism', 'hate speech', 'discrimination',

        # Illegal activities
        'illegal', 'hack into', 'crack password', 'pirate', 'steal data',

        # Dangerous SQL keywords in questions — multi-word phrases
        'drop table', 'drop database', 'drop all', 'drop schema',
        'drop user', 'drop role', 'drop index', 'drop view', 'drop sequence',
        'delete from', 'delete all', 'delete everything', 'delete user',
        'truncate table', 'truncate all',
        'alter table', 'alter database', 'alter schema', 'alter user', 'alter role',
        'update table', 'update all', 'update everything',
        'insert into', 'insert bulk',
        'grant all', 'revoke all', 'grant privilege', 'grant permission',
        'remove table', 'remove database', 'remove all', 'remove user',
        'create user', 'create table', 'create index', 'create database',
    ]

    # Single dangerous SQL verbs — blocked when they appear as standalone words
    # (catches "DROP user bkp123", "DELETE FROM ...", "ALTER SESSION SET ..." etc.)
    DANGEROUS_SQL_VERBS = {
        'drop', 'truncate', 'delete', 'alter', 'insert', 'update',
        'grant', 'revoke', 'create', 'replace', 'rename', 'purge',
        'flashback', 'merge',
    }

    @staticmethod
    def is_question_allowed(question: str) -> Tuple[bool, str]:
        """
        Check if user question contains restricted content.

        Returns:
            (is_allowed, reason): True if allowed, False with reason if blocked
        """
        if not question or not question.strip():
            return True, ""

        question_lower = question.lower().strip()

        # Check multi-word restricted phrases
        for keyword in ChatContentFilter.RESTRICTED_KEYWORDS:
            if keyword in question_lower:
                return False, f"Question contains restricted content: '{keyword}'"

        # Check standalone dangerous SQL verbs via word-boundary matching
        import re
        for verb in ChatContentFilter.DANGEROUS_SQL_VERBS:
            if re.search(r'\b' + verb + r'\b', question_lower):
                return False, f"Destructive SQL operation not permitted: '{verb.upper()}'"

        return True, ""
    
    @staticmethod
    def get_blocked_message(reason: str) -> str:
        """
        Get user-friendly blocked message
        
        Args:
            reason: Reason for blocking
            
        Returns:
            User-friendly message
        """
        return f"""
🚫 **Question Blocked**

Your question was blocked due to restricted content.

**Reason:** {reason}

**Allowed Questions:**
✅ Database performance analysis
✅ Query optimization
✅ Monitoring and alerts
✅ Schema information (SELECT/SHOW/DESCRIBE)
✅ Technical database questions

**Not Allowed:**
❌ Adult or inappropriate content
❌ Political discussions
❌ Violent or abusive content
❌ Dangerous SQL operations (DROP, DELETE, ALTER, UPDATE, INSERT)
❌ Illegal activities

Please rephrase your question to focus on database monitoring and analysis.
        """


def validate_chat_question(question: str) -> Tuple[bool, str]:
    """
    Validate chat question before processing
    
    Args:
        question: User's question
        
    Returns:
        (is_allowed, message): True if allowed, error message if blocked
    """
    is_allowed, reason = ChatContentFilter.is_question_allowed(question)
    
    if not is_allowed:
        return False, ChatContentFilter.get_blocked_message(reason)
    
    return True, ""
