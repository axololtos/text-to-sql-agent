import os
import sys
import argparse
from dotenv import load_dotenv
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain.agents import create_agent
from langchain_core.tools import StructuredTool
from langchain_google_genai import ChatGoogleGenerativeAI
from rich.console import Console
from rich.panel import Panel

# Load environment variables
load_dotenv()

console = Console()

# System prompt for the SQL agent
SYSTEM_PROMPT = """
You are an agent designed to interact with a SQL database.
Given an input question, create a syntactically correct {dialect} query to run,
then look at the results of the query and return the answer. Unless the user
specifies a specific number of examples they wish to obtain, always limit your
query to at most {top_k} results.

You can order the results by a relevant column to return the most interesting
examples in the database. Never query for all the columns from a specific table,
only ask for the relevant columns given the question.

You MUST double check your query before executing it. If you get an error while
executing a query, read the error message carefully, rewrite the query, and try
again. You only get a limited number of self-correction attempts; once the
sql_db_query tool tells you the repair budget is exhausted, stop rewriting and
report the last database error to the user verbatim as your final answer.

DO NOT make any DML statements (INSERT, UPDATE, DELETE, DROP etc.) to the
database.

To start you should ALWAYS look at the tables in the database to see what you
can query. Do NOT skip this step.

Then you should query the schema of the most relevant tables.
"""

def _wrap_query_tool_with_repair_budget(query_tool, max_attempts):
    """Wrap sql_db_query so failed executions are capped at max_attempts.

    Results pass straight through on success (which resets the counter). On a
    database error, the raw error string is returned with an explicit
    self-correction instruction appended; once max_attempts failures are
    reached, a terminal instruction tells the agent to stop and report the
    error instead of rewriting the query again.
    """
    # ponytail: one counter per agent instance. Fine for the CLI's one-shot
    # runs, and for the notebook a successful query resets it between questions.
    state = {"failures": 0}

    def _run(query: str) -> str:
        result = str(query_tool.run(query))
        if not result.startswith("Error:"):
            state["failures"] = 0
            return result
        state["failures"] += 1
        if state["failures"] >= max_attempts:
            return (
                f"{result}\n\n[repair budget exhausted after {max_attempts} "
                f"failed attempts] Stop rewriting the query. Report the error "
                f"above to the user verbatim as your final answer."
            )
        return (
            f"{result}\n\n[self-correction {state['failures']}/{max_attempts}] "
            f"Read the error above, fix the query, and call sql_db_query again."
        )

    return StructuredTool.from_function(
        _run,
        name=query_tool.name,
        description=query_tool.description,
        args_schema=getattr(query_tool, "args_schema", None),
    )


def create_sql_agent(max_repair_attempts=3):
    """Create and return a text-to-SQL agent.

    max_repair_attempts caps how many times a failing SQL query is fed back for
    self-correction before the agent must give up and report the error.
    """

    # Connect to Chinook database
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chinook.db")
    db = SQLDatabase.from_uri(
        f"sqlite:///{db_path}",
        sample_rows_in_table_info=3
    )

    # Initialize the Gemini chat model (override with GEMINI_MODEL in .env)
    model = ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    )

    # Create SQL toolkit with tools, capping self-correction on sql_db_query
    toolkit = SQLDatabaseToolkit(db=db, llm=model)
    tools = [
        _wrap_query_tool_with_repair_budget(tool, max_repair_attempts)
        if tool.name == "sql_db_query"
        else tool
        for tool in toolkit.get_tools()
    ]

    # Create the agent
    agent = create_agent(
        model,
        tools,
        system_prompt=SYSTEM_PROMPT.format(dialect=db.dialect, top_k=5)
    )

    return agent


def main():
    """Main entry point for the SQL Agent CLI"""
    parser = argparse.ArgumentParser(
        description="Text-to-SQL Agent powered by LangChain and Gemini (3.6 Flash by default)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python agent.py "What are the top 5 best-selling artists?"
  python agent.py "Which employee generated the most revenue?"
  python agent.py "How many customers are from Canada?"
        """
    )
    parser.add_argument(
        "question",
        type=str,
        help="Natural language question to answer using the Chinook database"
    )
    parser.add_argument(
        "--max-repair-attempts",
        type=int,
        default=int(os.getenv("MAX_REPAIR_ATTEMPTS", "3")),
        help="Failed SQL executions to self-correct before giving up (default: 3)"
    )

    args = parser.parse_args()

    # Display the question
    console.print(Panel(
        f"[bold cyan]Question:[/bold cyan] {args.question}",
        border_style="cyan"
    ))
    console.print()

    # Create the agent
    console.print("[dim]Creating SQL Agent...[/dim]")
    agent = create_sql_agent(max_repair_attempts=args.max_repair_attempts)

    # Invoke the agent
    console.print("[dim]Processing query...[/dim]\n")

    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": args.question}]},
            {"recursion_limit": 6 * args.max_repair_attempts + 12},
        )

        # Extract the final answer. Gemini returns content as a list of blocks
        # ([{"type": "text", "text": ...}, ...]); older models return a string.
        content = result["messages"][-1].content
        if isinstance(content, list):
            answer = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        else:
            answer = content

        console.print(Panel(
            f"[bold green]Answer:[/bold green]\n\n{answer}",
            border_style="green"
        ))

    except Exception as e:
        console.print(Panel(
            f"[bold red]Error:[/bold red]\n\n{str(e)}",
            border_style="red"
        ))
        sys.exit(1)


if __name__ == "__main__":
    main()
