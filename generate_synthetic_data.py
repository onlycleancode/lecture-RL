from __future__ import annotations

import sqlite3
from typing import Iterator, List, Literal, Optional
import asyncio
import json
from textwrap import dedent
from pathlib import Path

from pydantic import BaseModel, Field
import litellm
from litellm import acompletion
from litellm.caching.caching import LiteLLMCacheType, Cache
from rich import print

from project_types import LectureEntry, LectureScenario

DEFAULT_DB_PATH = "lectures.db"

# Enable LiteLLM caching on disk
litellm.cache = Cache(type=LiteLLMCacheType.DISK)

SCENARIOS_DB_PATH = "scenarios.db"


class GeneratedSyntheticQuery(BaseModel):
    question: str
    answer: str
    entry_ids: List[int]
    timestamp_references: List[str] = Field(
        default_factory=list,
        description="Specific timestamps mentioned in the Q&A if any"
    )
    how_realistic: float = Field(
        ...,
        description="Score between 0 and 1 on how realistic this question is. "
                    "Consider: Would a student naturally ask this during/after the lecture?"
    )


class Response(BaseModel):
    questions: List[GeneratedSyntheticQuery]


def iterate_lecture_batches(
    session_type: Literal["lecture", "officehours"],
    session_number: int,
    *,
    batch_size: int = 10,
    db_path: str = DEFAULT_DB_PATH,
    start_after_id: Optional[int] = None,
) -> Iterator[List[LectureEntry]]:
    """Yield batches of LectureEntry objects for a specific session.
    
    Parameters
    ----------
    session_type: Type of session ('lecture' or 'officehours')
    session_number: Session number to process
    batch_size: Number of entries per batch
    db_path: Path to the lectures database
    start_after_id: Resume processing after this entry ID (exclusive)
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Get all entries for this session, ordered by timestamp
    if start_after_id is not None:
        cursor = conn.execute("""
            SELECT id, session_type, session_number, speaker_name, timestamp, content
            FROM lectures
            WHERE session_type = ? AND session_number = ? AND id > ?
            ORDER BY id ASC
        """, (session_type, session_number, start_after_id))
    else:
        cursor = conn.execute("""
            SELECT id, session_type, session_number, speaker_name, timestamp, content
            FROM lectures
            WHERE session_type = ? AND session_number = ?
            ORDER BY id ASC
        """, (session_type, session_number))
    
    batch = []
    for row in cursor:
        entry = LectureEntry(
            id=row["id"],
            session_type=row["session_type"],
            session_number=row["session_number"],
            speaker_name=row["speaker_name"],
            timestamp=row["timestamp"],
            content=row["content"]
        )
        batch.append(entry)
        
        if len(batch) >= batch_size:
            yield batch
            batch = []
    
    # Yield any remaining entries
    if batch:
        yield batch
    
    conn.close()


def _entry_to_prompt_snippet(entry: LectureEntry, idx: int) -> str:
    """Convert a lecture entry to a concise prompt snippet."""
    content_preview = entry.content.strip().replace("\n", " ")
    if len(content_preview) > 300:
        content_preview = content_preview[:300] + " …"
    
    return dedent(f"""
        Entry {idx} (ID: {entry.id})
        Time: {entry.timestamp}
        Speaker: {entry.speaker_name}
        Content: {content_preview}
    """).strip()


async def generate_qa_pairs_for_batch(
    batch: List[LectureEntry],
    session_type: str,
    session_number: int,
    *,
    num_pairs: int = 5,
    model: str = "gpt-4o-mini",
) -> List[GeneratedSyntheticQuery]:
    """Generate Q&A pairs for a batch of lecture entries using an LLM."""
    
    system_prompt = dedent(f"""
        You are creating realistic question-answer pairs that students might ask about lecture content.
        
        Context: This is {session_type} {session_number} of a reinforcement learning course.
        
        Requirements:
        1. Questions should be natural - what students would actually ask
        2. Answers MUST be directly based on the provided lecture content
        3. Include entry IDs that contain the answer
        4. If timestamps are mentioned in Q&A, include them in timestamp_references
        5. Assign realistic scores (0.8-1.0 for natural questions, 0.5-0.7 for awkward ones)
        
        Types of good questions:
        - Clarification questions about concepts
        - Questions about specific examples or equations
        - Questions about what the professor said at a specific time
        - Questions connecting different parts of the lecture
        
        Respond with this JSON structure:
        {Response.model_json_schema()}
    """).strip()
    
    # Build lecture content snippets
    entry_snippets = "\n---\n".join(
        _entry_to_prompt_snippet(entry, idx=i + 1) 
        for i, entry in enumerate(batch)
    )
    
    user_prompt = dedent(f"""
        Here are {len(batch)} consecutive entries from {session_type} {session_number}:
        ---
        {entry_snippets}
        ---
        
        Generate {num_pairs} diverse, realistic question-answer pairs about this content.
        Remember to reference the specific entry IDs that contain the answer.
    """).strip()
    
    response = await acompletion(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.8,
        caching=True,
        response_format={"type": "json_object"},
    )
    
    content = response.choices[0].message.content
    qa_pairs = Response.model_validate_json(content).questions
    
    return qa_pairs


def get_last_processed_entry_id(
    session_type: str,
    session_number: int,
    db_path: str = SCENARIOS_DB_PATH
) -> Optional[int]:
    """Get the highest entry ID that has been processed for this session."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Query to find the maximum entry_id from all scenarios for this session
    result = cursor.execute("""
        SELECT MAX(CAST(entry_id AS INTEGER)) as max_id
        FROM (
            SELECT json_each.value as entry_id
            FROM scenarios, json_each(scenarios.entry_ids)
            WHERE session_type = ? AND session_number = ?
        )
    """, (session_type, session_number)).fetchone()
    
    conn.close()
    return result[0] if result and result[0] is not None else None


