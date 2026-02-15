from __future__ import annotations

from apl.logging import APLLogger, get_logger, setup_logging
from apl.metrics.prometheus_exporter import export_metrics_to_prometheus
from apl.metrics.server_metrics import ServerMetrics


class TestServerMetrics:

    def test_initial_state(self):
        m = ServerMetrics()
        assert m.requests_total == 0
        assert m.errors_total == 0

    def test_record_request(self):
        m = ServerMetrics()
        m.record_request(event_type="output.pre_send", decision="allow", latency_ms=42.5)
        assert m.requests_total == 1

    def test_record_error(self):
        m = ServerMetrics()
        m.record_error()
        assert m.errors_total == 1


class TestPrometheusExporter:

    def test_export_format(self):
        m = ServerMetrics()
        m.record_request(event_type="output.pre_send", decision="allow", latency_ms=10.0)
        output = export_metrics_to_prometheus(m)
        assert "apl_requests_total 1" in output
        assert "apl_errors_total 0" in output
        assert "apl_latency_ms_avg" in output


class TestLogging:

    def test_get_logger_returns_apl_logger(self):
        logger = get_logger("test.module")
        assert isinstance(logger, APLLogger)

    def test_setup_logging_runs_without_error(self):
        setup_logging(level="DEBUG")
