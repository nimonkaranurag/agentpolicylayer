#!/usr/bin/env python3
"""
APL Usage Example

This demonstrates how to integrate APL into your agent workflow.
Shows:
1. Creating policy events manually
2. Using the decorator API
3. Handling verdicts
"""

import asyncio
import os
import sys

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),
)

from apl import (
    EventPayload,
    Message,
    PolicyDenied,
    PolicyEscalation,
    PolicyLayer,
    SessionMetadata,
    Verdict,
)


async def demo_manual_evaluation():
    """
    Demo 1: Manual policy evaluation

    This shows the low-level API where you explicitly create events
    and evaluate them.
    """
    print("\n" + "=" * 60)
    print("Demo 1: Manual Policy Evaluation")
    print("=" * 60)

    # Create policy layer and add servers
    policies = PolicyLayer()
    policies.add_server("stdio://./examples/pii_filter.py")
    policies.add_server(
        "stdio://./examples/budget_limiter.py"
    )

    # Connect to servers
    await policies.connect()

    # Simulate an output event with PII
    print("\nEvaluating output with SSN...")
    verdict = await policies.evaluate(
        event_type="output.pre_send",
        messages=[
            Message(role="user", content="What's my SSN?"),
            Message(
                role="assistant",
                content="Your SSN is 123-45-6789",
            ),
        ],
        payload=EventPayload(
            output_text="Your SSN is 123-45-6789"
        ),
        metadata=SessionMetadata(
            session_id="demo-session",
            user_id="user-123",
            token_count=1000,
            token_budget=10000,
        ),
    )

    print(f"  Decision: {verdict.decision.value}")
    print(f"  Reasoning: {verdict.reasoning}")
    if verdict.modification:
        print(
            f"  Modified output: {verdict.modification.value}"
        )

    # Test budget enforcement
    print("\nEvaluating LLM call near budget limit...")
    verdict = await policies.evaluate(
        event_type="llm.pre_request",
        messages=[],
        payload=EventPayload(llm_model="gpt-4"),
        metadata=SessionMetadata(
            session_id="demo-session",
            user_id="user-123",
            token_count=95000,
            token_budget=100000,  # 95% used
        ),
    )

    print(f"  Decision: {verdict.decision.value}")
    print(f"  Reasoning: {verdict.reasoning}")

    await policies.close()


async def demo_decorator_api():
    """
    Demo 2: Decorator-based API

    This shows the ergonomic decorator API for wrapping functions.
    """
    print("\n" + "=" * 60)
    print("Demo 2: Decorator API")
    print("=" * 60)

    policies = PolicyLayer()
    policies.add_server(
        "stdio://./examples/confirm_destructive.py"
    )

    # Define a tool function with policy checks
    @policies.on("tool.pre_invoke")
    async def execute_tool(tool_name: str, tool_args: dict):
        """Simulated tool execution."""
        print(f"  Executing {tool_name} with {tool_args}")
        return {"status": "success"}

    # Test with a safe tool
    print("\nCalling safe tool 'search'...")
    try:
        result = await execute_tool(
            "search", {"query": "weather"}
        )
        print(f"  Result: {result}")
    except PolicyDenied as e:
        print(f"  DENIED: {e.verdict.reasoning}")
    except PolicyEscalation as e:
        print(
            f"  ESCALATION: {e.verdict.escalation.prompt}"
        )

    # Test with a dangerous tool
    print("\nCalling dangerous tool 'delete_file'...")
    try:
        result = await execute_tool(
            "delete_file", {"path": "/important/data"}
        )
        print(f"  Result: {result}")
    except PolicyDenied as e:
        print(f"  DENIED: {e.verdict.reasoning}")
    except PolicyEscalation as e:
        print(f"  ESCALATION REQUIRED:")
        print(f"    {e.verdict.escalation.prompt}")
        print(
            f"    Options: {e.verdict.escalation.options}"
        )

    await policies.close()


async def demo_composition():
    """
    Demo 3: Policy composition

    Shows how multiple policies combine their verdicts.
    """
    print("\n" + "=" * 60)
    print("Demo 3: Policy Composition")
    print("=" * 60)

    from apl import CompositionConfig, CompositionMode

    # Configure composition
    policies = PolicyLayer(
        composition=CompositionConfig(
            mode=CompositionMode.DENY_OVERRIDES,  # Any deny wins
            parallel=True,  # Evaluate in parallel
            timeout_ms=1000,
        )
    )

    # Add multiple policy servers
    policies.add_server("stdio://./examples/pii_filter.py")
    policies.add_server(
        "stdio://./examples/budget_limiter.py"
    )
    policies.add_server(
        "stdio://./examples/confirm_destructive.py"
    )

    await policies.connect()

    # Event that triggers multiple policies
    print(
        "\nEvaluating tool call with PII and low budget..."
    )
    verdict = await policies.evaluate(
        event_type="tool.pre_invoke",
        messages=[],
        payload=EventPayload(
            tool_name="send_email",
            tool_args={
                "to": "test@test.com",
                "body": "SSN: 123-45-6789",
            },
        ),
        metadata=SessionMetadata(
            session_id="demo-session",
            token_count=99000,
            token_budget=100000,
            cost_usd=0.95,
            cost_budget_usd=1.00,
        ),
    )

    print(f"  Final Decision: {verdict.decision.value}")
    print(f"  Reasoning: {verdict.reasoning}")
    print(f"  Policy: {verdict.policy_name}")

    await policies.close()


async def main():
    """Run all demos."""
    print("=" * 60)
    print("APL (Agent Policy Layer) - Demo")
    print("=" * 60)

    # Note: In a real scenario, you'd have the policy servers running.
    # For this demo, we'll just show the API patterns.

    print("\nNote: This demo shows the API patterns.")
    print(
        "To run with real policy servers, start them first:"
    )
    print("  python examples/pii_filter.py")
    print("  python examples/budget_limiter.py")
    print("  python examples/confirm_destructive.py")

    # Uncomment to run demos (requires policy servers running)
    # await demo_manual_evaluation()
    # await demo_decorator_api()
    # await demo_composition()

    # Instead, let's show a simple inline example
    print("\n" + "=" * 60)
    print("Inline Policy Example (no external server)")
    print("=" * 60)

    from apl import PolicyEvent, PolicyServer, Verdict

    # You can also create policies inline for testing
    server = PolicyServer("inline-test")

    @server.policy(
        name="always-warn",
        events=["output.pre_send"],
        context=["payload.output_text"],
    )
    async def always_warn(event: PolicyEvent) -> Verdict:
        return Verdict.observe(
            reasoning="This is just a test observation",
            trace={
                "output_length": len(
                    event.payload.output_text or ""
                )
            },
        )

    # Create a test event
    import uuid
    from datetime import datetime

    from apl import EventPayload, EventType, SessionMetadata

    event = PolicyEvent(
        id=str(uuid.uuid4()),
        type=EventType.OUTPUT_PRE_SEND,
        timestamp=datetime.utcnow(),
        messages=[
            Message(
                role="assistant", content="Hello, world!"
            )
        ],
        payload=EventPayload(output_text="Hello, world!"),
        metadata=SessionMetadata(session_id="test"),
    )

    verdicts = await server.evaluate(event)

    for v in verdicts:
        print(f"\nVerdict from '{v.policy_name}':")
        print(f"  Decision: {v.decision.value}")
        print(f"  Reasoning: {v.reasoning}")
        print(f"  Evaluation time: {v.evaluation_ms:.2f}ms")


if __name__ == "__main__":
    asyncio.run(main())
