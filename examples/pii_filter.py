#!/usr/bin/env python3
"""
PII Redaction Policy

A simple policy that redacts common PII patterns from agent outputs.
This demonstrates the core APL developer experience: ~30 lines for a real policy.

Run: python examples/pii_filter.py
"""

import os
import re
import sys

# Add parent to path for local development
sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),
)

from apl import PolicyEvent, PolicyServer, Verdict

server = PolicyServer(
    name="pii-filter",
    version="1.0.0",
    description="Redacts common PII patterns (SSN, credit cards, emails) from outputs",
)


# Pattern definitions
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


@server.policy(
    name="redact-pii",
    events=["output.pre_send"],
    context=["payload.output_text"],
    description="Scans output text for PII patterns and redacts them",
)
async def redact_pii(event: PolicyEvent) -> Verdict:
    """
    Scan output text for PII and redact if found.
    """
    text = event.payload.output_text

    if not text:
        return Verdict.allow()

    # Track what we found
    found = []
    redacted_text = text

    for name, (pattern, replacement) in PATTERNS.items():
        matches = re.findall(pattern, redacted_text)
        if matches:
            found.append(
                f"{name}: {len(matches)} occurrence(s)"
            )
            redacted_text = re.sub(
                pattern, replacement, redacted_text
            )

    if found:
        return Verdict.modify(
            target="output",
            operation="replace",
            value=redacted_text,
            reasoning=f"Redacted PII: {', '.join(found)}",
            confidence=0.95,
        )

    return Verdict.allow()


@server.policy(
    name="block-pii-in-tools",
    events=["tool.pre_invoke"],
    context=["payload.tool_name", "payload.tool_args"],
    description="Prevents PII from being passed to external tools",
)
async def block_pii_in_tools(event: PolicyEvent) -> Verdict:
    """
    Block tool calls that would send PII to external services.
    """
    tool_args = event.payload.tool_args or {}
    args_str = str(tool_args)

    for name, (pattern, _) in PATTERNS.items():
        if re.search(pattern, args_str):
            return Verdict.deny(
                reasoning=f"Tool call contains {name} - refusing to send to external tool",
                confidence=0.9,
            )

    return Verdict.allow()


if __name__ == "__main__":
    server.run()
