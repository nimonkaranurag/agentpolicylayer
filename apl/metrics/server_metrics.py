from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ServerMetrics:
    requests_total: int = 0
    requests_by_event_type: dict[str, int] = field(
        default_factory=dict
    )
    verdicts_by_decision: dict[str, int] = field(
        default_factory=dict
    )
    latency_sum_ms: float = 0.0
    latency_count: int = 0
    errors_total: int = 0
    start_time: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    def record_request(
        self,
        event_type: str,
        decision: str,
        latency_ms: float,
    ) -> None:
        self.requests_total += 1
        self.requests_by_event_type[event_type] = (
            self.requests_by_event_type.get(
                event_type, 0
            )
            + 1
        )
        self.verdicts_by_decision[decision] = (
            self.verdicts_by_decision.get(decision, 0)
            + 1
        )
        self.latency_sum_ms += latency_ms
        self.latency_count += 1

    def record_error(self) -> None:
        self.errors_total += 1

    @property
    def average_latency_ms(self) -> float:
        if self.latency_count == 0:
            return 0.0
        return self.latency_sum_ms / self.latency_count

    @property
    def uptime_seconds(self) -> float:
        return (
            datetime.now(timezone.utc)
            - self.start_time
        ).total_seconds()
