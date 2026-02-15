from ...types import EventPayload

SAMPLE_PAYLOADS_BY_EVENT_TYPE = {
    "output.pre_send": EventPayload(
        output_text=(
            "Your SSN is 123-45-6789"
            " and email is test@example.com"
        )
    ),
    "tool.pre_invoke": EventPayload(
        tool_name="delete_file",
        tool_args={"path": "/important/data"},
    ),
    "llm.pre_request": EventPayload(
        llm_model="gpt-4"
    ),
    "input.received": EventPayload(),
}
