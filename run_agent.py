from pydantic import BaseModel, Field
import weave
from litellm import acompletion
from rich import print
from rich.console import Console
from rich.panel import Panel
from textwrap import dedent
from dotenv import load_dotenv
import json
import os
from dataclasses import asdict
import asyncio
from typing import Optional

from lecture_search_tools import search_lectures, read_lecture, get_speaker_stats, get_session_list
from langchain_core.utils.function_calling import convert_to_openai_tool
from project_types import Scenario


load_dotenv()
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")

console = Console()

MAX_TURNS = 10

weave.init(project_name="lecture-rl")


class FinalAnswer(BaseModel):
    answer: str
    source_entry_ids: list[int]


@weave.op()
async def run_agent_with_tools(question: str) -> dict:
    """
    Run agent with access to lecture search tools
    """
    system_prompt = dedent(f"""
        You are a lecture search agent. You are given a user query and a list of tools you can use to search lecture transcripts.
        Use the tools to search the lecture database and find the answer to the user's query. 
        
        The database contains transcripts from reinforcement learning lectures and office hours sessions.
        Each entry has a speaker, timestamp (HH:MM:SS format), content, session type, and session number.
        
        SEARCH STRATEGY:
        1. Start with ONE targeted search using appropriate filters
        2. Read only the MOST RELEVANT 3-5 entries from search results
        3. If you have enough information to answer, provide the final answer immediately
        4. If after 2-3 searches you find NO results, state that the information is not in the database
        5. Be DECISIVE - don't keep searching endlessly. Either answer with what you found or state it's not available
        
        SEARCH FILTERS:
        - session_type: 'lecture' or 'officehours' 
        - session_number: e.g., 2 for "office hours 2" or "lecture 2"
        - speaker_name: filter by specific speaker
        - time_after/time_before: filter by timestamp ranges (HH:MM:SS format)
        - keywords: search for specific terms in content
        
        IMPORTANT:
        - For queries about specific sessions, use session filters NOT keywords
        - For queries about specific times, use time filters NOT keywords  
        - Timestamps: "00:10:00" = 10 minutes, "00:30:00" = 30 minutes, etc.
        - You have {MAX_TURNS} turns maximum, but AIM TO ANSWER IN 2-3 TURNS
    """).strip()
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question}
    ]
    
    
    def search_lecture_database(
        keywords: Optional[list[str]] = None,
        session_type: Optional[str] = None,
        session_number: Optional[int] = None,
        speaker_name: Optional[str] = None,
        time_after: Optional[str] = None,
        time_before: Optional[str] = None
    ) -> list[dict]:
        """Search the lecture database for entries matching the given criteria.
        
        Args:
            keywords: Optional list of keywords to search for in content
            session_type: Optional filter by 'lecture' or 'officehours'
            session_number: Optional session number (e.g., 2 for "office hours 2")
            speaker_name: Optional speaker name to filter by
            time_after: Optional timestamp filter 'HH:MM:SS' - find entries after this time
            time_before: Optional timestamp filter 'HH:MM:SS' - find entries before this time
        """
        try:
            results = search_lectures(
                keywords=keywords,
                session_type=session_type,
                session_number=session_number,
                speaker_name=speaker_name,
                date_after=time_after,
                date_before=time_before,
                max_results=10
            )
            return [asdict(result) for result in results]
        except Exception as e:
            return [{"error": str(e)}]
    
    def get_available_sessions() -> list[dict]:
        """Get a list of all available sessions in the database with their time ranges."""
        return get_session_list()
    
    def return_final_answer(
        answer: str, source_entry_ids: list[int]
    ) -> FinalAnswer:
        """Return the final answer and the entry IDs that were used to generate the answer."""
        return FinalAnswer(answer=answer, source_entry_ids=source_entry_ids)
    
    tools = [search_lecture_database, read_lecture, get_available_sessions, return_final_answer]
    tools_by_name = {t.__name__: t for t in tools}
    openai_tools = [convert_to_openai_tool(t) for t in tools]
    
    final_answer = None
    search_count = 0
    read_count = 0
    
    for turn in range(MAX_TURNS):
        console.print(f"\n[dim]Turn {turn + 1}/{MAX_TURNS}[/dim]")
        
        response = await acompletion(
            model="gpt-4.1",
            messages=messages,
            temperature=0.7,
            tools=openai_tools
        )
        
        response_message = response.choices[0].message
        
        # Properly format the assistant message with tool calls
        assistant_message = {
            "role": "assistant",
            "content": response_message.content
        }
        
        # Add tool_calls if present
        if hasattr(response_message, 'tool_calls') and response_message.tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments
                    }
                } for tool_call in response_message.tool_calls
            ]
        
        messages.append(assistant_message)
        
        # Check if there are no tool calls
        if not hasattr(response_message, 'tool_calls') or not response_message.tool_calls:
            if response_message.content:
                console.print(f"[yellow]Agent response:[/yellow] {response_message.content}")
            break
        
        # Process tool calls
        if hasattr(response_message, 'tool_calls') and response_message.tool_calls:
            for tool_call in response_message.tool_calls:
                tool_name = tool_call.function.name
                console.print(f"[blue]Calling tool:[/blue] {tool_name}")
                
                if tool_name in tools_by_name:
                    try:
                        tool_args = json.loads(tool_call.function.arguments)
                        console.print(f"[dim]Arguments: {tool_args}[/dim]")
                        
                        tool_to_call = tools_by_name[tool_name]
                        result = tool_to_call(**tool_args)
                        
                        # Track tool usage
                        if tool_name == "search_lecture_database":
                            search_count += 1
                            if search_count >= 3 and not result:
                                console.print(f"[yellow italic]Note: Multiple searches with no results. Consider providing a general answer.[/yellow italic]")
                        elif tool_name == "read_lecture":
                            read_count += 1
                        
                        tool_message = {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": str(result)
                        }
                        
                        # Add guidance for being decisive
                        if search_count >= 2 and len(str(result)) > 10:
                            tool_message["content"] += "\n\nREMINDER: You've done multiple searches. If you have relevant information, provide an answer now rather than continuing to search."
                        elif search_count >= 3 and not result:
                            tool_message["content"] += "\n\nIMPORTANT: You've searched 3+ times with no results. The information is not in the database. Please provide a final answer stating this."
                        
                        messages.append(tool_message)
                        
                        if tool_name == "return_final_answer":
                            final_answer = result
                            console.print(f"[green]Final answer provided[/green]")
                            break
                        
                        # Encourage decisiveness after reading entries
                        if tool_name == "read_lecture" and read_count >= 3:
                            console.print(f"[dim italic]You've read {read_count} entries. Consider answering now.[/dim italic]")
                            
                    except Exception as e:
                        console.print(f"[red]Error calling tool {tool_name}: {e}[/red]")
                        error_message = {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": f"Error: {str(e)}"
                        }
                        messages.append(error_message)
        
        if final_answer:
            break
    
    return {
        "final_answer": final_answer,
        "messages": messages,
        "turns_used": turn + 1
    }


