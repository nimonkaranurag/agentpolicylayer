#!/usr/bin/env python3
"""
Policy Server: SESSION_START / SESSION_END
==========================================
Controls session lifecycle.

Metadata is in: event.metadata.session_id, event.metadata.user_id

Client: chat.py or tools.py
"""

from apl import PolicyEvent, PolicyServer, Verdict

server = PolicyServer(
    name="session-events-policy", version="1.0.0"
)

# Simulated state (in production, use Redis/DB)
BLOCKED_USERS = {
    "banned_user",
    "spam_account",
    "malicious_actor",
}
RATE_LIMITS = {}  # user_id -> session_count


@server.policy(
    name="block-banned-users", events=["session.start"]
)
async def block_banned_users(
    event: PolicyEvent,
) -> Verdict:

    user_id = (
        event.metadata.user_id
        if event.metadata
        else None
    )

    if user_id in BLOCKED_USERS:
        return Verdict.deny(
            reasoning=f"User '{user_id}' is banned"
        )

    return Verdict.allow(
        reasoning=f"User '{user_id}' permitted"
    )


@server.policy(
    name="require-user-id", events=["session.start"]
)
async def require_user_id(
    event: PolicyEvent,
) -> Verdict:

    user_id = (
        event.metadata.user_id
        if event.metadata
        else None
    )

    if not user_id or user_id == "anonymous":
        return Verdict.deny(
            reasoning="Authentication required"
        )

    return Verdict.allow(
        reasoning=f"User '{user_id}' authenticated"
    )


@server.policy(
    name="log-session-start", events=["session.start"]
)
async def log_session_start(
    event: PolicyEvent,
) -> Verdict:

    session_id = (
        event.metadata.session_id
        if event.metadata
        else "unknown"
    )
    user_id = (
        event.metadata.user_id
        if event.metadata
        else "unknown"
    )

    print(
        f"[AUDIT] Session started: {session_id} by user {user_id}"
    )

    return Verdict.observe(
        reasoning="Session start logged"
    )


@server.policy(
    name="log-session-end", events=["session.end"]
)
async def log_session_end(
    event: PolicyEvent,
) -> Verdict:

    session_id = (
        event.metadata.session_id
        if event.metadata
        else "unknown"
    )
    user_id = (
        event.metadata.user_id
        if event.metadata
        else "unknown"
    )

    print(
        f"[AUDIT] Session ended: {session_id} by user {user_id}"
    )

    return Verdict.observe(
        reasoning="Session end logged"
    )


@server.policy(
    name="enforce-session-naming",
    events=["session.start"],
)
async def enforce_session_naming(
    event: PolicyEvent,
) -> Verdict:
    """Enforce session ID format."""
    session_id = (
        event.metadata.session_id
        if event.metadata
        else ""
    )

    if not session_id or len(session_id) < 5:
        return Verdict.deny(
            reasoning="Invalid session ID format"
        )

    return Verdict.allow(reasoning="Session ID valid")


if __name__ == "__main__":
    server.run(
        transport="http", host="0.0.0.0", port=8080
    )
