"""Database operations for lecture transcripts."""

import sqlite3
from pathlib import Path
from typing import List, Optional
import re
from project_types import LectureEntry


class LectureDatabase:
    """Manages the local SQLite database for lecture transcripts."""
    
    def __init__(self, db_path: str = "lectures.db"):
        self.db_path = Path(db_path)
        self.ensure_database()
    
    def ensure_database(self):
        """Ensure the database exists with proper schema."""
        if not self.db_path.exists():
            self.create_database()
    
    def create_database(self):
        """Create the database schema with FTS5 support."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        # Create main table
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
        
        # Create FTS5 virtual table
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS lectures_fts USING fts5(
                speaker_name,
                timestamp,
                content,
                content_rowid=id,
                tokenize='porter unicode61'
            )
        """)
        
        # Create indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_session 
            ON lectures(session_type, session_number)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_speaker 
            ON lectures(speaker_name)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp 
            ON lectures(timestamp)
        """)
        
        # Create triggers to maintain FTS
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
        conn.close()
    
    def add_entry(self, entry: LectureEntry) -> Optional[int]:
        """Add a single lecture entry to the database."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO lectures 
                (session_type, session_number, speaker_name, timestamp, content)
                VALUES (?, ?, ?, ?, ?)
            """, (
                entry.session_type,
                entry.session_number,
                entry.speaker_name,
                entry.timestamp,
                entry.content
            ))
            
            conn.commit()
            entry_id = cursor.lastrowid if cursor.rowcount > 0 else None
            conn.close()
            return entry_id
            
        except sqlite3.Error as e:
            print(f"Error adding entry: {e}")
            conn.close()
            return None
    
    def add_entries_batch(self, entries: List[LectureEntry]) -> int:
        """Add multiple lecture entries in a batch."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        added_count = 0
        for entry in entries:
            try:
                cursor.execute("""
                    INSERT OR IGNORE INTO lectures 
                    (session_type, session_number, speaker_name, timestamp, content)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    entry.session_type,
                    entry.session_number,
                    entry.speaker_name,
                    entry.timestamp,
                    entry.content
                ))
                added_count += cursor.rowcount
            except sqlite3.Error as e:
                print(f"Error adding entry: {e}")
        
        conn.commit()
        conn.close()
        return added_count
    
    def import_from_markdown(self, file_path: Path) -> int:
        """Import lecture entries from a markdown file."""
        entries = self.parse_markdown_file(file_path)
        return self.add_entries_batch(entries)
    
    @staticmethod
    def parse_markdown_file(file_path: Path) -> List[LectureEntry]:
        """Parse a lecture markdown file into LectureEntry objects."""
        entries = []
        
        # Determine session type and number
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
            
            # Check if this is a speaker entry
            if i + 2 < len(lines):
                speaker_name = lines[i].strip()
                timestamp = lines[i + 1].strip()
                
                # Validate timestamp
                if re.match(r'^\d{1,2}:\d{2}:\d{2}$', timestamp) or re.match(r'^\d{2}:\d{2}$', timestamp):
                    # Normalize timestamp to HH:MM:SS
                    if len(timestamp.split(':')) == 2:
                        timestamp = '00:' + timestamp
                    
                    # Collect content
                    content_lines = []
                    j = i + 2
                    
                    while j < len(lines):
                        # Check if we've hit the next speaker
                        if (j + 2 < len(lines) and 
                            lines[j].strip() and 
                            (re.match(r'^\d{1,2}:\d{2}:\d{2}$', lines[j + 1].strip()) or 
                             re.match(r'^\d{2}:\d{2}$', lines[j + 1].strip()))):
                            break
                        
                        if lines[j].strip():
                            content_lines.append(lines[j].strip())
                        j += 1
                    
                    content = ' '.join(content_lines)
                    if content:
                        entries.append(LectureEntry(
                            session_type=session_type,
                            session_number=session_number,
                            speaker_name=speaker_name,
                            timestamp=timestamp,
                            content=content
                        ))
                    
                    i = j
                    continue
            
            i += 1
        
        return entries
    
    def get_statistics(self) -> dict:
        """Get database statistics."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        stats = {}
        
        # Total entries
        cursor.execute("SELECT COUNT(*) FROM lectures")
        stats['total_entries'] = cursor.fetchone()[0]
        
        # Entries by session type
        cursor.execute("""
            SELECT session_type, COUNT(*) 
            FROM lectures 
            GROUP BY session_type
        """)
        stats['by_session_type'] = dict(cursor.fetchall())
        
        # Number of unique sessions
        cursor.execute("""
            SELECT COUNT(DISTINCT session_type || '_' || session_number) 
            FROM lectures
        """)
        stats['unique_sessions'] = cursor.fetchone()[0]
        
        # Number of unique speakers
        cursor.execute("SELECT COUNT(DISTINCT speaker_name) FROM lectures")
        stats['unique_speakers'] = cursor.fetchone()[0]
        
        # FTS index size
        cursor.execute("SELECT COUNT(*) FROM lectures_fts")
        stats['fts_entries'] = cursor.fetchone()[0]
        
        conn.close()
        return stats
    
    def clear_database(self):
        """Clear all data from the database."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM lectures")
        conn.commit()
        conn.close()
    
    def rebuild_fts_index(self):
        """Rebuild the FTS index from scratch."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        # Delete and recreate FTS table
        cursor.execute("DROP TABLE IF EXISTS lectures_fts")
        
        cursor.execute("""
            CREATE VIRTUAL TABLE lectures_fts USING fts5(
                speaker_name,
                timestamp,
                content,
                content_rowid=id,
                tokenize='porter unicode61'
            )
        """)
        
        # Repopulate FTS
        cursor.execute("""
            INSERT INTO lectures_fts(rowid, speaker_name, timestamp, content)
            SELECT id, speaker_name, timestamp, content FROM lectures
        """)
        
        conn.commit()
        conn.close()