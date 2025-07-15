"""Search tools for querying lecture transcripts with enhanced semantic understanding."""

import sqlite3
from typing import List, Optional, Tuple
from pathlib import Path
from project_types import LectureEntry
from dataclasses import dataclass
from typing import Optional
import os
import re

# Database connection management similar to email_search_tools
DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lectures.db")

conn = None

def get_conn():
    global conn
    if conn is None:
        conn = sqlite3.connect(
            f"file:{DEFAULT_DB_PATH}?mode=ro", uri=True, check_same_thread=False
        )
    return conn


@dataclass
class SearchResult:
    entry_id: int  # Changed from 'id' to match email pattern
    session_type: str
    session_number: int
    speaker_name: str
    timestamp: str
    snippet: str


def search_lectures(
    keywords: Optional[List[str]] = None,
    use_or_search: bool = False,
    session_type: Optional[str] = None,
    session_number: Optional[int] = None,
    speaker_name: Optional[str] = None,
    date_after: Optional[str] = None,
    date_before: Optional[str] = None,
    max_results: int = 10
) -> List[SearchResult]:
    """
    Enhanced search with flexible keyword matching.
    
    Args:
        keywords: List of keywords to search for
        use_or_search: If True, match ANY keyword; if False, match ALL keywords
        session_type: Optional filter by 'lecture' or 'officehours'
        session_number: Optional session number to filter by
        speaker_name: Optional speaker name to filter by
        date_after: Optional timestamp filter 'HH:MM:SS'
        date_before: Optional timestamp filter 'HH:MM:SS'
        max_results: Maximum number of results to return
    
    Returns:
        List of SearchResult objects
    """
    if max_results > 10:
        raise ValueError("max_results must be less than or equal to 10.")
    
    cursor = get_conn().cursor()
    
    # Build the query
    where_clauses = []
    params = []
    
    # Build FTS query based on mode
    if keywords:
        # Expand keywords for better matching
        expanded_keywords = []
        for kw in keywords:
            expanded_keywords.append(kw.lower())
            # Add common variations
            if kw.lower().endswith('ing') and len(kw) > 4:
                expanded_keywords.append(kw[:-3])  # managing -> manag
            elif kw.lower().endswith('ies') and len(kw) > 4:
                expanded_keywords.append(kw[:-3] + 'y')  # libraries -> library
            elif kw.lower().endswith('ed') and len(kw) > 3:
                expanded_keywords.append(kw[:-2])  # managed -> manag
        
        # Remove duplicates
        unique_keywords = list(dict.fromkeys(expanded_keywords))
        
        if use_or_search:
            # OR search - match any keyword with wildcards
            fts_query = " OR ".join(f'"{k.replace('"', '""')}*"' for k in unique_keywords)
        else:
            # AND search - match all keywords with wildcards
            fts_query = " ".join(f'"{k.replace('"', '""')}*"' for k in unique_keywords)
        
        where_clauses.append("fts.lectures_fts MATCH ?")
        params.append(fts_query)
    
    # Add filters
    if session_type:
        where_clauses.append("l.session_type = ?")
        params.append(session_type)
    
    if session_number is not None:
        where_clauses.append("l.session_number = ?")
        params.append(session_number)
    
    if speaker_name:
        where_clauses.append("l.speaker_name LIKE ?")
        params.append(f'%{speaker_name}%')
    
    if date_after:
        where_clauses.append("l.timestamp >= ?")
        params.append(date_after)
    
    if date_before:
        where_clauses.append("l.timestamp < ?")
        params.append(date_before)
    
    # Construct final query
    if keywords:
        # Query with FTS join
        where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"
        sql = f"""
            SELECT DISTINCT
                l.id,
                l.session_type,
                l.session_number,
                l.speaker_name,
                l.timestamp,
                snippet(lectures_fts, -1, '<b>', '</b>', '...', 20) as snippet
            FROM lectures l
            JOIN lectures_fts fts ON l.id = fts.rowid
            WHERE {where_clause}
            ORDER BY rank
            LIMIT ?
        """
    else:
        # Query without FTS when no keywords
        where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"
        sql = f"""
            SELECT 
                l.id,
                l.session_type,
                l.session_number,
                l.speaker_name,
                l.timestamp,
                substr(l.content, 1, 150) || '...' as snippet
            FROM lectures l
            WHERE {where_clause}
            ORDER BY l.session_type, l.session_number, l.timestamp
            LIMIT ?
        """
    
    params.append(max_results)
    cursor.execute(sql, params)
    results = cursor.fetchall()
    
    # Format results
    return [
        SearchResult(
            entry_id=row[0],
            session_type=row[1],
            session_number=row[2],
            speaker_name=row[3],
            timestamp=row[4],
            snippet=row[5]
        ) for row in results
    ]


def extract_key_terms(question: str) -> List[str]:
    """
    Extract key terms from a natural language question.
    
    Args:
        question: The question to analyze
        
    Returns:
        List of key terms to search for
    """
    # Remove common question words
    stop_words = {
        'what', 'who', 'when', 'where', 'why', 'how', 'is', 'are', 'was', 'were',
        'do', 'does', 'did', 'can', 'could', 'would', 'should', 'the', 'a', 'an',
        'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'about',
        'anyone', 'someone', 'something', 'anything', 'explain', 'describe'
    }
    
    # Tokenize and clean
    words = re.findall(r'\b\w+\b', question.lower())
    
    # Remove stop words but keep important terms
    key_terms = []
    for word in words:
        if word not in stop_words and len(word) > 2:
            key_terms.append(word)
    
    # Add stem variations for common patterns
    expanded_terms = []
    for term in key_terms:
        expanded_terms.append(term)
        
        # Add common variations
        if term.endswith('ing') and len(term) > 5:
            expanded_terms.append(term[:-3])  # greeting -> greet
        elif term.endswith('ed') and len(term) > 4:
            expanded_terms.append(term[:-2])  # greeted -> greet
            expanded_terms.append(term[:-1])  # stopped -> stoppe
    
    # Remove duplicates while preserving order
    seen = set()
    unique_terms = []
    for term in expanded_terms:
        if term not in seen:
            seen.add(term)
            unique_terms.append(term)
    
    return unique_terms


def search_with_fallback(
    question: str,
    session_type: Optional[str] = None,
    session_number: Optional[int] = None,
    max_results: int = 10
) -> List[SearchResult]:
    """
    Search with automatic fallback strategies.
    
    1. Try exact match with all keywords
    2. Try OR search with keywords
    3. Try searching in all sessions
    4. Extract and try key terms only
    
    Args:
        question: Natural language question
        session_type: Optional session type filter
        session_number: Optional session number filter
        max_results: Maximum results to return
        
    Returns:
        List of SearchResult objects
    """
    # Extract key terms from question
    keywords = extract_key_terms(question)
    
    if not keywords:
        return []
    
    # Strategy 1: Try AND search in specified session
    results = search_lectures(
        keywords=keywords,
        use_or_search=False,
        session_type=session_type,
        session_number=session_number,
        max_results=max_results
    )
    
    if results:
        return results
    
    # Strategy 2: Try OR search in specified session
    results = search_lectures(
        keywords=keywords,
        use_or_search=True,
        session_type=session_type,
        session_number=session_number,
        max_results=max_results
    )
    
    if results:
        return results
    
    # Strategy 3: Try AND search across all sessions
    results = search_lectures(
        keywords=keywords,
        use_or_search=False,
        session_type=None,
        session_number=None,
        max_results=max_results
    )
    
    if results:
        return results
    
    # Strategy 4: Try OR search across all sessions
    results = search_lectures(
        keywords=keywords,
        use_or_search=True,
        session_type=None,
        session_number=None,
        max_results=max_results
    )
    
    return results


def read_lecture(entry_id: int) -> Optional[LectureEntry]:
    """
    Retrieves a single lecture entry by its ID from the database.
    
    Args:
        entry_id: The unique identifier of the lecture entry to retrieve.
    
    Returns:
        A LectureEntry object containing the details of the found entry,
        or None if the entry is not found.
    """
    cursor = get_conn().cursor()
    
    # Query for lecture entry
    cursor.execute("""
        SELECT id, session_type, session_number, speaker_name, timestamp, content
        FROM lectures
        WHERE id = ?
    """, (entry_id,))
    
    row = cursor.fetchone()
    
    if not row:
        return None
    
    # Construct LectureEntry object
    return LectureEntry(
        id=row[0],
        session_type=row[1],
        session_number=row[2],
        speaker_name=row[3],
        timestamp=row[4],
        content=row[5]
    )


def get_session_context(
    entry_id: int, 
    context_size: int = 5
) -> List[LectureEntry]:
    """
    Get surrounding context for a specific entry.
    
    Args:
        entry_id: ID of the central entry
        context_size: Number of entries before and after to include
    
    Returns:
        List of LectureEntry objects in chronological order
    """
    cursor = get_conn().cursor()
    
    # First get the target entry details
    cursor.execute("""
        SELECT session_type, session_number, timestamp
        FROM lectures
        WHERE id = ?
    """, (entry_id,))
    
    target = cursor.fetchone()
    if not target:
        return []
    
    session_type, session_number, timestamp = target
    
    # Get context entries
    cursor.execute("""
        SELECT id, session_type, session_number, speaker_name, timestamp, content
        FROM lectures
        WHERE session_type = ? AND session_number = ?
        ORDER BY timestamp
    """, (session_type, session_number))
    
    all_entries = []
    target_index = -1
    
    for i, row in enumerate(cursor.fetchall()):
        entry = LectureEntry(
            id=row[0],
            session_type=row[1],
            session_number=row[2],
            speaker_name=row[3],
            timestamp=row[4],
            content=row[5]
        )
        all_entries.append(entry)
        if row[0] == entry_id:
            target_index = i
    
    # Extract context window
    if target_index >= 0:
        start = max(0, target_index - context_size)
        end = min(len(all_entries), target_index + context_size + 1)
        return all_entries[start:end]
    
    return []


def get_speaker_stats() -> dict:
    """Get statistics about speakers in the database."""
    cursor = get_conn().cursor()
    
    cursor.execute("""
        SELECT 
            speaker_name,
            COUNT(*) as entry_count,
            COUNT(DISTINCT session_type || '_' || session_number) as session_count
        FROM lectures
        GROUP BY speaker_name
        ORDER BY entry_count DESC
    """)
    
    stats = {}
    for speaker, entry_count, session_count in cursor.fetchall():
        stats[speaker] = {
            'entry_count': entry_count,
            'session_count': session_count
        }
    
    return stats


def get_session_list() -> List[dict]:
    """Get list of all sessions in the database."""
    cursor = get_conn().cursor()
    
    cursor.execute("""
        SELECT 
            session_type,
            session_number,
            COUNT(*) as entry_count,
            MIN(timestamp) as start_time,
            MAX(timestamp) as end_time,
            COUNT(DISTINCT speaker_name) as speaker_count
        FROM lectures
        GROUP BY session_type, session_number
        ORDER BY session_type, session_number
    """)
    
    sessions = []
    for row in cursor.fetchall():
        sessions.append({
            'session_type': row[0],
            'session_number': row[1],
            'entry_count': row[2],
            'start_time': row[3],
            'end_time': row[4],
            'speaker_count': row[5],
            'full_id': f"{row[0]}_{row[1]}"
        })
    
    return sessions