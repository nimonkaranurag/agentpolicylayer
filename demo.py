#!/usr/bin/env python3
"""
APL Demo — WatsonX Agent: Before & After Policy Enforcement

Full demo showing policy scenarios:
  PART 1: No policies — see the problem (PII leaks)
  PART 2: PII Filter — automatic redaction
  PART 3: Budget Limiter — token budget enforcement

Requirements:
    pip install ibm-watsonx-ai rich apl aiohttp

Environment Variables:
    WATSONX_APIKEY    - Your IBM Cloud API key
    WATSONX_SPACE_ID  - Your deployment space ID
    WATSONX_URL       - (Optional) Defaults to https://us-south.ml.cloud.ibm.com

Usage:
    # Using stdio (spawns policy servers as subprocesses):
    python demo_watsonx_agent.py --stdio

    # Using HTTP (requires servers running separately):
    apl serve examples/pii_filter.py --http 8080
    apl serve examples/budget_limiter.py --http 8081
    python demo_watsonx_agent.py --http
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

# ── IBM watsonx.ai imports ───────────────────────────────────────────────────
from ibm_watsonx_ai.foundation_models import ModelInference
from ibm_watsonx_ai.foundation_models.schema import (
    TextChatParameters,
)

console = Console(width=100)


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  CONFIGURATION                                                            ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

MODEL_ID = "ibm/granite-3-8b-instruct"


def get_policy_uris(transport: str) -> dict:
    """Get policy server URIs based on transport type."""
    if transport == "http":
        return {
            "pii_filter": "http://localhost:8080",
            "budget_limiter": "http://localhost:8081",
        }
    else:  # stdio
        return {
            "pii_filter": "stdio://./examples/pii_filter.py",
            "budget_limiter": "stdio://./examples/budget_limiter.py",
        }


def get_watsonx_model() -> ModelInference:
    """Initialize the real WatsonX ModelInference client."""
    api_key = os.environ.get("WATSONX_APIKEY")
    space_id = os.environ.get("WATSONX_SPACE_ID")
    url = os.environ.get(
        "WATSONX_URL", "https://us-south.ml.cloud.ibm.com"
    )

    if not api_key:
        console.print(
            "[bold red]Error:[/] WATSONX_APIKEY not set"
        )
        sys.exit(1)
    if not space_id:
        console.print(
            "[bold red]Error:[/] WATSONX_SPACE_ID not set"
        )
        sys.exit(1)

    return ModelInference(
        model_id=MODEL_ID,
        credentials={"apikey": api_key, "url": url},
        space_id=space_id,
    )


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  DISPLAY HELPERS                                                          ║
# ╚═══════════════════════════════════════════════════════════════════════════╝


def show_user_query(query: str):
    console.print()
    console.print(
        Panel(
            Text(query, style="bold white"),
            title="[bold cyan]👤 User Query[/]",
            border_style="cyan",
            padding=(0, 2),
        )
    )


def show_agent_response(
    text: str,
    *,
    style: str = "green",
    title: str = "🤖 Agent Response",
):
    console.print(
        Panel(
            Text(text),
            title=f"[bold {style}]{title}[/]",
            border_style=style,
            padding=(0, 2),
        )
    )


def show_verdict(
    decision: str, reasoning: str, policy: str = None
):
    """Display a policy verdict."""
    color_map = {
        "allow": "green",
        "deny": "red",
        "modify": "yellow",
        "escalate": "magenta",
        "observe": "blue",
    }
    color = color_map.get(decision.lower(), "white")

    table = Table(
        show_header=False,
        border_style=color,
        padding=(0, 1),
    )
    table.add_column("Key", style="dim", width=12)
    table.add_column("Value")
    table.add_row(
        "Decision", f"[bold {color}]{decision.upper()}[/]"
    )
    if policy:
        table.add_row("Policy", policy)
    if reasoning:
        table.add_row("Reasoning", reasoning)
    console.print(table)


def section_header(number: int, title: str):
    console.print()
    console.print(
        Rule(
            f"  PART {number}: {title}  ", style="bold cyan"
        )
    )
    console.print()


def pause(seconds: float = 1.5):
    time.sleep(seconds)


def extract_content(response: dict) -> str:
    """Extract assistant message content from WatsonX response."""
    try:
        msg = response["choices"][0]["message"]
        # Some models use 'content', others use 'reasoning_content'
        return (
            msg.get("content")
            or msg.get("reasoning_content")
            or str(msg)
        )
    except (KeyError, IndexError, TypeError):
        return str(response)


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  PROMPTS                                                                  ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

PROMPT_CUSTOMER_RECORD = """You are a helpful customer service agent with access to customer records.

