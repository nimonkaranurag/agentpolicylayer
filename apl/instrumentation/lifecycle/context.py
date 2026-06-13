from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from apl.types import Message


def _is_message_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(m, Message) for m in value)


@dataclass
class LifecycleContext:
    raw_messages: Any = None
    apl_messages: List[Message] = field(default_factory=list)
    model_name: str = "unknown"

    original_kwargs: Dict[str, Any] = field(default_factory=dict)
    modified_kwargs: Dict[str, Any] = field(default_factory=dict)

    response: Optional[Any] = None
    response_text: str = ""

    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    tool_result: Optional[Any] = None

    proposed_plan: Optional[List[str]] = None

    source_agent: Optional[str] = None
    target_agent: Optional[str] = None
    handoff_payload: Optional[Dict[str, Any]] = None

    response_text_applier: Optional[Callable[[Any, str], Any]] = None
    message_adapter_to_raw: Optional[Callable[[List[Message]], Any]] = None

    # Set when a policy modifies the request messages, so the provider knows to
    # write them back into the slot its SDK actually reads (a kwarg for
    # chat-completions, a positional arg for LangChain's invoke()).
    request_messages_modified: bool = False

    def modify_request_messages(self, new_messages: Any) -> None:
        # Update apl_messages so a subsequent modification in the same sequence
        # reads the already-modified value, and flag it so the provider converts
        # (via from_apl_messages) and writes it to the right SDK slot. Writing a
        # raw `messages=` kwarg here was the bug: it shipped foreign-typed APL
        # Message objects on chat-completions and was ignored entirely by
        # LangChain's positional invoke(), making input redaction a silent no-op.
        self.apl_messages = new_messages
        self.request_messages_modified = True

    def effective_request_messages(self) -> Any:
        """
        The request messages to actually pass to the SDK, converted to its shape.

        Converts the (possibly modified) APL messages back through the provider's
        ``from_apl_messages`` when they are APL :class:`~apl.types.Message` objects; a
        modification that replaced them with already-native values is passed through
        untouched.
        """
        messages = self.apl_messages
        if self.message_adapter_to_raw is not None and _is_message_list(messages):
            return self.message_adapter_to_raw(messages)
        return messages

    def modify_response_text(self, new_text: str) -> None:
        self.response_text = new_text
        if self.response is not None and self.response_text_applier is not None:
            self.response = self.response_text_applier(self.response, new_text)

    def modify_tool_args(self, new_args: Dict[str, Any]) -> None:
        self.tool_args = new_args

    def modify_tool_result(self, new_result: Any) -> None:
        self.tool_result = new_result

    def modify_proposed_plan(self, new_plan: List[str]) -> None:
        self.proposed_plan = new_plan

    def modify_handoff_payload(self, new_payload: Dict[str, Any]) -> None:
        self.handoff_payload = new_payload

    def get_effective_kwargs(self) -> Dict[str, Any]:
        return {
            **self.original_kwargs,
            **self.modified_kwargs,
        }
