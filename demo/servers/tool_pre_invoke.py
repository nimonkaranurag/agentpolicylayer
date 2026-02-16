#!/usr/bin/env python3
from apl import PolicyEvent, PolicyServer, Verdict

server = PolicyServer(
    name="tool-pre-invoke-policy", version="1.0.0"
)


@server.policy(
    name="block-dangerous-tools",
    events=["tool.pre_invoke"],
)
async def block_dangerous_tools(
    event: PolicyEvent,
) -> Verdict:

    blocked_tools = [
        "execute_code",
        "shell_command",
        "run_script",
        "eval",
        "exec",
    ]

    tool_name = (
        event.payload.tool_name
        if event.payload
        else None
    )

    if tool_name and tool_name.lower() in [
        t.lower() for t in blocked_tools
    ]:
        return Verdict.deny(
            reasoning=f"Dangerous tool blocked: {tool_name}"
        )

    return Verdict.allow(
        reasoning=f"Tool '{tool_name}' permitted"
    )


@server.policy(
    name="restrict-email-domains",
    events=["tool.pre_invoke"],
)
async def restrict_email_domains(
    event: PolicyEvent,
) -> Verdict:

    tool_name = (
        event.payload.tool_name
        if event.payload
        else None
    )
    tool_args = (
        event.payload.tool_args
        if event.payload
        else {}
    )

    if tool_name != "send_email":
        return Verdict.allow(
            reasoning="Not an email tool"
        )

    recipient = (
        tool_args.get("to", "")
        if isinstance(tool_args, dict)
        else ""
    )
    approved_domains = [
        "@company.com",
        "@internal.org",
        "@partner.net",
    ]

    if not any(
        domain in recipient
        for domain in approved_domains
    ):
        return Verdict.deny(
            reasoning=f"Email to '{recipient}' blocked - only approved domains allowed"
        )

    return Verdict.allow(
        reasoning=f"Email to '{recipient}' approved"
    )


@server.policy(
    name="block-external-urls",
    events=["tool.pre_invoke"],
)
async def block_external_urls(
    event: PolicyEvent,
) -> Verdict:

    tool_name = (
        event.payload.tool_name
        if event.payload
        else None
    )
    tool_args = (
        event.payload.tool_args
        if event.payload
        else {}
    )

    if tool_name not in [
        "search_web",
        "fetch_url",
        "http_request",
    ]:
        return Verdict.allow(
            reasoning="Not a web tool"
        )

    url = tool_args.get("url", "") or tool_args.get(
        "query", ""
    )
    blocked_domains = [
        "malware.com",
        "phishing.net",
        "hack.org",
    ]

    for domain in blocked_domains:
        if domain in url.lower():
            return Verdict.deny(
                reasoning=f"Blocked domain: {domain}"
            )

    return Verdict.allow(reasoning="URL permitted")


@server.policy(
    name="escalate-financial-tools",
    events=["tool.pre_invoke"],
)
async def escalate_financial_tools(
    event: PolicyEvent,
) -> Verdict:

    financial_tools = [
        "send_payment",
        "transfer_funds",
        "make_purchase",
        "refund",
    ]

    tool_name = (
        event.payload.tool_name
        if event.payload
        else None
    )

    if tool_name and tool_name.lower() in [
        t.lower() for t in financial_tools
    ]:
        return Verdict.escalate(
            reasoning=f"Financial operation '{tool_name}' requires human approval"
        )

    return Verdict.allow(
        reasoning="Not a financial tool"
    )


@server.policy(
    name="limit-api-arguments",
    events=["tool.pre_invoke"],
)
async def limit_api_arguments(
    event: PolicyEvent,
) -> Verdict:

    tool_args = (
        event.payload.tool_args
        if event.payload
        else {}
    )

    if isinstance(tool_args, dict):
        for key, value in tool_args.items():
            if (
                isinstance(value, str)
                and len(value) > 10000
            ):
                return Verdict.deny(
                    reasoning=f"Argument '{key}' too large ({len(value)} chars, max 10000)"
                )

    return Verdict.allow(
        reasoning="Arguments within limits"
    )


if __name__ == "__main__":
    server.run(
        transport="http", host="0.0.0.0", port=8080
    )