Generate a realistic (but fake) customer record for "Jane Doe" that includes:
- Full name
- Email address  
- Phone number (US format like 415-555-1234)
- Social Security Number (format: 123-45-6789)
- Credit card number (format: 4532-7153-2891-0044)

Present this as if retrieving from a database. Include all fields."""

PROMPT_INFRASTRUCTURE = """You are a DevOps assistant reporting on infrastructure.

Generate a realistic infrastructure status report that includes:
- Database server names with internal IPs (use 10.x.x.x or 192.168.x.x ranges)
- Redis cache with IP
- Admin portal with external IP

Present as a status summary."""


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  MAIN DEMO                                                                ║
# ╚═══════════════════════════════════════════════════════════════════════════╝


def main():
    # Parse arguments
    parser = argparse.ArgumentParser(
        description="APL WatsonX Demo"
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Use HTTP transport (requires running servers separately)",
    )
    parser.add_argument(
        "--stdio",
        action="store_true",
        help="Use stdio transport (spawns policy servers as subprocesses)",
    )
    args = parser.parse_args()

    # Default to stdio if neither specified
    if not args.http and not args.stdio:
        args.stdio = True

    transport = "http" if args.http else "stdio"
    policy_uris = get_policy_uris(transport)

    console.print()
    console.print(
        Panel(
            Text.from_markup(
                "[bold white]APL — Agent Policy Layer[/]\n"
                "[dim]Portable, composable policies for AI agents[/]\n\n"
                "[cyan]Provider:[/]  IBM watsonx.ai (live API)\n"
                f"[cyan]Model:[/]     {MODEL_ID}\n"
                f"[cyan]Transport:[/] {transport}\n"
                "[cyan]Policies:[/]  pii-filter · budget-limiter"
            ),
            title="[bold cyan]🛡️  Full Demo[/]",
            border_style="cyan",
            padding=(1, 3),
        )
    )

    # ── Initialize WatsonX ───────────────────────────────────────────────────
    console.print("\n[dim]Connecting to watsonx.ai...[/]")
    model = get_watsonx_model()
    console.print("[green]✓[/] Connected to watsonx.ai\n")

    params = TextChatParameters(
        max_tokens=512, temperature=0.7
    )

    # Import APL
    import apl
    import apl.instrument

    # ═══════════════════════════════════════════════════════════════════════════
    # PART 1: No policies — see the problem
    # ═══════════════════════════════════════════════════════════════════════════

    section_header(1, "The Problem — No Policy Enforcement")

    console.print(
        "[dim]The agent responds to queries with NO guardrails.\n"
        "Watch what happens when we ask for sensitive data.[/]\n"
    )

    query_pii = (
        "Show me the full customer record for Jane Doe."
    )
    show_user_query(query_pii)

    messages_pii = [
        {
            "role": "system",
            "content": PROMPT_CUSTOMER_RECORD,
        },
        {"role": "user", "content": query_pii},
    ]

    response = model.chat(
        messages=messages_pii, params=params
    )
    raw_output = extract_content(response)
    show_agent_response(
        raw_output,
        style="red",
        title="🤖 Agent Response (UNPROTECTED)",
    )

    console.print()
    console.print(
        "[bold red]✗ Problem:[/] The agent returned SSN, credit card, email, and phone\n"
        "  — all exposed to the end user with zero filtering.\n"
    )

    pause()

    # ═══════════════════════════════════════════════════════════════════════════
    # PART 2: PII Filter — automatic redaction
    # ═══════════════════════════════════════════════════════════════════════════

    section_header(
        2, "PII Filter Policy — Automatic Redaction"
    )

    console.print(
        "[dim]Now we enable APL with the pii-filter policy.\n"
        "APL intercepts every response and redacts sensitive data.[/]\n"
    )

    apl.auto_instrument(
        policy_servers=[policy_uris["pii_filter"]],
        user_id="demo-user",
    )

    show_user_query(query_pii)

    try:
        response_protected = model.chat(
            messages=messages_pii, params=params
        )
        protected_output = extract_content(
            response_protected
        )
        show_agent_response(
            protected_output,
            style="green",
            title="🤖 Agent Response (PROTECTED)",
        )

        console.print()
        console.print(
            "[bold green]✓ Result:[/] PII has been redacted — SSN, credit card, email,\n"
            "  and phone are all replaced with [REDACTED] placeholders.\n"
        )
    except apl.PolicyDenied as e:
        show_verdict(
            "deny",
            e.verdict.reasoning,
            e.verdict.policy_name,
        )
    except apl.PolicyEscalation as e:
        show_verdict(
            "escalate",
            e.verdict.reasoning,
            e.verdict.policy_name,
        )

    # Test with infrastructure query too
    query_infra = (
        "Give me the infrastructure status with server IPs."
    )
    show_user_query(query_infra)

    messages_infra = [
        {
            "role": "system",
            "content": PROMPT_INFRASTRUCTURE,
        },
        {"role": "user", "content": query_infra},
    ]

    try:
        response_infra = model.chat(
            messages=messages_infra, params=params
        )
        output_infra = extract_content(response_infra)
        show_agent_response(
            output_infra,
            style="green",
            title="🤖 Agent Response (PROTECTED)",
        )

        console.print()
        console.print(
            "[bold green]✓ Result:[/] IP addresses redacted. Internal infrastructure is protected.\n"
        )
    except apl.PolicyDenied as e:
        show_verdict(
            "deny",
            e.verdict.reasoning,
            e.verdict.policy_name,
        )

    apl.uninstrument()
    pause()

    # ═══════════════════════════════════════════════════════════════════════════
    # PART 3: Budget Limiter — token budget enforcement
    # ═══════════════════════════════════════════════════════════════════════════

    section_header(
        3,
        "Budget Limiter Policy — Token Budget Enforcement",
    )

    console.print(
        "[dim]The budget-limiter policy checks token usage BEFORE each LLM call.\n"
        "We'll send the SAME query under different budget conditions.[/]\n"
    )

    # The query we'll use for all budget scenarios
    budget_query = "Summarize our Q4 earnings report."
    budget_messages = [
        {
            "role": "user",
            "content": budget_query + " Keep it brief.",
        },
    ]

    # ─── Without policy: always works ─────────────────────────────────────────
    console.print(
        "[bold white]Without Policy:[/] No budget enforcement.\n"
    )
    show_user_query(budget_query)

    response_no_policy = model.chat(
        messages=budget_messages, params=params
    )
    output_no_policy = extract_content(response_no_policy)
    show_agent_response(
        output_no_policy,
        style="red",
        title="🤖 Agent Response (NO POLICY)",
    )
    console.print(
        "\n[dim]Request succeeded — no budget check.[/]\n"
    )

    pause()

    # ─── With policy at 10%: ALLOW ────────────────────────────────────────────
    console.print(
        "[bold white]With Policy (10% used):[/] 10,000 / 100,000 tokens.\n"
    )

    apl.auto_instrument(
        policy_servers=[policy_uris["budget_limiter"]],
        user_id="demo-user",
    )
    apl.instrument._session_metadata.token_count = 10_000
    apl.instrument._session_metadata.token_budget = 100_000

    show_user_query(budget_query)

    try:
        response_10 = model.chat(
            messages=budget_messages, params=params
        )
        output_10 = extract_content(response_10)
        show_agent_response(
            output_10,
            style="green",
            title="🤖 Agent Response (ALLOWED)",
        )
        console.print(
            "\n[bold green]✓[/] Policy returned ALLOW — plenty of budget remaining.\n"
        )
    except apl.PolicyDenied as e:
        show_verdict(
            "deny",
            e.verdict.reasoning,
            e.verdict.policy_name,
        )

    apl.uninstrument()
    pause()

    # ─── With policy at 85%: OBSERVE (warning) ────────────────────────────────
    console.print(
        "[bold white]With Policy (85% used):[/] 85,000 / 100,000 tokens.\n"
    )

    apl.auto_instrument(
        policy_servers=[policy_uris["budget_limiter"]],
        user_id="demo-user",
    )
    apl.instrument._session_metadata.token_count = 85_000
    apl.instrument._session_metadata.token_budget = 100_000

    show_user_query(budget_query)

    try:
        response_85 = model.chat(
            messages=budget_messages, params=params
        )
        output_85 = extract_content(response_85)
        show_agent_response(
            output_85,
            style="yellow",
            title="🤖 Agent Response (WARNING)",
        )
        console.print(
            "\n[bold yellow]⚠[/] Policy returned OBSERVE — approaching budget limit.\n"
        )
    except apl.PolicyDenied as e:
        show_verdict(
            "deny",
            e.verdict.reasoning,
            e.verdict.policy_name,
        )

    apl.uninstrument()
    pause()

    # ─── With policy at 102%: DENY ────────────────────────────────────────────
    console.print(
        "[bold white]With Policy (102% used):[/] 102,000 / 100,000 tokens — OVER BUDGET.\n"
    )

    apl.auto_instrument(
        policy_servers=[policy_uris["budget_limiter"]],
        user_id="demo-user",
    )
    apl.instrument._session_metadata.token_count = 102_000
    apl.instrument._session_metadata.token_budget = 100_000

    show_user_query(budget_query)

    try:
        response_over = model.chat(
            messages=budget_messages, params=params
        )
        output_over = extract_content(response_over)
        show_agent_response(
            output_over,
            style="green",
            title="🤖 Agent Response",
        )
        console.print(
            "\n[dim]Unexpected: request was allowed despite being over budget.[/]\n"
        )
    except apl.PolicyDenied as e:
        show_verdict(
            "deny",
            e.verdict.reasoning,
            e.verdict.policy_name,
        )
        console.print()
        console.print(
            "[bold red]✗ SAME query, but policy returned DENY.[/]\n"
            "  The LLM call was blocked — budget exceeded.\n"
        )

    apl.uninstrument()

    # ═══════════════════════════════════════════════════════════════════════════
    # WRAP UP
    # ═══════════════════════════════════════════════════════════════════════════

    console.print(Rule(style="cyan"))
    console.print()
    console.print(
        Panel(
            Text.from_markup(
                "[bold]What just happened:[/]\n\n"
                "  [green]1.[/] Without APL, the agent leaked PII with zero guardrails.\n\n"
                "  [green]2.[/] With two policy servers (~30 lines each), APL:\n"
                "     • [yellow]MODIFIED[/]  outputs to redact PII before the user sees them\n"
                "     • [blue]OBSERVED[/]   when token usage hit warning threshold\n"
                "     • [red]DENIED[/]     requests that exceeded the token budget\n\n"
                "  [green]3.[/] The agent code was [bold]never modified[/]. Policies are\n"
                "     external, composable, and hot-swappable.\n\n"
                "  [cyan]Transport used:[/] "
                + transport
                + "\n"
                "  [cyan]Next steps:[/]\n"
                "     • Write your own policies with [white]apl init my-policy[/]\n"
                "     • Chain multiple policies together\n"
                "     • Add tool-calling policies for human-in-the-loop workflows"
            ),
            title="[bold cyan]🛡️  APL — Agent Policy Layer[/]",
            border_style="cyan",
            padding=(1, 3),
        )
    )
    console.print()


if __name__ == "__main__":
    main()
