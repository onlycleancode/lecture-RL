#!/usr/bin/env python3
"""
Script to import lecture transcripts into SQLite database with FTS5 support.
"""

import sqlite3
import os
from pathlib import Path
from typing import List, Tuple
import re


def create_database(db_path: str) -> sqlite3.Connection:
    """Create SQLite database with FTS5 virtual table for full-text search."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create main table for storing lecture data
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lectures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_type TEXT NOT NULL,
            session_number INTEGER,
            speaker_name TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            content TEXT NOT NULL,
            UNIQUE(session_type, session_number, timestamp, speaker_name)
        )
    """)
    
    # Create FTS5 virtual table for full-text search
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS lectures_fts USING fts5(
            speaker_name,
            timestamp,
            content,
            content_rowid=id,
            tokenize='porter unicode61'
        )
    """)
    
    # Create triggers to keep FTS table in sync with main table
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS lectures_ai AFTER INSERT ON lectures BEGIN
            INSERT INTO lectures_fts(rowid, speaker_name, timestamp, content)
            VALUES (new.id, new.speaker_name, new.timestamp, new.content);
        END
    """)
    
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS lectures_ad AFTER DELETE ON lectures BEGIN
            DELETE FROM lectures_fts WHERE rowid = old.id;
        END
    """)
    
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS lectures_au AFTER UPDATE ON lectures BEGIN
            UPDATE lectures_fts 
            SET speaker_name = new.speaker_name,
                timestamp = new.timestamp,
                content = new.content
            WHERE rowid = new.id;
        END
    """)
    
    conn.commit()
    return conn


def parse_lecture_file(file_path: Path) -> List[Tuple[str, str, str, str, int]]:
    """Parse a lecture markdown file and extract speaker, timestamp, and content."""
    entries = []
    
    # Determine session type and number from filename
    if 'officehours' in file_path.name:
        session_type = 'officehours'
        match = re.search(r'officehours(\d+)\.md', file_path.name)
        session_number = int(match.group(1)) if match else 0
    else:
        session_type = 'lecture'
        match = re.search(r'lecture(\d+)\.md', file_path.name)
        session_number = int(match.group(1)) if match else 0
    
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    i = 0
    while i < len(lines):
        # Skip empty lines
        if not lines[i].strip():
            i += 1
            continue
        
        # Check if this line is a speaker name
        if i + 2 < len(lines):
            speaker_name = lines[i].strip()
            timestamp = lines[i + 1].strip()
            
            # Validate timestamp format (HH:MM:SS or MM:SS)
            if re.match(r'^\d{1,2}:\d{2}:\d{2}$', timestamp) or re.match(r'^\d{2}:\d{2}$', timestamp):
                # Convert MM:SS to HH:MM:SS format
                if len(timestamp.split(':')) == 2:
                    timestamp = '00:' + timestamp
                
                # Find content - it starts from line i+2 and continues until next speaker or EOF
                content_lines = []
                j = i + 2
                
                while j < len(lines):
                    # Check if we've hit the next speaker entry
                    if (j + 2 < len(lines) and 
                        lines[j].strip() and 
                        (re.match(r'^\d{1,2}:\d{2}:\d{2}$', lines[j + 1].strip()) or 
                         re.match(r'^\d{2}:\d{2}$', lines[j + 1].strip()))):
                        break
                    
                    # Add non-empty lines to content
                    if lines[j].strip():
                        content_lines.append(lines[j].strip())
                    j += 1
                
                content = ' '.join(content_lines)
                if content:  # Only add entries with actual content
                    entries.append((session_type, speaker_name, timestamp, content, session_number))
                
                i = j
                continue
        
        i += 1
    
    return entries


def import_lectures(transcript_dir: str, db_path: str):
    """Import all lecture files from the transcript directory into the database."""
    conn = create_database(db_path)
    cursor = conn.cursor()
    
    transcript_path = Path(transcript_dir)
    # Get both lecture and office hours files
    lecture_files = sorted(transcript_path.glob('lecture*.md'))
    officehours_files = sorted(transcript_path.glob('officehours*.md'))
    all_files = lecture_files + officehours_files
    
    total_entries = 0
    
    for file_path in all_files:
        print(f"Processing {file_path.name}...")
        entries = parse_lecture_file(file_path)
        
        for session_type, speaker_name, timestamp, content, session_number in entries:
            try:
                cursor.execute("""
                    INSERT OR IGNORE INTO lectures (session_type, session_number, speaker_name, timestamp, content)
                    VALUES (?, ?, ?, ?, ?)
                """, (session_type, session_number, speaker_name, timestamp, content))
                total_entries += cursor.rowcount
            except sqlite3.Error as e:
                print(f"Error inserting entry: {e}")
                print(f"  Speaker: {speaker_name}, Timestamp: {timestamp}")
        
        conn.commit()
        print(f"  Added {len(entries)} entries from {file_path.name}")
    
    print(f"\nTotal entries imported: {total_entries}")
    
    # Verify FTS is working
    cursor.execute("SELECT COUNT(*) FROM lectures_fts")
    fts_count = cursor.fetchone()[0]
    print(f"FTS table contains: {fts_count} entries")
    
    conn.close()


def search_lectures(db_path: str, query: str):
    """Example function to demonstrate FTS5 search capabilities."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Search using FTS5
    cursor.execute("""
        SELECT l.session_type, l.session_number, l.speaker_name, l.timestamp, snippet(lectures_fts, 2, '[', ']', '...', 10)
        FROM lectures l
        JOIN lectures_fts ON l.id = lectures_fts.rowid
        WHERE lectures_fts MATCH ?
        ORDER BY rank
        LIMIT 10
    """, (query,))
    
    results = cursor.fetchall()
    conn.close()
    
    return results


if __name__ == "__main__":
    # Set up paths
    project_root = Path(__file__).parent
    transcript_dir = project_root / "lecture-transcript"
    db_path = project_root / "lectures.db"
    
    # Import lectures
    import_lectures(str(transcript_dir), str(db_path))
    
    # Example search
    print("\nExample search for 'agent':")
    results = search_lectures(str(db_path), "agent")
    for session_type, session_num, speaker, timestamp, snippet in results[:5]:
        print(f"{session_type.capitalize()} {session_num} - {speaker} [{timestamp}]: {snippet}")