"""Search tools for querying lecture transcripts."""

import sqlite3
from typing import List, Optional, Tuple
from pathlib import Path
from project_types import LectureEntry
from dataclasses import dataclass
from typing import Optional
import os

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
    session_type: Optional[str] = None,
    session_number: Optional[int] = None,
    speaker_name: Optional[str] = None,
    date_after: Optional[str] = None,
    date_before: Optional[str] = None,
    max_results: int = 10
) -> List[SearchResult]:
    """
    Search lecture transcripts based on keywords and/or filters.
    
    Args:
        keywords: Optional list of keywords that must all appear in the content
        session_type: Optional filter by 'lecture' or 'officehours'
        session_number: Optional session number to filter by
        speaker_name: Optional speaker name to filter by
        date_after: Optional timestamp filter 'HH:MM:SS'
        date_before: Optional timestamp filter 'HH:MM:SS'
        max_results: Maximum number of results to return (max 10)
    
    Returns:
        List of SearchResult objects
    """
    # Validate inputs
    if max_results > 10:
        raise ValueError("max_results must be less than or equal to 10.")
    
    cursor = get_conn().cursor()
    
    # Build the query
    where_clauses = []
    params = []
    
    # If keywords provided, use FTS search
    if keywords:
        # Build FTS query from keywords list (similar to email_search)
        # FTS5 default is AND, so just join keywords. Escape quotes for safety.
        fts_query = " ".join(f""" "{k.replace('"', '""')}" """ for k in keywords)
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
    
    # Construct final query based on whether we have keywords
    if keywords:
        # Query with FTS join
        sql = f"""
            SELECT 
                l.id,
                l.session_type,
                l.session_number,
                l.speaker_name,
                l.timestamp,
                snippet(lectures_fts, -1, '<b>', '</b>', ' ... ', 15) as snippet
            FROM lectures l 
            JOIN lectures_fts fts ON l.id = fts.rowid
            WHERE {" AND ".join(where_clauses)}
            ORDER BY rank
            LIMIT ?;
        """
    else:
        # Query without FTS when no keywords
        if not where_clauses:
            where_clauses.append("1=1")  # Ensure valid SQL
        
        sql = f"""
            SELECT 
                l.id,
                l.session_type,
                l.session_number,
                l.speaker_name,
                l.timestamp,
                substr(l.content, 1, 150) || '...' as snippet
            FROM lectures l
            WHERE {" AND ".join(where_clauses)}
            ORDER BY l.session_type, l.session_number, l.timestamp
            LIMIT ?;
        """
    params.append(max_results)
    
    # Execute query
    cursor.execute(sql, params)
    results = cursor.fetchall()
    
    # Format results
    formatted_results = [
        SearchResult(
            entry_id=row[0],
            session_type=row[1],
            session_number=row[2],
            speaker_name=row[3],
            timestamp=row[4],
            snippet=row[5]
        ) for row in results
    ]
    
    return formatted_results


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