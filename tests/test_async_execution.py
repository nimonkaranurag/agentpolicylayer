from __future__ import annotations

import asyncio

from tests.conftest import async_execution_error


class TestAsyncTestsExecute:
    async def test_coroutine_tests_are_awaited(self) -> None:
        """
        A running event loop inside the test body proves pytest-asyncio is actually
        awaiting coroutine tests rather than skipping them.
        """
        await asyncio.sleep(0)
        assert asyncio.get_running_loop().is_running()


class TestAsyncExecutionGuardDecision:
    """
    Unit-tests for the pure decision behind the collection-time guard.
    """

    def test_no_error_when_plugin_active(self) -> None:
        assert (
            async_execution_error(
                asyncio_plugin_active=True,
                async_node_ids=["tests/test_x.py::test_async"],
            )
            is None
        )

    def test_no_error_when_no_async_tests(self) -> None:
        assert (
            async_execution_error(
                asyncio_plugin_active=False,
                async_node_ids=[],
            )
            is None
        )

    def test_error_when_async_collected_without_plugin(self) -> None:
        message = async_execution_error(
            asyncio_plugin_active=False,
            async_node_ids=["tests/test_server.py::test_async_handler"],
        )
        assert message is not None
        assert "pytest" in message and "asyncio" in message
        assert "test_async_handler" in message

    def test_error_reports_count_and_truncates(self) -> None:
        node_ids = [f"tests/test_x.py::test_{i}" for i in range(5)]
        message = async_execution_error(
            asyncio_plugin_active=False,
            async_node_ids=node_ids,
        )
        assert message is not None
        assert message.startswith("5 async test(s)")
        assert message.endswith("...")  # only the first few are listed


class TestAsyncExecutionGuardWiring:
    """
    End-to-end tests of the ``pytest_collection_modifyitems`` hook via the ``pytester``
    fixture: the real hook must abort a session whose async tests cannot run, and stay
    out of the way when they can.
    """

    _SANDBOX_CONFTEST = (
        "from tests.conftest import pytest_collection_modifyitems  # noqa: F401\n"
    )
    _ASYNC_TEST = "async def test_async_noop():\n    assert True\n"

    def test_hook_aborts_when_asyncio_plugin_disabled(self, pytester) -> None:
        pytester.makeconftest(self._SANDBOX_CONFTEST)
        pytester.makepyfile(self._ASYNC_TEST)

        result = pytester.runpytest("-p", "no:asyncio")

        assert result.ret != 0  # session aborted, not a silent pass
        result.stderr.fnmatch_lines(["*async test*not active*"])

    def test_hook_allows_async_when_plugin_active(self, pytester) -> None:
        pytester.makeconftest(self._SANDBOX_CONFTEST)
        pytester.makepyfile(self._ASYNC_TEST)

        result = pytester.runpytest(
            "-o",
            "asyncio_mode=auto",
            "-o",
            "asyncio_default_fixture_loop_scope=function",
        )

        result.assert_outcomes(passed=1)
