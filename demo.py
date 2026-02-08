#!/usr/bin/env python3
"""
APL Demo — WatsonX Agent: Before & After Policy Enforcement

This script demonstrates APL auto-instrumentation with IBM watsonx.ai.

Requirements:
    pip install ibm-watsonx-ai rich apl

Environment Variables:
    WATSONX_APIKEY    - Your IBM Cloud API key
    WATSONX_SPACE_ID  - Your deployment space ID
    WATSONX_URL       - (Optional) Defaults to https://us-south.ml.cloud.ibm.com

Usage:
    python demo_watsonx_agent.py
"""

from __future__ import annotations

import os
import sys
import time

# ── IBM watsonx.ai imports ───────────────────────────────────────────────────
from ibm_watsonx_ai.foundation_models import ModelInference
from ibm_watsonx_ai.foundation_models.schema import (
    TextChatParameters,
)
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

console = Console(width=90)


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  CONFIGURATION                                                            ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

MODEL_ID = "openai/gpt-oss-120b"

# Paths to the real APL example policy servers
POLICY_PII_FILTER = "http://localhost:8080"
POLICY_BUDGET_LIMITER = (
    "stdio://./examples/budget_limiter.py"
)
POLICY_CONFIRM_DESTRUCTIVE = (
    "stdio://./examples/confirm_destructive.py"
)


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
        return response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return str(response)


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  PROMPTS - Designed to elicit PII/IP in responses                         ║
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
    console.print()
    console.print(
        Panel(
            Text.from_markup(
                "[bold white]APL — Agent Policy Layer[/]\n"
                "[dim]Portable, composable policies for AI agents[/]\n\n"
                "[cyan]Provider:[/]  IBM watsonx.ai (live API)\n"
                f"[cyan]Model:[/]     {MODEL_ID}\n"
                "[cyan]Policies:[/]  pii-filter (real APL server)"
            ),
            title="[bold cyan]🛡️  Demo[/]",
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

    # ═══════════════════════════════════════════════════════════════════════
    # PART 1: No policies — see the problem
    # ═══════════════════════════════════════════════════════════════════════

    section_header(1, "The Problem — No Policy Enforcement")

    console.print(
        "[dim]The agent responds to queries with NO guardrails.\n"
        "Watch what happens when we ask for sensitive data.[/]\n"
    )

    query_1 = (
        "Show me the full customer record for Jane Doe."
    )
    show_user_query(query_1)

    messages = [
        {
            "role": "system",
            "content": PROMPT_CUSTOMER_RECORD,
        },
        {"role": "user", "content": query_1},
    ]

    response = model.chat(messages=messages, params=params)
    raw_output = extract_content(response)
    show_agent_response(
        raw_output,
        style="red",
        title="🤖 Agent Response (UNPROTECTED)",
    )

    console.print()
    console.print(
        "[bold red]✗ Problem:[/] The agent just returned SSN, credit card, email,\n"
        "  and phone — all exposed to the end user.\n"
    )

    pause()

    # Infrastructure query
    query_2 = (
        "Give me the infrastructure status with server IPs."
    )
    show_user_query(query_2)

    messages_2 = [
        {
            "role": "system",
            "content": PROMPT_INFRASTRUCTURE,
        },
        {"role": "user", "content": query_2},
    ]

    response_2 = model.chat(
        messages=messages_2, params=params
    )
    raw_output_2 = extract_content(response_2)
    show_agent_response(
        raw_output_2,
        style="red",
        title="🤖 Agent Response (UNPROTECTED)",
    )

    console.print()
    console.print(
        "[bold red]✗ Problem:[/] Internal IP addresses exposed. An attacker could\n"
        "  use these to map your private network.\n"
    )

    pause()

    # ═══════════════════════════════════════════════════════════════════════
    # PART 2: Enable APL auto-instrumentation with PII filter
    # ═══════════════════════════════════════════════════════════════════════

    section_header(
        2, "PII Filter Policy — Automatic Redaction"
    )

    console.print(
        "[dim]Now we enable APL auto-instrumentation.\n"
        "APL wraps the WatsonX client and evaluates policies on every call.[/]\n"
    )

    # Import and enable APL
    import apl

    apl.auto_instrument(
        policy_servers=[POLICY_PII_FILTER],
        user_id="demo-user",
    )

    # Re-run the same queries — now protected
    show_user_query(query_1)

    # The model.chat() call is now instrumented by APL
    try:
        response_protected = model.chat(
            messages=messages, params=params
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
            "[bold green]✓ Result:[/] PII has been redacted before reaching the user.\n"
            "  SSN, credit card, email, and phone are all protected.\n"
        )
    except apl.PolicyDenied as e:
        console.print(
            f"[bold yellow]Policy DENIED:[/] {e.verdict.reasoning}\n"
        )
    except apl.PolicyEscalation as e:
        console.print(
            f"[bold magenta]Policy ESCALATED:[/] {e.verdict.escalation.prompt}\n"
        )

    pause()

    # Infrastructure query with protection
    show_user_query(query_2)

    try:
        response_protected_2 = model.chat(
            messages=messages_2, params=params
        )
        protected_output_2 = extract_content(
            response_protected_2
        )
        show_agent_response(
            protected_output_2,
            style="green",
            title="🤖 Agent Response (PROTECTED)",
        )

        console.print()
        console.print(
            "[bold green]✓ Result:[/] IP addresses redacted. Infrastructure info is safe.\n"
        )
    except apl.PolicyDenied as e:
        console.print(
            f"[bold yellow]Policy DENIED:[/] {e.verdict.reasoning}\n"
        )

    # ═══════════════════════════════════════════════════════════════════════
    # WRAP UP
    # ═══════════════════════════════════════════════════════════════════════

    console.print(Rule(style="cyan"))
    console.print()
    console.print(
        Panel(
            Text.from_markup(
                "[bold]What just happened:[/]\n\n"
                "  [green]1.[/] Without APL, the agent leaked PII and internal IPs\n"
                "     with zero guardrails.\n\n"
                "  [green]2.[/] With [bold]one line[/] — [cyan]apl.auto_instrument()[/] —\n"
                "     every WatsonX call is now protected by the pii-filter policy.\n\n"
                "  [green]3.[/] The agent code was [bold]never modified[/].\n"
                "     Policies are external, composable, and hot-swappable.\n\n"
                "  [dim]Add more policies (budget, confirm-destructive) by adding\n"
                "  more URIs to the policy_servers list.[/]"
            ),
            title="[bold cyan]🛡️  APL — Agent Policy Layer[/]",
            border_style="cyan",
            padding=(1, 3),
        )
    )
    console.print()

    # Clean up
    apl.uninstrument()


if __name__ == "__main__":
    main()
