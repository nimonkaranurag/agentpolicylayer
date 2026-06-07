from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click

from ...types import (
    EventPayload,
    EventType,
    Message,
    PolicyEvent,
    SessionMetadata,
)
from .. import cli, console
from ..branding import print_status, render_banner
from ..formatting import RichCommand
from ..policy_source import load_policy_server
from ..renderers import render_verdict_table

# Representative payloads for the common event types; any other valid event type
# falls back to an empty payload, which is enough to exercise the policy handler.
_SAMPLE_PAYLOADS: dict[str, EventPayload] = {
    "output.pre_send": EventPayload(
        output_text="Your SSN is 123-45-6789 and email is test@example.com"
    ),
    "tool.pre_invoke": EventPayload(
        tool_name="delete_file",
        tool_args={"path": "/important/data"},
    ),
    "llm.pre_request": EventPayload(llm_model="gpt-4"),
    "input.received": EventPayload(),
}


@cli.command(cls=RichCommand)
@click.argument("path", type=click.Path(exists=True))
@click.option(
    "-e",
    "--event",
    type=click.Choice([event_type.value for event_type in EventType]),
    default=EventType.OUTPUT_PRE_SEND.value,
    help="Event type to test",
)
@click.option("-p", "--payload", default=None, help="JSON payload")
def test(path: str, event: str, payload: Optional[str]):
    """
    Test a policy with sample events.

    Examples:
      apl test ./pii_filter.py
      apl test ./policy.yaml -e tool.pre_invoke
    """
    render_banner(console, "mini")
    console.print()
    print_status(console, f"Testing: [cyan]{path}[/cyan]", "loading")

    from ...logging import setup_logging

    logger = setup_logging(level="WARNING")

    server = load_policy_server(Path(path), logger)
    if server is None:
        print_status(console, "Failed to load policy", "error")
        sys.exit(1)

    test_event = _build_test_event(event, payload)

    console.print()
    print_status(console, f"Event type: [cyan]{event}[/cyan]", "info")

    verdicts = asyncio.run(server.evaluate(test_event))
    render_verdict_table(console, verdicts)


def _build_test_event(event_type: str, payload_json: Optional[str]) -> PolicyEvent:
    return PolicyEvent(
        id=str(uuid.uuid4()),
        type=EventType(event_type),
        timestamp=datetime.now(timezone.utc),
        messages=[Message(role="user", content="Test message")],
        payload=_resolve_payload(event_type, payload_json),
        metadata=SessionMetadata(
            session_id="test-session",
            user_id="test-user",
            token_count=1000,
            token_budget=10000,
        ),
    )


def _resolve_payload(event_type: str, payload_json: Optional[str]) -> EventPayload:
    if payload_json is None:
        return _SAMPLE_PAYLOADS.get(event_type, EventPayload())

    try:
        data = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        raise click.BadParameter(f"--payload is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise click.BadParameter("--payload must be a JSON object")

    try:
        return EventPayload(**data)
    except Exception as exc:
        raise click.BadParameter(f"--payload does not match the event schema: {exc}")