def save_scenarios_to_db(
    scenarios: List[LectureScenario],
    db_path: str = SCENARIOS_DB_PATH
):
    """Save scenarios to the SQLite database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    for scenario in scenarios:
        cursor.execute("""
            INSERT INTO scenarios 
            (id, question, answer, entry_ids, session_type, session_number, 
             timestamp_context, how_realistic, split)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            scenario.id,
            scenario.question,
            scenario.answer,
            json.dumps(scenario.entry_ids),
            scenario.session_type,
            scenario.session_number,
            scenario.timestamp_context,
            scenario.how_realistic,
            scenario.split
        ))
    
    conn.commit()
    conn.close()


async def generate_scenarios_for_session(
    session_type: Literal["lecture", "officehours"],
    session_number: int,
    split: Literal["train", "test"] = "train",
    *,
    max_scenarios: int = 5,
    batch_size: int = 10,
    model: str = "gpt-4o-mini",
    resume: bool = True,
) -> List[LectureScenario]:
    """Generate scenarios for a specific lecture session.
    
    Parameters
    ----------
    resume: If True, skip already processed entries
    """
    
    print(f"[blue]Generating scenarios for {session_type} {session_number}[/blue]")
    
    scenarios = []
    scenario_id = 0
    
    # Get existing max ID from database
    conn = sqlite3.connect(SCENARIOS_DB_PATH)
    cursor = conn.execute("SELECT MAX(id) FROM scenarios")
    max_id = cursor.fetchone()[0]
    if max_id is not None:
        scenario_id = max_id + 1
    conn.close()
    
    # Check where we left off if resuming
    start_after_id = None
    if resume:
        start_after_id = get_last_processed_entry_id(session_type, session_number)
        if start_after_id is not None:
            print(f"[yellow]Resuming from entry ID {start_after_id}[/yellow]")
    
    for batch_idx, batch in enumerate(iterate_lecture_batches(
        session_type, session_number, batch_size=batch_size, start_after_id=start_after_id
    )):
        if len(scenarios) >= max_scenarios:
            break
            
        print(f"  Processing batch {batch_idx + 1} ({len(batch)} entries)...")
        
        # Calculate how many Q&A pairs to generate for this batch
        remaining = max_scenarios - len(scenarios)
        pairs_to_generate = min(5, remaining)
        
        qa_pairs = await generate_qa_pairs_for_batch(
            batch,
            session_type,
            session_number,
            num_pairs=pairs_to_generate,
            model=model
        )
        
        for qa in qa_pairs:
            if len(scenarios) >= max_scenarios:
                break
                
            # Extract timestamp context if mentioned
            timestamp_context = None
            if qa.timestamp_references:
                timestamp_context = f"around {qa.timestamp_references[0]}"
            
            scenario = LectureScenario(
                id=scenario_id,
                question=qa.question,
                answer=qa.answer,
                entry_ids=qa.entry_ids,
                session_type=session_type,
                session_number=session_number,
                timestamp_context=timestamp_context,
                how_realistic=qa.how_realistic,
                split=split
            )
            scenarios.append(scenario)
            scenario_id += 1
    
    print(f"[green]Generated {len(scenarios)} scenarios[/green]")
    return scenarios


async def main():
    """Main entry point for testing scenario generation."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Generate synthetic Q&A scenarios for lecture content"
    )
    parser.add_argument(
        "--session-type", 
        choices=["lecture", "officehours"], 
        default="lecture",
        help="Type of session to process"
    )
    parser.add_argument(
        "--session-number",
        type=int,
        default=1,
        help="Session number to process"
    )
    parser.add_argument(
        "--split",
        choices=["train", "test"],
        default="train",
        help="Dataset split for the scenarios"
    )
    parser.add_argument(
        "--max-scenarios",
        type=int,
        default=5,
        help="Maximum number of scenarios to generate"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Number of lecture entries per batch"
    )
    parser.add_argument(
        "--model",
        default="gpt-4o-mini",
        help="LLM model to use for generation"
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Start from beginning even if entries were already processed"
    )
    
    args = parser.parse_args()
    
    # Ensure scenarios database exists
    if not Path(SCENARIOS_DB_PATH).exists():
        print("[yellow]Scenarios database not found. Creating...[/yellow]")
        from setup_scenarios_db import create_scenarios_database
        create_scenarios_database()
    
    # Generate scenarios
    scenarios = await generate_scenarios_for_session(
        session_type=args.session_type,
        session_number=args.session_number,
        split=args.split,
        max_scenarios=args.max_scenarios,
        batch_size=args.batch_size,
        model=args.model,
        resume=not args.no_resume
    )
    
    # Save to database
    if scenarios:
        save_scenarios_to_db(scenarios)
        print(f"[green]Saved {len(scenarios)} scenarios to {SCENARIOS_DB_PATH}[/green]")
        
        # Display sample
        print("\n[bold]Sample generated scenarios:[/bold]")
        for scenario in scenarios[:2]:
            print(f"\nQ: {scenario.question}")
            print(f"A: {scenario.answer[:200]}...")
            print(f"Realism: {scenario.how_realistic:.2f}")
            print(f"Entry IDs: {scenario.entry_ids}")


if __name__ == "__main__":
    asyncio.run(main())