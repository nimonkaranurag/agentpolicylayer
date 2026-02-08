#!/usr/bin/env python3
"""
Token & Cost Budget Policy

Enforces token and cost limits on agent sessions.
Demonstrates using session metadata for stateful policies.

Run: python examples/budget_limiter.py
"""

import os
import sys

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),
)

from apl import PolicyEvent, PolicyServer, Verdict

server = PolicyServer(
    name="budget-limiter",
    version="1.0.0",
    description="Enforces token and cost budgets",
)


# Default limits (can be overridden via metadata)
DEFAULT_TOKEN_BUDGET = 100_000
DEFAULT_COST_BUDGET_USD = 1.00
WARNING_THRESHOLD = 0.8  # Warn at 80%


@server.policy(
    name="token-budget",
    events=["llm.pre_request"],
    context=[
        "metadata.token_count",
        "metadata.token_budget",
    ],
    description="Enforces token limits per session",
)
async def check_token_budget(event: PolicyEvent) -> Verdict:
    """
    Check if session is within token budget.
    """
    token_count = event.metadata.token_count
    token_budget = (
        event.metadata.token_budget or DEFAULT_TOKEN_BUDGET
    )

    ratio = (
        token_count / token_budget
        if token_budget > 0
        else 0
    )

    if ratio >= 1.0:
        return Verdict.deny(
            reasoning=f"Token budget exceeded: {token_count:,} / {token_budget:,} tokens",
            confidence=1.0,
        )

    if ratio >= WARNING_THRESHOLD:
        remaining = token_budget - token_count
        return Verdict.observe(
            reasoning=f"Token budget warning: {remaining:,} tokens remaining ({(1-ratio)*100:.0f}%)",
            trace={
                "token_count": token_count,
                "token_budget": token_budget,
                "ratio": ratio,
            },
        )

    return Verdict.allow()


@server.policy(
    name="cost-budget",
    events=["llm.pre_request", "tool.pre_invoke"],
    context=[
        "metadata.cost_usd",
        "metadata.cost_budget_usd",
    ],
    description="Enforces cost limits per session",
)
async def check_cost_budget(event: PolicyEvent) -> Verdict:
    """
    Check if session is within cost budget.
    """
    cost_usd = event.metadata.cost_usd
    cost_budget = (
        event.metadata.cost_budget_usd
        or DEFAULT_COST_BUDGET_USD
    )

    ratio = cost_usd / cost_budget if cost_budget > 0 else 0

    if ratio >= 1.0:
        return Verdict.deny(
            reasoning=f"Cost budget exceeded: ${cost_usd:.4f} / ${cost_budget:.2f}",
            confidence=1.0,
        )

    if ratio >= WARNING_THRESHOLD:
        remaining = cost_budget - cost_usd
        return Verdict.observe(
            reasoning=f"Cost budget warning: ${remaining:.4f} remaining",
            trace={
                "cost_usd": cost_usd,
                "cost_budget": cost_budget,
            },
        )

    return Verdict.allow()


@server.policy(
    name="expensive-model-guard",
    events=["llm.pre_request"],
    context=[
        "payload.llm_model",
        "metadata.cost_budget_usd",
    ],
    description="Prevents use of expensive models when budget is low",
)
async def expensive_model_guard(
    event: PolicyEvent,
) -> Verdict:
    """
    Suggest cheaper models when budget is running low.
    """
    model = event.payload.llm_model or ""
    cost_usd = event.metadata.cost_usd
    cost_budget = (
        event.metadata.cost_budget_usd
        or DEFAULT_COST_BUDGET_USD
    )

    ratio = cost_usd / cost_budget if cost_budget > 0 else 0

    # Expensive models (rough heuristic)
    expensive_models = [
        "gpt-4",
        "claude-3-opus",
        "claude-opus",
    ]

    is_expensive = any(
        exp in model.lower() for exp in expensive_models
    )

    if is_expensive and ratio >= 0.5:
        # Suggest switching to a cheaper model
        return Verdict.escalate(
            type="human_confirm",
            prompt=f"💰 Budget is at {ratio*100:.0f}%. Continue with expensive model '{model}' or switch to a cheaper alternative?",
            reasoning="Expensive model requested with limited budget remaining",
            options=["Continue", "Use cheaper model"],
            fallback_action="use_cheaper_model",
        )

    return Verdict.allow()


if __name__ == "__main__":
    server.run()
