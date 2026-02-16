from __future__ import annotations


class TestCoreImports:

    def test_top_level_package(self):
        import apl

        assert hasattr(apl, "__version__")

    def test_public_api_exports(self):
        from apl import (
            APLLogger,
            CompositionConfig,
            CompositionMode,
            ContextRequirement,
            Decision,
            Escalation,
            EventPayload,
            EventSerializer,
            EventType,
            FunctionCall,
            Message,
            Modification,
            PolicyClient,
            PolicyDefinition,
            PolicyDenied,
            PolicyEscalation,
            PolicyEvent,
            PolicyLayer,
            PolicyManifest,
            PolicyServer,
            SessionMetadata,
            ToolCall,
            Verdict,
            VerdictComposer,
            VerdictSerializer,
            auto_instrument,
            get_logger,
            load_yaml_policy,
            setup_logging,
            uninstrument,
            validate_yaml_policy,
        )


class TestLayerImports:

    def test_layer_package(self):
        from apl.layer import (
            PolicyClient,
            PolicyDenied,
            PolicyEscalation,
            PolicyLayer,
        )

    def test_layer_submodules(self):
        from apl.layer.event_builder import (
            PolicyEventBuilder,
        )
        from apl.layer.exceptions import (
            PolicyDenied,
            PolicyEscalation,
        )
        from apl.layer.policy_client import (
            PolicyClient,
        )
        from apl.layer.policy_layer import PolicyLayer

    def test_transport_imports(self):
        from apl.layer.client_transports import (
            BaseClientTransport,
            resolve_client_transport_for_uri,
        )
        from apl.layer.client_transports.http_client_transport import (
            HttpClientTransport,
        )
        from apl.layer.client_transports.stdio_client_transport import (
            StdioClientTransport,
        )


class TestDeclarativeEngineImports:

    def test_declarative_engine_package(self):
        from apl.declarative_engine import (
            load_yaml_policy,
            validate_yaml_policy,
        )

    def test_declarative_engine_submodules(self):
        from apl.declarative_engine.condition_evaluator import (
            ConditionEvaluator,
        )
        from apl.declarative_engine.object_traversal import (
            get_nested_value_by_dot_path,
        )
        from apl.declarative_engine.rule_evaluator import (
            RuleEvaluator,
        )
        from apl.declarative_engine.schema import (
            YAMLManifest,
            YAMLPolicyDefinition,
            YAMLRule,
        )
        from apl.declarative_engine.template_renderer import (
            TemplateRenderer,
        )
        from apl.declarative_engine.yaml_policy_loader import (
            YamlPolicyLoader,
        )
        from apl.declarative_engine.yaml_policy_validator import (
            YamlPolicyValidator,
        )


class TestServerImports:

    def test_server_package(self):
        from apl.server import PolicyServer

    def test_server_submodules(self):
        from apl.server.handler_invoker import (
            invoke_policy_handler,
        )
        from apl.server.manifest_generator import (
            generate_manifest_from_server,
        )
        from apl.server.policy_decorator import (
            create_policy_decorator,
        )
        from apl.server.policy_registry import (
            PolicyRegistry,
        )
        from apl.server.policy_server import (
            PolicyServer,
        )
        from apl.server.registered_policy import (
            RegisteredPolicy,
        )


class TestCompositionImports:

    def test_composition_package(self):
        from apl.composition import VerdictComposer

    def test_strategies(self):
        from apl.composition.strategies import (
            STRATEGY_REGISTRY,
            AllowOverridesStrategy,
            BaseCompositionStrategy,
            CompositionStrategy,
            DenyOverridesStrategy,
            FirstApplicableStrategy,
            UnanimousStrategy,
            WeightedStrategy,
            get_strategy,
        )


class TestSerializationImports:

    def test_serialization_package(self):
        from apl.serialization import (
            EventSerializer,
            ManifestSerializer,
            VerdictSerializer,
        )

    def test_serialization_submodules(self):
        from apl.serialization.event_serializer import (
            EventSerializer,
        )
        from apl.serialization.manifest_serializer import (
            ManifestSerializer,
        )
        from apl.serialization.message_serializer import (
            MessageSerializer,
        )
        from apl.serialization.metadata_serializer import (
            MetadataSerializer,
        )
        from apl.serialization.payload_serializer import (
            PayloadSerializer,
        )
        from apl.serialization.verdict_serializer import (
            VerdictSerializer,
        )


class TestInstrumentationImports:

    def test_instrumentation_package(self):
        from apl.instrumentation import (
            auto_instrument,
            uninstrument,
        )

    def test_events(self):
        from apl.instrumentation.events import (
            EVENT_REGISTRY,
            get_event,
        )

    def test_execution(self):
        from apl.instrumentation.execution import (
            AsyncLifecycleExecutor,
            BaseLifecycleExecutor,
            StreamingLifecycleExecutor,
            SyncLifecycleExecutor,
        )

    def test_messages(self):
        from apl.instrumentation.messages import (
            get_message_adapter,
        )

    def test_providers(self):
        from apl.instrumentation.providers import (
            PROVIDER_REGISTRY,
            AnthropicProvider,
            BaseProvider,
            LangChainProvider,
            LiteLLMProvider,
            OpenAIProvider,
            WatsonXProvider,
        )

    def test_state(self):
        from apl.instrumentation.state import (
            InstrumentationState,
        )


class TestAdapterImports:

    def test_adapters_package(self):
        from apl.adapters import BaseFrameworkAdapter

    def test_langgraph_adapter(self):
        from apl.adapters.langgraph import (
            APLGraphWrapper,
            create_apl_graph,
        )


class TestCLIImports:

    def test_cli_package(self):
        from apl.cli import cli

    def test_cli_commands(self):
        from apl.cli.commands import (
            info_command,
            init_command,
            serve_command,
            test_command,
        )


class TestTransportImports:

    def test_transports_package(self):
        from apl.transports import create_transport

    def test_http_transport(self):
        from apl.transports.http import HTTPTransport

    def test_stdio_transport(self):
        from apl.transports.stdio import StdioTransport


class TestMetricsImports:

    def test_metrics(self):
        from apl.metrics.prometheus_exporter import (
            export_metrics_to_prometheus,
        )
        from apl.metrics.server_metrics import (
            ServerMetrics,
        )
