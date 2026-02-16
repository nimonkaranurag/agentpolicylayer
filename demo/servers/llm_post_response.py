#!/usr/bin/env python3
"""
Policy Server: LLM_POST_RESPONSE
================================
Filters LLM responses before they're processed further.

Response is in: event.payload.llm_response['content']

Client: chat.py or tools.py
"""

import re

from apl import PolicyEvent, PolicyServer, Verdict

server = PolicyServer(
    name="llm-post-response-policy", version="1.0.0"
)


def get_response_content(event: PolicyEvent) -> str:

    llm_response = (
        event.payload.llm_response
        if event.payload
        else None
    )
    if not llm_response:
        return ""
    return (
        llm_response.get("content", "")
        if isinstance(llm_response, dict)
        else str(llm_response)
    )


@server.policy(
    name="redact-emails", events=["llm.post_response"]
)
async def redact_emails(event: PolicyEvent) -> Verdict:

    content = get_response_content(event)
    if not content:
        return Verdict.allow(reasoning="No content")

    email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    emails = re.findall(email_pattern, content)

    if emails:
        redacted = re.sub(
            email_pattern, "[EMAIL REDACTED]", content
        )
        return Verdict.modify(
            target="output",
            operation="replace",
            value=redacted,
            reasoning=f"Redacted {len(emails)} email(s)",
        )

    return Verdict.allow(reasoning="No emails")


@server.policy(
    name="redact-phone-numbers",
    events=["llm.post_response"],
)
async def redact_phone_numbers(
    event: PolicyEvent,
) -> Verdict:

    content = get_response_content(event)
    if not content:
        return Verdict.allow(reasoning="No content")

    phone_patterns = [
        r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b",  # US
        r"\+\d{1,3}[-.\s]?\d{2,4}[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b",  # International
    ]

    redacted = content
    found = False
    for pattern in phone_patterns:
        if re.search(pattern, redacted):
            found = True
            redacted = re.sub(
                pattern, "[PHONE REDACTED]", redacted
            )

    if found:
        return Verdict.modify(
            target="output",
            operation="replace",
            value=redacted,
            reasoning="Redacted phone number(s)",
        )

    return Verdict.allow(reasoning="No phone numbers")


@server.policy(
    name="block-fake-urls",
    events=["llm.post_response"],
)
async def block_fake_urls(
    event: PolicyEvent,
) -> Verdict:

    content = get_response_content(event)
    if not content:
        return Verdict.allow(reasoning="No content")

    # Common hallucinated URL patterns
    fake_patterns = [
        r"https?://(?:www\.)?example\d*\.com/[a-z0-9/-]+",
        r"https?://(?:www\.)?fake[a-z]*\.com",
        r"https?://(?:www\.)?sample[a-z]*\.org",
    ]

    for pattern in fake_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return Verdict.deny(
                reasoning="Response contains potentially fake URL"
            )

    return Verdict.allow(
        reasoning="No fake URLs detected"
    )


@server.policy(
    name="block-code-execution-instructions",
    events=["llm.post_response"],
)
async def block_code_execution(
    event: PolicyEvent,
) -> Verdict:

    content = get_response_content(event)
    if not content:
        return Verdict.allow(reasoning="No content")

    dangerous = [
        "rm -rf /",
        "rm -rf ~",
        ":(){ :|:& };:",  # fork bomb
        "dd if=/dev/zero",
        "mkfs.",
        "> /dev/sda",
        "chmod -R 777 /",
        "sudo rm -rf",
    ]

    content_lower = content.lower()
    for cmd in dangerous:
        if cmd.lower() in content_lower:
            return Verdict.deny(
                reasoning=f"Dangerous command blocked: {cmd}"
            )

    return Verdict.allow(
        reasoning="No dangerous commands"
    )


@server.policy(
    name="flag-uncertainty",
    events=["llm.post_response"],
)
async def flag_uncertainty(
    event: PolicyEvent,
) -> Verdict:

    content = get_response_content(event)
    if not content:
        return Verdict.allow(reasoning="No content")

    uncertainty_markers = [
        "i'm not sure",
        "i think",
        "probably",
        "might be",
        "i believe",
        "as far as i know",
        "i could be wrong",
    ]

    content_lower = content.lower()
    for marker in uncertainty_markers:
        if marker in content_lower:
            warning = "\n\n⚠️ *This response contains uncertain information. Please verify independently.*"
            return Verdict.modify(
                target="output",
                operation="append",
                value=warning,
                reasoning=f"Uncertainty detected: '{marker}'",
            )

    return Verdict.allow(
        reasoning="No uncertainty markers"
    )


if __name__ == "__main__":
    server.run(
        transport="http", host="0.0.0.0", port=8080
    )
