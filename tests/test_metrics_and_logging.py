from __future__ import annotations

import logging

from apl.logging import (
    APLLogger,
    get_logger,
    setup_logging,
)
from apl.metrics.prometheus_exporter import (
    export_metrics_to_prometheus,
)
from apl.metrics.server_metrics import ServerMetrics


class TestServerMetrics:
    def test_initial_state(self):
        m = ServerMetrics()
        assert m.requests_total == 0
        assert m.errors_total == 0

    def test_record_request(self):
        m = ServerMetrics()
        m.record_request(
            event_type="output.pre_send",
            decision="allow",
            latency_ms=42.5,
        )
        assert m.requests_total == 1

    def test_record_error(self):
        m = ServerMetrics()
        m.record_error()
        assert m.errors_total == 1


class TestPrometheusExporter:
    def test_export_format(self):
        m = ServerMetrics()
        m.record_request(
            event_type="output.pre_send",
            decision="allow",
            latency_ms=10.0,
        )
        output = export_metrics_to_prometheus(m)
        assert "apl_requests_total 1" in output
        assert "apl_errors_total 0" in output
        assert "apl_latency_ms_avg" in output


class TestLogging:
    def test_get_logger_returns_apl_logger(self):
        logger = get_logger("test.module")
        assert isinstance(logger, APLLogger)

    def test_setup_logging_configures_apl_root_logger(self):
        # Pre-fix this test had no assertion — it would have passed even if
        # setup_logging silently configured nothing. Assert the observable effect:
        # the `apl` root logger gets the requested level and exactly one handler
        # (handlers are cleared first, so re-running setup never stacks duplicates).
        logger = setup_logging(level="DEBUG")
        assert isinstance(logger, APLLogger)

        apl_root = logging.getLogger("apl")
        assert apl_root.level == logging.DEBUG
        assert len(apl_root.handlers) == 1

    def test_setup_logging_uses_plain_handler_for_stdio(self):
        # rich_output=False is the stdio path (stdout must stay clean for the JSON
        # protocol, so logs go to a plain stderr StreamHandler).
        setup_logging(level="WARNING", rich_output=False)

        apl_root = logging.getLogger("apl")
        assert apl_root.level == logging.WARNING
        assert isinstance(apl_root.handlers[0], logging.StreamHandler)
