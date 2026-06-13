from __future__ import annotations

import importlib
import pkgutil
import traceback

import apl


def _all_apl_module_names() -> list[str]:
    return sorted(
        info.name for info in pkgutil.walk_packages(apl.__path__, prefix="apl.")
    )


class TestPublicApi:
    def test_top_level_package(self) -> None:
        assert isinstance(apl.__version__, str)
        assert apl.__version__

    def test_all_advertised_names_resolve(self) -> None:
        """
        Every name in ``apl.__all__`` must actually be importable from the package — a
        stale ``__all__`` entry is a broken public API.
        """
        missing = [name for name in apl.__all__ if not hasattr(apl, name)]
        assert not missing, f"apl.__all__ lists names that don't resolve: {missing}"


class TestEveryModuleImports:
    def test_all_submodules_import_cleanly(self) -> None:
        """
        Import every module under ``apl`` and fail if any raises.

        This is the net that turns a broken import in an otherwise-untested module from
        a green build into a red one.
        """
        failures: dict[str, str] = {}

        def _record(name: str) -> None:
            failures[name] = traceback.format_exc()

        # walk_packages imports each package to read its __path__; capture
        # package-level failures via onerror and module-level ones below.
        for info in pkgutil.walk_packages(apl.__path__, prefix="apl.", onerror=_record):
            try:
                importlib.import_module(info.name)
            except Exception:
                failures[info.name] = traceback.format_exc()

        assert not failures, "modules failed to import:\n" + "\n".join(
            f"--- {name} ---\n{tb}" for name, tb in failures.items()
        )

    def test_tree_is_non_trivial(self) -> None:
        # Guard against the walk silently finding nothing (e.g. a bad __path__).
        assert len(_all_apl_module_names()) > 50


class TestFlagshipSmoke:
    """
    Construct the flagship public classes that were previously import-only.
    """

    def test_policy_layer_constructs(self) -> None:
        layer = apl.PolicyLayer()
        assert callable(layer.add_server)
        assert callable(layer.evaluate)
        assert callable(layer.wrap)

    def test_policy_server_constructs(self) -> None:
        server = apl.PolicyServer("import-smoke")
        assert callable(server.policy)
        assert callable(server.run)

    def test_create_transport_resolves_both_schemes(self) -> None:
        # The http transport is lazy-loaded (its aiohttp dependency is an extra),
        # but both schemes still resolve through create_transport, and
        # HTTPTransport remains importable from the package via PEP 562.
        from apl.transports import (
            HTTPTransport,
            StdioTransport,
            create_transport,
        )

        server = apl.PolicyServer("import-smoke")
        assert isinstance(create_transport("stdio", server), StdioTransport)
        assert isinstance(create_transport("http", server), HTTPTransport)

    def test_provider_classes_import(self) -> None:
        from apl.instrumentation.providers import (
            BaseProvider,
            OpenAIProvider,
        )

        assert issubclass(OpenAIProvider, BaseProvider)

    def test_cli_entrypoint_is_callable(self) -> None:
        from apl.cli import main

        assert callable(main)

    def test_adapters_package_constructs(self) -> None:
        from apl.adapters import (
            APLGraphWrapper,
            BaseFrameworkAdapter,
            create_apl_graph,
        )

        assert BaseFrameworkAdapter is not None
        assert callable(create_apl_graph)
        # Constructs without langgraph installed (the adapter imports lazily).
        assert APLGraphWrapper() is not None
