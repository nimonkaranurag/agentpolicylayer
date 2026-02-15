from .server_metrics import ServerMetrics


def export_metrics_to_prometheus(metrics: ServerMetrics) -> str:
    lines = [
        "# HELP apl_requests_total Total number of policy evaluation requests",
        "# TYPE apl_requests_total counter",
        f"apl_requests_total {metrics.requests_total}",
        "",
        "# HELP apl_errors_total Total number of errors",
        "# TYPE apl_errors_total counter",
        f"apl_errors_total {metrics.errors_total}",
        "",
        "# HELP apl_latency_ms_avg Average evaluation latency in milliseconds",
        "# TYPE apl_latency_ms_avg gauge",
        f"apl_latency_ms_avg {metrics.average_latency_ms:.2f}",
        "",
        "# HELP apl_uptime_seconds Server uptime in seconds",
        "# TYPE apl_uptime_seconds gauge",
        f"apl_uptime_seconds {metrics.uptime_seconds:.0f}",
    ]

    if metrics.requests_by_event_type:
        lines.extend([
            "",
            "# HELP apl_requests_by_event_total Requests by event type",
            "# TYPE apl_requests_by_event_total counter",
        ])
        for event_type, count in metrics.requests_by_event_type.items():
            lines.append(f'apl_requests_by_event_total{{event="{event_type}"}} {count}')

    if metrics.verdicts_by_decision:
        lines.extend([
            "",
            "# HELP apl_verdicts_by_decision_total Verdicts by decision",
            "# TYPE apl_verdicts_by_decision_total counter",
        ])
        for decision, count in metrics.verdicts_by_decision.items():
            lines.append(f'apl_verdicts_by_decision_total{{decision="{decision}"}} {count}')

    return "\n".join(lines)
