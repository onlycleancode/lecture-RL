from project_types import LectureScenario
from typing import List, Optional, Literal
import sqlite3
import json
import random

# Define the database path
SCENARIOS_DB_PATH = "scenarios.db"


def load_scenarios(
    split: Literal["train", "test"] = "train",
    limit: Optional[int] = None,
    shuffle: bool = False,
    seed: Optional[int] = None,
) -> List[LectureScenario]:
    """Load scenarios from the local SQLite database."""
    
    conn = sqlite3.connect(SCENARIOS_DB_PATH)
    cursor = conn.cursor()
    
    # Build query
    query = """
        SELECT id, question, answer, entry_ids, session_type, session_number, 
               timestamp_context, how_realistic, split
        FROM scenarios
        WHERE split = ?
    """
    params = [split]
    
    # Add limit if specified
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    # Convert rows to LectureScenario objects
    scenarios = []
    for row in rows:
        id_, question, answer, entry_ids_json, session_type, session_number, \
        timestamp_context, how_realistic, split_val = row
        
        # Parse JSON entry_ids
        entry_ids = json.loads(entry_ids_json)
        
        scenario = LectureScenario(
            id=id_,
            question=question,
            answer=answer,
            entry_ids=entry_ids,
            session_type=session_type,
            session_number=session_number,
            timestamp_context=timestamp_context,
            how_realistic=how_realistic,
            split=split_val
        )
        scenarios.append(scenario)
    
    # Handle shuffling
    if shuffle:
        if seed is not None:
            rng = random.Random(seed)
            rng.shuffle(scenarios)
        else:
            random.shuffle(scenarios)
    
    return scenarios


if __name__ == "__main__":
    from rich import print

    scenarios = load_scenarios(limit=5)
    print(scenarios)