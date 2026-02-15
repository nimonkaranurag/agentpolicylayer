from dataclasses import dataclass

from apl.types import EventType


@dataclass
class PolicyCheckpoint:
    event_type: EventType
    node_name: str | None = None
    before_node_execution: bool = True
