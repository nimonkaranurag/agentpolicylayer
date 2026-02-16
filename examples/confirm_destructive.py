#!/usr/bin/env python3
"""
Destructive Action Confirmation Policy

Requires human confirmation before executing destructive operations.
Demonstrates the ESCALATE verdict type.

Run: python examples/confirm_destructive.py
"""

import os
import re
import sys

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),
)

from apl import PolicyEvent, PolicyServer, Verdict

server = PolicyServer(
    name="confirm-destructive",
    version="1.0.0",
    description="Requires confirmation for destructive operations",
)


# Dangerous patterns
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


@server.policy(
    name="confirm-delete",
    events=["tool.pre_invoke"],
    context=["payload.tool_name", "payload.tool_args"],
    description="Requires human confirmation for delete operations",
)
async def confirm_delete(
    event: PolicyEvent,
) -> Verdict:
    """
    Check if tool is destructive and require confirmation.
    """
    tool_name = event.payload.tool_name or ""
    tool_args = event.payload.tool_args or {}

    # Check against destructive patterns
    for pattern in DESTRUCTIVE_TOOLS:
        if re.match(pattern, tool_name.lower()):
            # Build informative prompt
            target = (
                tool_args.get("target")
                or tool_args.get("path")
                or tool_args.get("id")
                or str(tool_args)
            )

            return Verdict.escalate(
                type="human_confirm",
                prompt=f"⚠️ Destructive action requested:\n\nTool: {tool_name}\nTarget: {target}\n\nProceed?",
                reasoning=f"Tool '{tool_name}' matches destructive pattern",
                options=["Proceed", "Cancel"],
                timeout_ms=60000,  # 1 minute to decide
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
    description="Warns about high-risk operations, blocks for non-admin users",
)
async def warn_high_risk(
    event: PolicyEvent,
) -> Verdict:
    """
    High-risk operations require admin role or explicit confirmation.
    """
    tool_name = event.payload.tool_name or ""
    user_roles = event.metadata.user_roles or []

    for pattern in HIGH_RISK_TOOLS:
        if re.match(pattern, tool_name.lower()):
            # Admins get a warning but can proceed
            if "admin" in user_roles:
                return Verdict.observe(
                    reasoning=f"High-risk tool '{tool_name}' used by admin",
                    trace={
                        "tool": tool_name,
                        "roles": user_roles,
                    },
                )

            # Non-admins need confirmation
            return Verdict.escalate(
                type="human_confirm",
                prompt=f"🔒 This operation requires elevated privileges.\n\nTool: {tool_name}\n\nRequest admin approval?",
                reasoning=f"Non-admin user attempting high-risk tool",
                options=["Request Approval", "Cancel"],
            )

    return Verdict.allow()


if __name__ == "__main__":
    server.run()
