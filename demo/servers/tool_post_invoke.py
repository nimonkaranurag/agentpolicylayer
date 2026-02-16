#!/usr/bin/env python3
import re

from apl import PolicyEvent, PolicyServer, Verdict

server = PolicyServer(
    name="tool-post-invoke-policy", version="1.0.0"
)


@server.policy(
    name="redact-ssn", events=["tool.post_invoke"]
)
async def redact_ssn(event: PolicyEvent) -> Verdict:
    """Redact SSNs from tool output."""
    result = (
        event.payload.tool_result
        if event.payload
        else ""
    )
    if not result:
        return Verdict.allow(reasoning="No result")

    result_str = str(result)
    ssn_pattern = r"\b\d{3}-\d{2}-\d{4}\b"

    if re.search(ssn_pattern, result_str):
        redacted = re.sub(
            ssn_pattern, "[SSN REDACTED]", result_str
        )
        return Verdict.modify(
            target="output",
            operation="replace",
            value=redacted,
            reasoning="SSN redacted from tool output",
        )

    return Verdict.allow(reasoning="No SSN found")


@server.policy(
    name="redact-api-keys", events=["tool.post_invoke"]
)
async def redact_api_keys(
    event: PolicyEvent,
) -> Verdict:
    """Redact API keys from tool output."""
    result = (
        event.payload.tool_result
        if event.payload
        else ""
    )
    if not result:
        return Verdict.allow(reasoning="No result")

    result_str = str(result)
    key_patterns = [
        (
            r"sk[_-]live[_-][a-zA-Z0-9]{20,}",
            "[STRIPE_KEY]",
        ),
        (
            r"sk[_-]test[_-][a-zA-Z0-9]{20,}",
            "[STRIPE_TEST_KEY]",
        ),
        (r"AKIA[A-Z0-9]{16}", "[AWS_KEY]"),
        (r"ghp_[a-zA-Z0-9]{36}", "[GITHUB_TOKEN]"),
        (r"xox[baprs]-[a-zA-Z0-9-]+", "[SLACK_TOKEN]"),
    ]

    redacted = result_str
    found = False
    for pattern, replacement in key_patterns:
        if re.search(pattern, redacted):
            found = True
            redacted = re.sub(
                pattern, replacement, redacted
            )

    if found:
        return Verdict.modify(
            target="output",
            operation="replace",
            value=redacted,
            reasoning="API keys redacted",
        )

    return Verdict.allow(reasoning="No API keys found")


@server.policy(
    name="sanitize-errors", events=["tool.post_invoke"]
)
async def sanitize_errors(
    event: PolicyEvent,
) -> Verdict:

    error = (
        event.payload.tool_error
        if event.payload
        else None
    )
    if not error:
        return Verdict.allow(reasoning="No error")

    error_str = str(error)

    # Remove stack traces and paths
    if (
        "Traceback" in error_str
        or "/home/" in error_str
        or "\\Users\\" in error_str
    ):
        return Verdict.modify(
            target="output",
            operation="replace",
            value="An error occurred. Please try again or contact support.",
            reasoning="Detailed error sanitized",
        )

    return Verdict.allow(reasoning="Error OK to show")


@server.policy(
    name="limit-output-size",
    events=["tool.post_invoke"],
)
async def limit_output_size(
    event: PolicyEvent,
) -> Verdict:

    result = (
        event.payload.tool_result
        if event.payload
        else ""
    )
    result_str = str(result)
    max_size = 5000

    if len(result_str) > max_size:
        truncated = (
            result_str[:max_size]
            + "\n...[TRUNCATED - output too large]"
        )
        return Verdict.modify(
            target="output",
            operation="replace",
            value=truncated,
            reasoning=f"Output truncated from {len(result_str)} to {max_size} chars",
        )

    return Verdict.allow(
        reasoning=f"Output size OK: {len(result_str)}"
    )


@server.policy(
    name="block-sensitive-paths",
    events=["tool.post_invoke"],
)
async def block_sensitive_paths(
    event: PolicyEvent,
) -> Verdict:

    result = (
        event.payload.tool_result
        if event.payload
        else ""
    )
    result_str = str(result)

    sensitive_paths = [
        "/etc/passwd",
        "/etc/shadow",
        ".ssh/",
        "id_rsa",
        ".env",
        "credentials",
        "secrets.yaml",
        ".aws/",
    ]

    for path in sensitive_paths:
        if path in result_str.lower():
            return Verdict.deny(
                reasoning=f"Sensitive path in output: {path}"
            )

    return Verdict.allow(
        reasoning="No sensitive paths"
    )


if __name__ == "__main__":
    server.run(
        transport="http", host="0.0.0.0", port=8080
    )
