import sqlite3
import json
from rich import print
from rich.table import Table
from rich.console import Console

console = Console()

def view_scenarios(limit: int = 10):
    """View scenarios from the database in a formatted table."""
    conn = sqlite3.connect("scenarios.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, question, answer, entry_ids, session_type, session_number, 
               timestamp_context, how_realistic, split
        FROM scenarios
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))
    
    scenarios = cursor.fetchall()
    conn.close()
    
    if not scenarios:
        print("[yellow]No scenarios found in database.[/yellow]")
        return
    
    # Create a rich table
    table = Table(title=f"Latest {len(scenarios)} Scenarios", show_lines=True)
    table.add_column("ID", style="cyan", width=6)
    table.add_column("Question", style="yellow", width=50)
    table.add_column("Session", style="green", width=15)
    table.add_column("Realism", style="magenta", width=10)
    table.add_column("Entry IDs", style="blue", width=15)
    
    for scenario in scenarios:
        id_, question, answer, entry_ids_json, session_type, session_number, \
        timestamp_context, how_realistic, split = scenario
        
        entry_ids = json.loads(entry_ids_json)
        session = f"{session_type}-{session_number}"
        
        # Truncate question if too long
        if len(question) > 47:
            question = question[:47] + "..."
        
        table.add_row(
            str(id_),
            question,
            session,
            f"{how_realistic:.2f}",
            str(entry_ids)
        )
    
    console.print(table)
    
    # Show a sample answer
    if scenarios:
        print("\n[bold]Sample Answer (ID: {})[/bold]".format(scenarios[0][0]))
        print(scenarios[0][2][:300] + "..." if len(scenarios[0][2]) > 300 else scenarios[0][2])


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="View scenarios from database")
    parser.add_argument("--limit", type=int, default=10, help="Number of scenarios to show")
    args = parser.parse_args()
    
    view_scenarios(args.limit)