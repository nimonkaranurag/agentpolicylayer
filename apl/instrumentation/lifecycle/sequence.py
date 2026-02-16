from dataclasses import dataclass, field
from typing import List

from ..events.base_event import BaseEvent


@dataclass
class EventSequence:
    name: str
    events: List[BaseEvent] = field(
        default_factory=list
    )

    def add_event(
        self, event: BaseEvent
    ) -> "EventSequence":
        self.events.append(event)
        return self

    def prepend_event(
        self, event: BaseEvent
    ) -> "EventSequence":
        self.events.insert(0, event)
        return self

    def __iter__(self):
        return iter(self.events)

    def __len__(self):
        return len(self.events)