async def main():
    """Main async function to handle user input and LLM interaction"""
    console.print("[bold cyan]🤖 RL Lecture Search Assistant[/bold cyan]")
    console.print("I can search through reinforcement learning lecture transcripts to answer your questions.")
    console.print("Type 'quit' or 'exit' to stop\n")
    
    while True:
        # Get user input
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]Goodbye![/yellow]")
            break
            
        if user_input.lower() in ['quit', 'exit']:
            console.print("[yellow]Goodbye![/yellow]")
            break
            
        if not user_input:
            console.print("[dim]Please enter a message.[/dim]")
            continue
        
        # Call the agent with user input
        try:
            console.print("\n[bold]Searching lecture database...[/bold]")
            result = await run_agent_with_tools(user_input)
            
            if result.get("final_answer"):
                final_answer = result["final_answer"]
                console.print(f"\n[bold green]Answer:[/bold green] {final_answer.answer}")
                if final_answer.source_entry_ids:
                    console.print(f"\n[dim]Sources: Entry IDs {final_answer.source_entry_ids}[/dim]")
            else:
                console.print("\n[yellow]Could not find a specific answer in the lecture transcripts.[/yellow]")
                
            console.print(f"\n[dim]Used {result['turns_used']} turns[/dim]\n")
            
        except Exception as e:
            console.print(f"[red]Error: {str(e)}[/red]\n")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    # Check if database exists
    from lecture_search_tools import DEFAULT_DB_PATH
    import os
    
    if not os.path.exists(DEFAULT_DB_PATH):
        console.print(f"[red]Error: Database not found at {DEFAULT_DB_PATH}[/red]")
        console.print("Please ensure the lecture database has been created.")
        exit(1)
    
    # Run the async main function
    asyncio.run(main())





