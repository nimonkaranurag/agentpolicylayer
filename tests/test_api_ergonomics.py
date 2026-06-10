from __future__ import annotations

import inspect
import logging

import pytest

import apl
from apl import (
    CompositionConfig,
    FailMode,
    PolicyLayer,
    PolicyServer,
    Verdict,
)
from apl.types import PROTOCOL_VERSION


class _FakeGraph:
    """
    Minimal LangGraph-StateGraph stand-in (duck-typed, no langgraph dep).
    """

    def __init__(self) -> None:
        self.nodes = {"greet": lambda state: state}

    def add_node(self, *args, **kwargs) -> None: ...

    def add_edge(self, *args, **kwargs) -> None: ...


# =============================================================================
# PolicyLayer.wrap
# =============================================================================


class TestPolicyLayerWrap:
    def test_wrap_actually_wraps_graph_nodes(self):
        # Previously _wrap_langgraph returned the graph untouched ("not yet
        # implemented"), so the node object was unchanged. Now it delegates to
        # APLGraphWrapper, which replaces each node with a policy-enforcing wrapper.
        graph = _FakeGraph()
        original_node = graph.nodes["greet"]

        result = PolicyLayer().wrap(graph)

        assert result is graph
        assert graph.nodes["greet"] is not original_node

    def test_wrap_rejects_unsupported_object(self):
        # A silently-unwrapped agent would run with NO enforcement — exactly the
        # fail-open trap this layer prevents. Unsupported types must raise.
        with pytest.raises(TypeError):
            PolicyLayer().wrap(object())

    def test_wrap_delegates_to_adapter_with_this_layer(self):
        # The contract: wrap() builds APLGraphWrapper(self) and calls .wrap(graph),
        # so the adapter enforces THIS layer's servers/config — not a fresh empty
        # one. Mock the adapter to assert the delegation precisely (robust to the
        # adapter's own internals).
        from unittest.mock import patch

        layer = PolicyLayer()
        graph = _FakeGraph()
        with patch("apl.adapters.APLGraphWrapper") as mock_wrapper:
            mock_wrapper.return_value.wrap.return_value = graph
            layer.wrap(graph)

        mock_wrapper.assert_called_once_with(layer)
        mock_wrapper.return_value.wrap.assert_called_once_with(graph)


# =============================================================================
# Public exports / __all__
# =============================================================================


class TestPublicExports:
    def test_apl_graph_wrapper_is_exported(self):
        assert hasattr(apl, "APLGraphWrapper")
        assert "APLGraphWrapper" in apl.__all__

    def test_instrument_context_manager_is_exported(self):
        assert hasattr(apl, "instrument")
        assert "instrument" in apl.__all__

    def test_wire_serializers_are_not_public(self):
        # Wire plumbing must stay internal (they were deleted; guard against
        # them creeping back into the public surface).
        assert "EventSerializer" not in apl.__all__
        assert "VerdictSerializer" not in apl.__all__


# =============================================================================
# PolicyLayer.fail_mode public property
# =============================================================================


class TestFailModeProperty:
    def test_default_is_closed(self):
        assert PolicyLayer().fail_mode is FailMode.CLOSED

    def test_reflects_configured_mode(self):
        layer = PolicyLayer(CompositionConfig(fail_mode=FailMode.OPEN))
        assert layer.fail_mode is FailMode.OPEN

    def test_evaluator_reads_public_property_not_private_composition(self):
        # The instrumentation evaluator now derives fail-mode from the public
        # property; a layer-like object exposing only `fail_mode` must work.
        from apl.instrumentation.evaluation.policy_evaluator import PolicyEvaluator

        class _State:
            policy_layer = PolicyLayer(CompositionConfig(fail_mode=FailMode.OPEN))

        assert PolicyEvaluator(_State())._fail_mode is FailMode.OPEN


# =============================================================================
# Verdict factory Optional[...] annotations  (§5.1)
# =============================================================================


