#!/usr/bin/env python3
import re

from apl import PolicyEvent, PolicyServer, Verdict

server = PolicyServer(
    name="input-received-policy",
    version="1.0.0",
)


@server.policy(
    name="block-profanity", events=["input.received"]
)
async def block_profanity(
    event: PolicyEvent,
) -> Verdict:

    profanity = [
        "fuck",
        "shit",
        "asshole",
        "bastard",
        "bitch",
    ]

    # check only the last user message
    user_msgs = [
        m for m in event.messages if m.role == "user"
    ]
    if not user_msgs:
        return Verdict.allow(
            reasoning="No user message"
        )

    latest = user_msgs[-1].content or ""
    # reject user queries that contain the listed profanities
    for word in profanity:
        if word in latest.lower():
            return Verdict.deny(
                reasoning=f"Profanity detected: '{word}'"
            )

    return Verdict.allow(reasoning="No profanity")


@server.policy(
    name="block-pii-sharing", events=["input.received"]
)
async def block_pii_sharing(
    event: PolicyEvent,
) -> Verdict:

    user_msgs = [
        m for m in event.messages if m.role == "user"
    ]
    if not user_msgs:
        return Verdict.allow(
            reasoning="No user message"
        )

    latest = user_msgs[-1].content or ""

    # SSN
    # reject user queries containing social security numbers
    if re.search(r"\b\d{3}-\d{2}-\d{4}\b", latest):
        return Verdict.deny(
            reasoning="Don't share SSN - blocked for your protection"
        )
    # credit card numbers
    # reject user queries containing credit card numbers
    if re.search(
        r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
        latest,
    ):
        return Verdict.deny(
            reasoning="Don't share credit card numbers"
        )

    return Verdict.allow(reasoning="No PII detected")


@server.policy(
    name="detect-prompt-injection",
    events=["input.received"],
)
async def detect_prompt_injection(
    event: PolicyEvent,
) -> Verdict:

    injection_patterns = [
        "ignore previous instructions",
        "ignore all previous",
        "disregard above",
        "forget your instructions",
        "new instructions:",
        "system prompt:",
        "you are now",
        "act as if",
        "pretend you are",
        "jailbreak",
    ]

    user_msgs = [
        m for m in event.messages if m.role == "user"
    ]
    if not user_msgs:
        return Verdict.allow(
            reasoning="No user message"
        )

    latest = user_msgs[-1].content or ""
    content_lower = latest.lower()

    # user queries containing any of the listed injection patterns are rejected
    for pattern in injection_patterns:
        if pattern in content_lower:
            return Verdict.deny(
                reasoning=f"Prompt injection detected: '{pattern}'"
            )

    return Verdict.allow(
        reasoning="No injection detected"
    )


@server.policy(
    name="enforce-min-length",
    events=["input.received"],
)
async def enforce_min_length(
    event: PolicyEvent,
) -> Verdict:

    user_msgs = [
        m for m in event.messages if m.role == "user"
    ]
    if not user_msgs:
        return Verdict.allow(
            reasoning="No user message"
        )

    latest = user_msgs[-1].content or ""

    # user queries < 3 chars long are rejected
    if len(latest.strip()) < 3:
        return Verdict.deny(
            reasoning=f"Input too short ({len(latest)} chars, min 3)"
        )

    return Verdict.allow(reasoning="Length OK")


if __name__ == "__main__":
    server.run(
        transport="http", host="0.0.0.0", port=8080
    )
