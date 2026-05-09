from __future__ import annotations

import os

from rich.console import Console

from ai.provider import build_llm, detect_provider
from ai.resume_parser import load_resume
from ai.tools import ChatState, build_tools
from output.table import render_table

HISTORY_CAP: int = 20
MAX_ITERATIONS: int = 8

_SYSTEM_PROMPT = (
    "You are job-scout, a helpful AI assistant that helps users search for jobs and "
    "evaluate them against their resume.\n\n"
    "Use the provided tools to search, filter, score, open, summarize, and export "
    "job listings. Prefer in-memory results before re-searching. When the user "
    "refers to a listing by number, use that 1-based index. Never invent listings "
    "or URLs. When discussing specific jobs, cite their index (e.g. '#3').\n\n"
    "Current state: {state_summary}\n\n"
    "Reply briefly. The tools render their own tables and side effects, so do not "
    "repeat data the tool already printed."
)

_HELP_TEXT = (
    "Commands:\n"
    "  /help            Show this help.\n"
    "  /results         Re-render the current results table.\n"
    "  /clear           Clear results and conversation history.\n"
    "  /resume PATH     Load or replace the resume in-session.\n"
    "  /exit, /quit     Exit chat.\n\n"
    "Agent capabilities (just describe what you want):\n"
    "  • Search for jobs by query, type, location, or limit.\n"
    "  • Filter current results by company, location, type, or keyword.\n"
    "  • Score current results against the loaded resume.\n"
    "  • Open a result in your browser by number.\n"
    "  • Summarize likely requirements for a specific result.\n"
    "  • Export current results to CSV."
)


def run_chat(resume_path: str | None) -> None:
    console = Console()
    llm = build_llm()
    if llm is None:
        # Defensive: caller should have already gated on detect_provider().
        console.print("[red]No AI provider configured.[/red]")
        return

    detected = detect_provider()
    provider_label = (
        f"{detected[0]} ({detected[1]})" if detected else "unknown"
    )

    state = ChatState(console=console, llm=llm)
    if resume_path:
        try:
            state.resume_text = load_resume(resume_path)
            state.resume_path = resume_path
            if not state.has_resume():
                console.print(
                    f"[yellow]Resume at {resume_path} produced no extractable text.[/yellow]"
                )
        except ValueError as exc:
            console.print(f"[yellow]Could not load resume: {exc}[/yellow]")

    resume_label = (
        f"loaded ({state.resume_path})" if state.has_resume() else "none"
    )
    console.print(
        f"\n[bold]job-scout chat[/bold]  ·  provider: {provider_label}  ·  resume: {resume_label}"
    )
    console.print("Type [bold]/help[/bold] for commands, [bold]/exit[/bold] to quit.\n")

    tools = build_tools(state)
    agent_executor = _build_agent(llm, tools)

    history: list[tuple[str, str]] = []  # list of (role, content)

    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import HTML

    session: PromptSession = PromptSession()

    while True:
        try:
            text = session.prompt(HTML("<b><ansicyan>you&gt; </ansicyan></b>"))
        except KeyboardInterrupt:
            continue
        except EOFError:
            console.print("Goodbye.")
            return

        text = text.strip()
        if not text:
            continue

        if text.startswith("/"):
            if _handle_command(text, state, history, console):
                return
            continue

        try:
            with console.status("[dim]thinking…[/dim]"):
                response = agent_executor.invoke(
                    {
                        "input": text,
                        "chat_history": _to_lc_messages(history),
                        "state_summary": state.summary(),
                    }
                )
        except KeyboardInterrupt:
            console.print("[yellow]Cancelled.[/yellow]")
            continue
        except Exception as exc:
            console.print(f"[red]AI error:[/red] {type(exc).__name__}: {exc}")
            continue

        output = (response.get("output") if isinstance(response, dict) else str(response)) or ""
        if isinstance(output, list):
            output = "".join(
                str(p.get("text", p)) if isinstance(p, dict) else str(p) for p in output
            )
        output = str(output).strip()
        if output:
            console.print(output)
        history.append(("human", text))
        if output:
            history.append(("ai", output))
        if len(history) > HISTORY_CAP:
            history[:] = history[-HISTORY_CAP:]


def _handle_command(
    text: str,
    state: ChatState,
    history: list[tuple[str, str]],
    console: Console,
) -> bool:
    """Handle a /command. Returns True when the chat should exit."""
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in {"/exit", "/quit"}:
        console.print("Goodbye.")
        return True
    if cmd == "/help":
        console.print(_HELP_TEXT)
        return False
    if cmd == "/results":
        if not state.results:
            console.print("[dim]No results loaded.[/dim]")
        else:
            render_table(
                state.results,
                state.last_query or "results",
                show_match=any(l.match_score is not None for l in state.results),
            )
        return False
    if cmd == "/clear":
        state.results = []
        state.last_query = None
        history.clear()
        console.print("[dim]Cleared results and conversation history.[/dim]")
        return False
    if cmd == "/resume":
        if not arg:
            console.print("[yellow]Usage: /resume PATH[/yellow]")
            return False
        expanded = os.path.expanduser(arg)
        try:
            text_content = load_resume(expanded)
        except ValueError as exc:
            console.print(f"[yellow]Could not load resume: {exc}[/yellow]")
            return False
        if not text_content.strip():
            console.print(
                f"[yellow]Resume at {expanded} produced no extractable text.[/yellow]"
            )
            return False
        state.resume_text = text_content
        state.resume_path = expanded
        console.print(f"[green]Resume loaded:[/green] {expanded}")
        return False

    console.print(f"[yellow]Unknown command: {cmd}. Try /help.[/yellow]")
    return False


def _build_agent(llm, tools):
    try:
        # langchain >= 1.0 moved the legacy AgentExecutor to langchain_classic.
        from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
    except ImportError:
        from langchain.agents import AgentExecutor, create_tool_calling_agent
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", _SYSTEM_PROMPT),
            MessagesPlaceholder("chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ]
    )
    agent = create_tool_calling_agent(llm, tools, prompt)
    return AgentExecutor(
        agent=agent,
        tools=tools,
        max_iterations=MAX_ITERATIONS,
        handle_parsing_errors=True,
        verbose=False,
    )


def _to_lc_messages(history: list[tuple[str, str]]):
    from langchain_core.messages import AIMessage, HumanMessage

    msgs = []
    for role, content in history:
        if role == "human":
            msgs.append(HumanMessage(content=content))
        else:
            msgs.append(AIMessage(content=content))
    return msgs
