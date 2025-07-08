import sqlite3
from pathlib import Path

SCENARIOS_DB_PATH = "scenarios.db"

def create_scenarios_database():
    """Create the scenarios database with proper schema."""
    
    # Remove existing database if it exists
    if Path(SCENARIOS_DB_PATH).exists():
        Path(SCENARIOS_DB_PATH).unlink()
    
    conn = sqlite3.connect(SCENARIOS_DB_PATH)
    cursor = conn.cursor()
    
    # Create scenarios table
    cursor.execute("""
        CREATE TABLE scenarios (
            id INTEGER PRIMARY KEY,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            entry_ids TEXT NOT NULL,  -- JSON array of entry IDs
            session_type TEXT NOT NULL CHECK (session_type IN ('lecture', 'officehours')),
            session_number INTEGER NOT NULL,
            timestamp_context TEXT,
            how_realistic REAL NOT NULL CHECK (how_realistic >= 0 AND how_realistic <= 1),
            split TEXT NOT NULL CHECK (split IN ('train', 'test')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create indices for efficient querying
    cursor.execute("CREATE INDEX idx_scenarios_split ON scenarios(split)")
    cursor.execute("CREATE INDEX idx_scenarios_session ON scenarios(session_type, session_number)")
    cursor.execute("CREATE INDEX idx_scenarios_realistic ON scenarios(how_realistic)")
    
    conn.commit()
    conn.close()
    print(f"Created scenarios database at {SCENARIOS_DB_PATH}")

if __name__ == "__main__":
    create_scenarios_database()