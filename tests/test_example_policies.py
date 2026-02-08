"""
APL Example Policy Tests

Exercises every policy defined in the ``examples/`` directory using
in-process ``PolicyServer.evaluate()`` calls — no subprocess or network
required.

Policies under test:
    examples/pii_filter.py
        - redact-pii          (output.pre_send)
        - block-pii-in-tools  (tool.pre_invoke)

    examples/budget_limiter.py
        - token-budget          (llm.pre_request)
        - cost-budget           (llm.pre_request, tool.pre_invoke)
        - expensive-model-guard (llm.pre_request)

    examples/confirm_destructive.py
        - confirm-delete   (tool.pre_invoke)
        - warn-high-risk   (tool.pre_invoke)
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from datetime import datetime

import pytest

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),
)

from apl import (
    Decision,
    EventPayload,
    EventType,
    Message,
    PolicyEvent,
    PolicyServer,
    SessionMetadata,
    Verdict,
)

# Import the conftest helper (works because conftest.py is in the same dir)
from tests.conftest import make_event

# ============================================================================
# PII Filter — examples/pii_filter.py
# ============================================================================

# Recreate the policy server in-process so we don't need subprocesses.

PATTERNS = {
    "ssn": (r"\b\d{3}-\d{2}-\d{4}\b", "[SSN REDACTED]"),
    "credit_card": (
        r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
        "[CC REDACTED]",
    ),
    "email": (
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "[EMAIL REDACTED]",
    ),
    "phone_us": (
        r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b",
        "[PHONE REDACTED]",
    ),
    "ip_address": (
        r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
        "[IP REDACTED]",
    ),
}


def _make_pii_server() -> PolicyServer:
    server = PolicyServer("pii-filter", version="1.0.0")

    @server.policy(
        name="redact-pii",
        events=["output.pre_send"],
        context=["payload.output_text"],
    )
    async def redact_pii(event):
        text = event.payload.output_text
        if not text:
            return Verdict.allow()
        found = []
        redacted = text
        for name, (pat, repl) in PATTERNS.items():
            matches = re.findall(pat, redacted)
            if matches:
                found.append(f"{name}: {len(matches)}")
                redacted = re.sub(pat, repl, redacted)
        if found:
            return Verdict.modify(
                target="output",
                operation="replace",
                value=redacted,
                reasoning=f"Redacted PII: {', '.join(found)}",
                confidence=0.95,
            )
        return Verdict.allow()

    @server.policy(
        name="block-pii-in-tools",
        events=["tool.pre_invoke"],
        context=["payload.tool_name", "payload.tool_args"],
    )
    async def block_pii_in_tools(event):
        args_str = str(event.payload.tool_args or {})
        for name, (pat, _) in PATTERNS.items():
            if re.search(pat, args_str):
                return Verdict.deny(
                    reasoning=f"Tool call contains {name}",
                    confidence=0.9,
                )
        return Verdict.allow()

    return server


class TestPIIFilter:
    """redact-pii and block-pii-in-tools policies."""

    @pytest.fixture(autouse=True)
    def server(self):
        self._server = _make_pii_server()

    # ---- redact-pii (output.pre_send) -------------------------------------

    @pytest.mark.asyncio
    async def test_redact_ssn(self):
        event = make_event(
            "output.pre_send",
            output_text="My SSN is 123-45-6789.",
        )
        verdicts = await self._server.evaluate(event)
        v = verdicts[0]
        assert v.decision == Decision.MODIFY
        assert "[SSN REDACTED]" in v.modification.value
        assert "123-45-6789" not in v.modification.value

    @pytest.mark.asyncio
    async def test_redact_credit_card(self):
        event = make_event(
            "output.pre_send",
            output_text="Card: 4111-1111-1111-1111",
        )
        verdicts = await self._server.evaluate(event)
        v = verdicts[0]
        assert v.decision == Decision.MODIFY
        assert "[CC REDACTED]" in v.modification.value

    @pytest.mark.asyncio
    async def test_redact_email(self):
        event = make_event(
            "output.pre_send",
            output_text="Email john@example.com for info.",
        )
        verdicts = await self._server.evaluate(event)
        v = verdicts[0]
        assert v.decision == Decision.MODIFY
        assert "[EMAIL REDACTED]" in v.modification.value
        assert (
            "john@example.com" not in v.modification.value
        )

    @pytest.mark.asyncio
    async def test_redact_phone(self):
        event = make_event(
            "output.pre_send",
            output_text="Call me at 555-123-4567.",
        )
        verdicts = await self._server.evaluate(event)
        v = verdicts[0]
        assert v.decision == Decision.MODIFY
        assert "[PHONE REDACTED]" in v.modification.value

    @pytest.mark.asyncio
    async def test_redact_ip_address(self):
        event = make_event(
            "output.pre_send",
            output_text="Server IP: 192.168.1.100",
        )
        verdicts = await self._server.evaluate(event)
        v = verdicts[0]
        assert v.decision == Decision.MODIFY
        assert "[IP REDACTED]" in v.modification.value

    @pytest.mark.asyncio
    async def test_redact_multiple_pii(self):
        event = make_event(
            "output.pre_send",
            output_text="SSN 123-45-6789, email bob@test.com, IP 10.0.0.1",
        )
        verdicts = await self._server.evaluate(event)
        v = verdicts[0]
        assert v.decision == Decision.MODIFY
        val = v.modification.value
        assert "[SSN REDACTED]" in val
        assert "[EMAIL REDACTED]" in val
        assert "[IP REDACTED]" in val
        assert "123-45-6789" not in val
        assert "bob@test.com" not in val

    @pytest.mark.asyncio
    async def test_no_pii_allows(self):
        event = make_event(
            "output.pre_send",
            output_text="The weather is nice today.",
        )
        verdicts = await self._server.evaluate(event)
        assert verdicts[0].decision == Decision.ALLOW

    @pytest.mark.asyncio
    async def test_empty_text_allows(self):
        event = make_event(
            "output.pre_send", output_text=""
        )
        verdicts = await self._server.evaluate(event)
        assert verdicts[0].decision == Decision.ALLOW

    @pytest.mark.asyncio
    async def test_none_text_allows(self):
        event = make_event(
            "output.pre_send", output_text=None
        )
        verdicts = await self._server.evaluate(event)
        assert verdicts[0].decision == Decision.ALLOW

    # ---- block-pii-in-tools (tool.pre_invoke) ------------------------------

    @pytest.mark.asyncio
    async def test_block_pii_in_tool_args_ssn(self):
        event = make_event(
            "tool.pre_invoke",
            tool_name="send_email",
            tool_args={"body": "SSN: 123-45-6789"},
        )
        verdicts = await self._server.evaluate(event)
        assert verdicts[0].decision == Decision.DENY
        assert "ssn" in verdicts[0].reasoning.lower()

    @pytest.mark.asyncio
    async def test_block_pii_in_tool_args_email(self):
        event = make_event(
            "tool.pre_invoke",
            tool_name="webhook",
            tool_args={"payload": "contact alice@corp.com"},
        )
        verdicts = await self._server.evaluate(event)
        assert verdicts[0].decision == Decision.DENY

    @pytest.mark.asyncio
    async def test_clean_tool_args_allowed(self):
        event = make_event(
            "tool.pre_invoke",
            tool_name="search",
            tool_args={"query": "weather today"},
        )
        verdicts = await self._server.evaluate(event)
        assert verdicts[0].decision == Decision.ALLOW


# ============================================================================
# Budget Limiter — examples/budget_limiter.py
# ============================================================================

DEFAULT_TOKEN_BUDGET = 100_000
DEFAULT_COST_BUDGET_USD = 1.00
WARNING_THRESHOLD = 0.8


def _make_budget_server() -> PolicyServer:
    server = PolicyServer("budget-limiter", version="1.0.0")

    @server.policy(
        name="token-budget",
        events=["llm.pre_request"],
        context=[
            "metadata.token_count",
            "metadata.token_budget",
        ],
    )
    async def check_token_budget(event):
        tc = event.metadata.token_count
        tb = (
            event.metadata.token_budget
            or DEFAULT_TOKEN_BUDGET
        )
        ratio = tc / tb if tb > 0 else 0
        if ratio >= 1.0:
            return Verdict.deny(
                reasoning=f"Token budget exceeded: {tc:,}/{tb:,}"
            )
        if ratio >= WARNING_THRESHOLD:
            return Verdict.observe(
                reasoning=f"Token budget warning: {tb - tc:,} remaining"
            )
        return Verdict.allow()

    @server.policy(
        name="cost-budget",
        events=["llm.pre_request", "tool.pre_invoke"],
        context=[
            "metadata.cost_usd",
            "metadata.cost_budget_usd",
        ],
    )
    async def check_cost_budget(event):
        cost = event.metadata.cost_usd
        budget = (
            event.metadata.cost_budget_usd
            or DEFAULT_COST_BUDGET_USD
        )
        ratio = cost / budget if budget > 0 else 0
        if ratio >= 1.0:
            return Verdict.deny(
                reasoning=f"Cost budget exceeded: ${cost:.4f}/${budget:.2f}"
            )
        if ratio >= WARNING_THRESHOLD:
            return Verdict.observe(
                reasoning=f"Cost budget warning: ${budget - cost:.4f} remaining"
            )
        return Verdict.allow()

    @server.policy(
        name="expensive-model-guard",
        events=["llm.pre_request"],
        context=[
            "payload.llm_model",
            "metadata.cost_budget_usd",
        ],
    )
    async def expensive_model_guard(event):
        model = event.payload.llm_model or ""
        cost = event.metadata.cost_usd
        budget = (
            event.metadata.cost_budget_usd
            or DEFAULT_COST_BUDGET_USD
        )
        ratio = cost / budget if budget > 0 else 0
        expensive = [
            "gpt-4",
            "claude-3-opus",
            "claude-opus",
        ]
        is_expensive = any(
            e in model.lower() for e in expensive
        )
        if is_expensive and ratio >= 0.5:
            return Verdict.escalate(
                type="human_confirm",
                prompt=f"Budget at {ratio*100:.0f}%. Continue with '{model}'?",
                reasoning="Expensive model with limited budget",
                options=["Continue", "Use cheaper model"],
                fallback_action="use_cheaper_model",
            )
        return Verdict.allow()

    return server


class TestBudgetLimiter:
    """token-budget, cost-budget, expensive-model-guard policies."""

    @pytest.fixture(autouse=True)
    def server(self):
        self._server = _make_budget_server()

    # ---- token-budget ------------------------------------------------------

    @pytest.mark.asyncio
    async def test_token_budget_exceeded_denies(self):
        event = make_event(
            "llm.pre_request",
            llm_model="gpt-3.5-turbo",
            token_count=100_000,
            token_budget=100_000,
        )
        verdicts = await self._server.evaluate(event)
        decisions = [v.decision for v in verdicts]
        assert Decision.DENY in decisions

    @pytest.mark.asyncio
    async def test_token_budget_over_limit_denies(self):
        event = make_event(
            "llm.pre_request",
            llm_model="gpt-3.5-turbo",
            token_count=150_000,
            token_budget=100_000,
        )
        verdicts = await self._server.evaluate(event)
        decisions = [v.decision for v in verdicts]
        assert Decision.DENY in decisions

    @pytest.mark.asyncio
    async def test_token_budget_warning_observes(self):
        event = make_event(
            "llm.pre_request",
            llm_model="gpt-3.5-turbo",
            token_count=85_000,
            token_budget=100_000,
        )
        verdicts = await self._server.evaluate(event)
        # The token-budget policy should OBSERVE
        token_verdicts = [
            v
            for v in verdicts
            if v.policy_name == "token-budget"
        ]
        assert len(token_verdicts) == 1
        assert (
            token_verdicts[0].decision == Decision.OBSERVE
        )

    @pytest.mark.asyncio
    async def test_token_budget_ok_allows(self):
        event = make_event(
            "llm.pre_request",
            llm_model="gpt-3.5-turbo",
            token_count=10_000,
            token_budget=100_000,
        )
        verdicts = await self._server.evaluate(event)
        token_verdicts = [
            v
            for v in verdicts
            if v.policy_name == "token-budget"
        ]
        assert token_verdicts[0].decision == Decision.ALLOW

    # ---- cost-budget -------------------------------------------------------

    @pytest.mark.asyncio
    async def test_cost_budget_exceeded_denies(self):
        event = make_event(
            "llm.pre_request",
            llm_model="gpt-3.5-turbo",
            cost_usd=1.50,
            cost_budget_usd=1.00,
        )
        verdicts = await self._server.evaluate(event)
        cost_verdicts = [
            v
            for v in verdicts
            if v.policy_name == "cost-budget"
        ]
        assert cost_verdicts[0].decision == Decision.DENY

    @pytest.mark.asyncio
    async def test_cost_budget_warning_observes(self):
        event = make_event(
            "llm.pre_request",
            llm_model="gpt-3.5-turbo",
            cost_usd=0.85,
            cost_budget_usd=1.00,
        )
        verdicts = await self._server.evaluate(event)
        cost_verdicts = [
            v
            for v in verdicts
            if v.policy_name == "cost-budget"
        ]
        assert cost_verdicts[0].decision == Decision.OBSERVE

    @pytest.mark.asyncio
    async def test_cost_budget_ok_allows(self):
        event = make_event(
            "llm.pre_request",
            llm_model="gpt-3.5-turbo",
            cost_usd=0.10,
            cost_budget_usd=1.00,
        )
        verdicts = await self._server.evaluate(event)
        cost_verdicts = [
            v
            for v in verdicts
            if v.policy_name == "cost-budget"
        ]
        assert cost_verdicts[0].decision == Decision.ALLOW

    @pytest.mark.asyncio
    async def test_cost_budget_tool_pre_invoke(self):
        """cost-budget also fires on tool.pre_invoke."""
        event = make_event(
            "tool.pre_invoke",
            tool_name="web_search",
            cost_usd=2.00,
            cost_budget_usd=1.00,
        )
        verdicts = await self._server.evaluate(event)
        cost_verdicts = [
            v
            for v in verdicts
            if v.policy_name == "cost-budget"
        ]
        assert len(cost_verdicts) == 1
        assert cost_verdicts[0].decision == Decision.DENY

    # ---- expensive-model-guard ---------------------------------------------

    @pytest.mark.asyncio
    async def test_expensive_model_low_budget_escalates(
        self,
    ):
        event = make_event(
            "llm.pre_request",
            llm_model="gpt-4",
            cost_usd=0.60,
            cost_budget_usd=1.00,
        )
        verdicts = await self._server.evaluate(event)
        guard = [
            v
            for v in verdicts
            if v.policy_name == "expensive-model-guard"
        ]
        assert guard[0].decision == Decision.ESCALATE
        assert guard[0].escalation.type == "human_confirm"

    @pytest.mark.asyncio
    async def test_expensive_model_high_budget_allows(self):
        event = make_event(
            "llm.pre_request",
            llm_model="gpt-4",
            cost_usd=0.10,
            cost_budget_usd=1.00,
        )
        verdicts = await self._server.evaluate(event)
        guard = [
            v
            for v in verdicts
            if v.policy_name == "expensive-model-guard"
        ]
        assert guard[0].decision == Decision.ALLOW

    @pytest.mark.asyncio
    async def test_cheap_model_low_budget_allows(self):
        event = make_event(
            "llm.pre_request",
            llm_model="gpt-3.5-turbo",
            cost_usd=0.90,
            cost_budget_usd=1.00,
        )
        verdicts = await self._server.evaluate(event)
        guard = [
            v
            for v in verdicts
            if v.policy_name == "expensive-model-guard"
        ]
        assert guard[0].decision == Decision.ALLOW

    @pytest.mark.asyncio
    async def test_claude_opus_low_budget_escalates(self):
        """claude-3-opus should also be flagged as expensive."""
        event = make_event(
            "llm.pre_request",
            llm_model="claude-3-opus-20240229",
            cost_usd=0.55,
            cost_budget_usd=1.00,
        )
        verdicts = await self._server.evaluate(event)
        guard = [
            v
            for v in verdicts
            if v.policy_name == "expensive-model-guard"
        ]
        assert guard[0].decision == Decision.ESCALATE


# ============================================================================
# Confirm Destructive — examples/confirm_destructive.py
# ============================================================================

DESTRUCTIVE_TOOLS = [
    r".*delete.*",
    r".*remove.*",
    r".*drop.*",
    r".*destroy.*",
    r".*purge.*",
    r".*truncate.*",
    r".*wipe.*",
    r"rm\b",
    r"rmdir\b",
]

HIGH_RISK_TOOLS = [
    r".*execute.*sql.*",
    r".*run.*command.*",
    r".*shell.*",
    r".*exec.*",
    r".*eval.*",
]


def _make_destructive_server() -> PolicyServer:
    server = PolicyServer(
        "confirm-destructive", version="1.0.0"
    )

    @server.policy(
        name="confirm-delete",
        events=["tool.pre_invoke"],
        context=[
            "payload.tool_name",
            "payload.tool_args",
        ],
    )
    async def confirm_delete(event):
        tool_name = event.payload.tool_name or ""
        tool_args = event.payload.tool_args or {}
        for pattern in DESTRUCTIVE_TOOLS:
            if re.match(pattern, tool_name.lower()):
                target = (
                    tool_args.get("target")
                    or tool_args.get("path")
                    or tool_args.get("id")
                    or str(tool_args)
                )
                return Verdict.escalate(
                    type="human_confirm",
                    prompt=f"Destructive: {tool_name} on {target}",
                    reasoning=f"Tool '{tool_name}' matches destructive pattern",
                    options=["Proceed", "Cancel"],
                    timeout_ms=60000,
                )
        return Verdict.allow()

    @server.policy(
        name="warn-high-risk",
        events=["tool.pre_invoke"],
        context=[
            "payload.tool_name",
            "payload.tool_args",
            "metadata.user_roles",
        ],
    )
    async def warn_high_risk(event):
        tool_name = event.payload.tool_name or ""
        user_roles = event.metadata.user_roles or []
        for pattern in HIGH_RISK_TOOLS:
            if re.match(pattern, tool_name.lower()):
                if "admin" in user_roles:
                    return Verdict.observe(
                        reasoning=f"High-risk '{tool_name}' by admin"
                    )
                return Verdict.escalate(
                    type="human_confirm",
                    prompt=f"Elevated privileges required: {tool_name}",
                    reasoning="Non-admin attempting high-risk tool",
                    options=[
                        "Request Approval",
                        "Cancel",
                    ],
                )
        return Verdict.allow()

    return server


class TestConfirmDestructive:
    """confirm-delete and warn-high-risk policies."""

    @pytest.fixture(autouse=True)
    def server(self):
        self._server = _make_destructive_server()

    # ---- confirm-delete ----------------------------------------------------

    @pytest.mark.asyncio
    async def test_delete_file_escalates(self):
        event = make_event(
            "tool.pre_invoke",
            tool_name="delete_file",
            tool_args={"path": "/data/important.csv"},
        )
        verdicts = await self._server.evaluate(event)
        cd = [
            v
            for v in verdicts
            if v.policy_name == "confirm-delete"
        ]
        assert cd[0].decision == Decision.ESCALATE
        assert cd[0].escalation.type == "human_confirm"
        assert "Proceed" in cd[0].escalation.options

    @pytest.mark.asyncio
    async def test_remove_item_escalates(self):
        event = make_event(
            "tool.pre_invoke",
            tool_name="remove_item",
            tool_args={"id": "item-42"},
        )
        verdicts = await self._server.evaluate(event)
        cd = [
            v
            for v in verdicts
            if v.policy_name == "confirm-delete"
        ]
        assert cd[0].decision == Decision.ESCALATE

    @pytest.mark.asyncio
    async def test_drop_table_escalates(self):
        event = make_event(
            "tool.pre_invoke",
            tool_name="drop_table",
            tool_args={"target": "users"},
        )
        verdicts = await self._server.evaluate(event)
        cd = [
            v
            for v in verdicts
            if v.policy_name == "confirm-delete"
        ]
        assert cd[0].decision == Decision.ESCALATE

    @pytest.mark.asyncio
    async def test_purge_cache_escalates(self):
        event = make_event(
            "tool.pre_invoke",
            tool_name="purge_cache",
            tool_args={},
        )
        verdicts = await self._server.evaluate(event)
        cd = [
            v
            for v in verdicts
            if v.policy_name == "confirm-delete"
        ]
        assert cd[0].decision == Decision.ESCALATE

    @pytest.mark.asyncio
    async def test_safe_tool_allows(self):
        event = make_event(
            "tool.pre_invoke",
            tool_name="search",
            tool_args={"query": "weather"},
        )
        verdicts = await self._server.evaluate(event)
        cd = [
            v
            for v in verdicts
            if v.policy_name == "confirm-delete"
        ]
        assert cd[0].decision == Decision.ALLOW

    # ---- warn-high-risk ----------------------------------------------------

    @pytest.mark.asyncio
    async def test_execute_sql_non_admin_escalates(self):
        event = make_event(
            "tool.pre_invoke",
            tool_name="execute_sql",
            tool_args={"query": "SELECT 1"},
            user_roles=["viewer"],
        )
        verdicts = await self._server.evaluate(event)
        hr = [
            v
            for v in verdicts
            if v.policy_name == "warn-high-risk"
        ]
        assert hr[0].decision == Decision.ESCALATE

    @pytest.mark.asyncio
    async def test_execute_sql_admin_observes(self):
        event = make_event(
            "tool.pre_invoke",
            tool_name="execute_sql",
            tool_args={"query": "SELECT 1"},
            user_roles=["admin"],
        )
        verdicts = await self._server.evaluate(event)
        hr = [
            v
            for v in verdicts
            if v.policy_name == "warn-high-risk"
        ]
        assert hr[0].decision == Decision.OBSERVE

    @pytest.mark.asyncio
    async def test_shell_command_non_admin_escalates(self):
        event = make_event(
            "tool.pre_invoke",
            tool_name="shell_exec",
            tool_args={"cmd": "ls -la"},
            user_roles=[],
        )
        verdicts = await self._server.evaluate(event)
        hr = [
            v
            for v in verdicts
            if v.policy_name == "warn-high-risk"
        ]
        assert hr[0].decision == Decision.ESCALATE

    @pytest.mark.asyncio
    async def test_eval_non_admin_escalates(self):
        event = make_event(
            "tool.pre_invoke",
            tool_name="eval",
            tool_args={"code": "1+1"},
            user_roles=["user"],
        )
        verdicts = await self._server.evaluate(event)
        hr = [
            v
            for v in verdicts
            if v.policy_name == "warn-high-risk"
        ]
        assert hr[0].decision == Decision.ESCALATE

    @pytest.mark.asyncio
    async def test_safe_tool_non_admin_allows(self):
        event = make_event(
            "tool.pre_invoke",
            tool_name="search",
            tool_args={"query": "hello"},
            user_roles=["viewer"],
        )
        verdicts = await self._server.evaluate(event)
        hr = [
            v
            for v in verdicts
            if v.policy_name == "warn-high-risk"
        ]
        assert hr[0].decision == Decision.ALLOW


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
