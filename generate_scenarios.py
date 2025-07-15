#!/usr/bin/env python
"""Generate train/test scenarios for lectures and office hours."""

import asyncio
import subprocess
from rich import print
from typing import List, Tuple, Literal

# Default session configurations
DEFAULT_TRAIN_SESSIONS = [
    # Lectures - 80 scenarios each for training
    ("lecture", 1, 80),
    ("lecture", 2, 80),
    ("lecture", 3, 80),
    ("lecture", 4, 80),
    ("lecture", 5, 80),
    ("lecture", 6, 80),
    # Office Hours - 40 scenarios each for training
    ("officehours", 1, 40),
    ("officehours", 2, 40),
    ("officehours", 3, 40),
    ("officehours", 4, 40),
]

DEFAULT_TEST_SESSIONS = [
    # Lectures - 10 scenarios each for testing
    ("lecture", 1, 10),
    ("lecture", 2, 10),
    ("lecture", 3, 10),
    ("lecture", 4, 10),
    ("lecture", 5, 10),
    ("lecture", 6, 10),
    # Office Hours - 5 scenarios each for testing
    ("officehours", 1, 5),
    ("officehours", 2, 5),
    ("officehours", 3, 5),
    ("officehours", 4, 5),
]


async def generate_scenarios_for_session(
    session_type: str, 
    session_number: int, 
    count: int,
    split: Literal["train", "test"] = "train"
):
    """Generate scenarios for a single session."""
    print(f"\n[blue]Generating {count} {split} scenarios for {session_type} {session_number}[/blue]")
    
    cmd = [
        "uv", "run", "python", "generate_synthetic_data.py",
        "--session-type", session_type,
        "--session-number", str(session_number),
        "--split", split,
        "--max-scenarios", str(count),
        "--batch-size", "10"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"[green]✓ Completed {session_type} {session_number} ({split})[/green]")
        else:
            print(f"[red]✗ Failed {session_type} {session_number}: {result.stderr}[/red]")
            if result.stdout:
                print(f"[yellow]stdout: {result.stdout}[/yellow]")
    except Exception as e:
        print(f"[red]✗ Error with {session_type} {session_number}: {e}[/red]")


def check_existing_scenarios(split: Literal["train", "test"]) -> dict:
    """Check existing scenarios in the database."""
    result = subprocess.run([
        "sqlite3", "scenarios.db", "-json",
        f"SELECT session_type, session_number, COUNT(*) as count FROM scenarios WHERE split='{split}' GROUP BY session_type, session_number;"
    ], capture_output=True, text=True)
    
    existing = {}
    if result.returncode == 0 and result.stdout.strip():
        import json
        data = json.loads(result.stdout)
        for row in data:
            key = (row["session_type"], row["session_number"])
            existing[key] = row["count"]
    
    return existing


async def generate_scenarios(
    sessions: List[Tuple[str, int, int]],
    split: Literal["train", "test"] = "train",
    skip_existing: bool = True
):
    """Generate scenarios for multiple sessions."""
    
    if skip_existing:
        existing = check_existing_scenarios(split)
        sessions_to_process = []
        
        for session_type, session_number, target_count in sessions:
            key = (session_type, session_number)
            current_count = existing.get(key, 0)
            
            if current_count >= target_count:
                print(f"[yellow]Skipping {session_type} {session_number} - already has {current_count}/{target_count} {split} scenarios[/yellow]")
            else:
                needed = target_count - current_count
                print(f"[cyan]{session_type} {session_number} needs {needed} more {split} scenarios (has {current_count}/{target_count})[/cyan]")
                sessions_to_process.append((session_type, session_number, needed))
    else:
        sessions_to_process = sessions
    
    # Process sessions
    for session_type, session_number, count in sessions_to_process:
        await generate_scenarios_for_session(session_type, session_number, count, split)
        # Small delay to avoid rate limits
        await asyncio.sleep(1)


async def main():
    """Main entry point for scenario generation."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Generate train/test scenarios for lecture content"
    )
    parser.add_argument(
        "--split",
        choices=["train", "test", "both"],
        default="both",
        help="Which split to generate scenarios for"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Generate scenarios even if they already exist"
    )
    parser.add_argument(
        "--sessions",
        nargs="+",
        help="Specific sessions to generate (e.g., lecture-1 officehours-2)"
    )
    
    args = parser.parse_args()
    
    # Check database state
    print("[bold]Current database state:[/bold]")
    subprocess.run([
        "sqlite3", "scenarios.db",
        "SELECT split, COUNT(*) as total FROM scenarios GROUP BY split;"
    ])
    
    print("\n[bold]Scenarios by session:[/bold]")
    subprocess.run([
        "sqlite3", "scenarios.db",
        "SELECT split, session_type || '-' || session_number as session, COUNT(*) as count FROM scenarios GROUP BY split, session_type, session_number ORDER BY split, session_type, session_number;"
    ])
    
    # Parse specific sessions if provided
    if args.sessions:
        train_sessions = []
        test_sessions = []
        
        for session in args.sessions:
            parts = session.split("-")
            if len(parts) == 2:
                session_type = parts[0]
                session_number = int(parts[1])
                
                # Find default counts for this session
                if args.split in ["train", "both"]:
                    for s_type, s_num, count in DEFAULT_TRAIN_SESSIONS:
                        if s_type == session_type and s_num == session_number:
                            train_sessions.append((s_type, s_num, count))
                            break
                
                if args.split in ["test", "both"]:
                    for s_type, s_num, count in DEFAULT_TEST_SESSIONS:
                        if s_type == session_type and s_num == session_number:
                            test_sessions.append((s_type, s_num, count))
                            break
    else:
        train_sessions = DEFAULT_TRAIN_SESSIONS if args.split in ["train", "both"] else []
        test_sessions = DEFAULT_TEST_SESSIONS if args.split in ["test", "both"] else []
    
    # Generate scenarios
    if train_sessions:
        print(f"\n[bold]Generating TRAIN scenarios[/bold]")
        await generate_scenarios(train_sessions, "train", skip_existing=not args.force)
    
    if test_sessions:
        print(f"\n[bold]Generating TEST scenarios[/bold]")
        await generate_scenarios(test_sessions, "test", skip_existing=not args.force)
    
    # Show final statistics
    print("\n[bold]Final statistics:[/bold]")
    subprocess.run([
        "sqlite3", "scenarios.db",
        "SELECT split, COUNT(*) as total FROM scenarios GROUP BY split;"
    ])
    
    print("\n[bold]Detailed breakdown:[/bold]")
    subprocess.run([
        "sqlite3", "scenarios.db", "-column", "-header",
        "SELECT split, session_type || '-' || session_number as session, COUNT(*) as count FROM scenarios GROUP BY split, session_type, session_number ORDER BY split, session_type, session_number;"
    ])


if __name__ == "__main__":
    asyncio.run(main())