class TestVerdictOptionalAnnotations:
    # With `from __future__ import annotations`, annotations are the source
    # strings; previously these read "str"/"int"/"dict" with a None default
    # (implicit-optional), which mypy's no_implicit_optional rejects.
    @pytest.mark.parametrize(
        "factory, param, expected",
        [
            (Verdict.allow, "reasoning", "Optional[str]"),
            (Verdict.modify, "reasoning", "Optional[str]"),
            (Verdict.modify, "path", "Optional[str]"),
            (Verdict.escalate, "prompt", "Optional[str]"),
            (Verdict.escalate, "timeout_ms", "Optional[int]"),
            (Verdict.escalate, "options", "Optional[list[str]]"),
            (Verdict.observe, "trace", "Optional[dict]"),
        ],
    )
    def test_factory_param_is_optional(self, factory, param, expected):
        assert factory.__annotations__[param] == expected

    def test_factories_accept_omitted_optionals(self):
        # Behavioural sanity: the factories still work with the optionals omitted.
        assert Verdict.allow().reasoning is None
        assert Verdict.observe().trace is None


# =============================================================================
# Version / protocol single-sourcing
# =============================================================================


class TestVersionSingleSource:
    def test_policy_server_default_version_tracks_package_version(self):
        assert PolicyServer("svc").version == apl.__version__

    def test_policy_server_has_no_hardcoded_version_literal(self):
        # Previously the default was the literal "0.3.0"; it must now reference
        # __version__ so it cannot drift from the package version.
        src = inspect.getsource(__import__("apl.server.policy_server", fromlist=["x"]))
        assert '"0.3.0"' not in src

    def test_info_command_uses_protocol_constant(self):
        # The CLI "Protocol" row must read PROTOCOL_VERSION, not a literal.
        info_mod = __import__("apl.cli.commands.info_command", fromlist=["x"])
        assert getattr(info_mod, "PROTOCOL_VERSION", None) == PROTOCOL_VERSION


# =============================================================================
# Logging: no stdout, escaped markup, one decision-style map, safe tracebacks
# =============================================================================


class TestInstrumentationIsQuiet:
    def test_auto_instrument_prints_nothing_to_stdout(self, capsys):
        from apl import auto_instrument, uninstrument

        state = auto_instrument(
            ["stdio://./policies.py"],
            enabled_providers=["__no_such_provider__"],
        )
        uninstrument(state)

        assert capsys.readouterr().out == ""

    def test_instrument_context_manager_instruments_and_restores(self, capsys):
        from apl.instrumentation.state import InstrumentationState

        with apl.instrument(
            ["stdio://./policies.py"],
            enabled_providers=["__no_such_provider__"],
        ) as state:
            assert isinstance(state, InstrumentationState)

        assert capsys.readouterr().out == ""

    def test_instrument_restores_even_on_exception(self):
        with pytest.raises(ValueError):
            with apl.instrument(
                ["stdio://./policies.py"],
                enabled_providers=["__no_such_provider__"],
            ):
                raise ValueError("boom")


class TestLoggingHardening:
    def test_decision_styles_is_single_sourced(self):
        from apl.logging import _DECISION_STYLES
        from apl.types import Decision

        assert set(_DECISION_STYLES) == set(Decision)

    def test_tracebacks_show_locals_defaults_off(self):
        # Locals routinely hold prompts/keys/PII for a security product.
        from apl.logging import APLRichHandler

        assert APLRichHandler().tracebacks_show_locals is False

    def test_policy_evaluated_escapes_remote_reasoning(self, caplog):
        # verdict.reasoning can arrive from a remote policy server and is rendered
        # as Rich markup → it must be escaped (markup/log injection).
        from apl.logging import APLLogger

        logger = APLLogger("wp8-escape")
        with caplog.at_level(logging.DEBUG, logger="apl.wp8-escape"):
            logger.policy_evaluated(
                "pii-filter",
                Verdict.deny(reasoning="[red]INJECTED[/red]"),
            )

        messages = [r.getMessage() for r in caplog.records]
        assert any("\\[red]" in m for m in messages), messages

    def test_composition_result_uses_shared_decision_styles(self, caplog):
        from apl.logging import APLLogger
        from apl.types import Decision

        logger = APLLogger("wp8-compose")
        with caplog.at_level(logging.INFO, logger="apl.wp8-compose"):
            logger.composition_result(3, Decision.DENY, 1.2)

        messages = [r.getMessage() for r in caplog.records]
        assert any("[policy.deny]DENY[/policy.deny]" in m for m in messages), messages
