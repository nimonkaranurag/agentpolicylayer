from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from apl.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _write_policy(
    directory: Path,
    filename: str = "policy.py",
    *,
    server_name: str = "test-server",
    policy_name: str = "test-policy",
    decision: str = "allow",
) -> Path:
    """
    Write a minimal valid Python policy file and return its path.
    """
    path = directory / filename
    path.write_text(
        textwrap.dedent(
            f"""
            from apl.server import PolicyServer
            from apl.types import Verdict

            server = PolicyServer(name="{server_name}")

            @server.policy(name="{policy_name}", events=["output.pre_send"])
            async def handler(event):
                return Verdict.{decision}(reasoning="from {policy_name}")
            """
        )
    )
    return path


# ---------------------------------------------------------------------------
# Top-level group / help
# ---------------------------------------------------------------------------


class TestCliGroup:
    def test_help_lists_commands(self, runner: CliRunner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        for command in ("serve", "test", "validate", "init", "info"):
            assert command in result.output

    def test_info_runs(self, runner: CliRunner):
        result = runner.invoke(cli, ["info"])
        assert result.exit_code == 0
        assert "Agent Policy Layer" in result.output

    @pytest.mark.parametrize("command", ["serve", "test", "validate", "init", "info"])
    def test_each_command_help(self, runner: CliRunner, command: str):
        result = runner.invoke(cli, [command, "--help"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# `serve`
# ---------------------------------------------------------------------------


class TestServe:
    def test_http_zero_port_binds_http_not_stdio(
        self, runner: CliRunner, monkeypatch, tmp_path: Path
    ):
        """
        ``--http 0`` is a real request (OS picks an ephemeral port); the old
        ``if http_port:`` guard treated 0 as "no HTTP" and fell through to stdio.
        """
        from apl.cli.commands import serve_command

        routed: dict[str, object] = {}
        monkeypatch.setattr(
            serve_command,
            "_serve_over_http",
            lambda *a, **k: routed.update(http=True, port=k.get("port")),
        )
        monkeypatch.setattr(
            serve_command,
            "_serve_over_stdio",
            lambda *a, **k: routed.update(stdio=True),
        )

        policy = _write_policy(tmp_path)
        result = runner.invoke(cli, ["serve", str(policy), "--http", "0", "-q"])

        assert result.exit_code == 0
        assert routed.get("http") is True
        assert routed.get("port") == 0
        assert "stdio" not in routed

    def test_default_serves_stdio(self, runner: CliRunner, monkeypatch, tmp_path: Path):
        from apl.cli.commands import serve_command

        routed: dict[str, object] = {}
        monkeypatch.setattr(
            serve_command, "_serve_over_http", lambda *a, **k: routed.update(http=True)
        )
        monkeypatch.setattr(
            serve_command,
            "_serve_over_stdio",
            lambda *a, **k: routed.update(stdio=True),
        )

        policy = _write_policy(tmp_path)
        result = runner.invoke(cli, ["serve", str(policy), "-q"])

        assert result.exit_code == 0
        assert routed.get("stdio") is True
        assert "http" not in routed

    def test_stdio_serve_keeps_stdout_clean(
        self, runner: CliRunner, monkeypatch, tmp_path: Path
    ):
        """
        The stdio transport speaks JSON on stdout, so human chrome (banner, policy
        tree, status lines) must go to stderr — stdout must stay empty.
        """
        from apl.cli.commands import serve_command

        monkeypatch.setattr(serve_command, "_serve_over_stdio", lambda *a, **k: None)

        policy = _write_policy(tmp_path)
        result = runner.invoke(cli, ["serve", str(policy)])  # not quiet

        assert result.exit_code == 0
        assert result.stdout == ""
        assert "test-server" in result.stderr  # the policy tree went to stderr

    def test_stdio_flag_removed(self, runner: CliRunner, tmp_path: Path):
        policy = _write_policy(tmp_path)
        result = runner.invoke(cli, ["serve", str(policy), "--stdio"])
        assert result.exit_code == 2
        assert "no such option" in result.output.lower()

    def test_http_flags_passed_through(
        self, runner: CliRunner, monkeypatch, tmp_path: Path
    ):
        from apl.cli.commands import serve_command

        captured: dict[str, object] = {}

        class _FakeServer:
            def run(self, **kwargs):
                captured.update(kwargs)

        monkeypatch.setattr(
            serve_command, "load_policy_server", lambda *a, **k: _FakeServer()
        )

        policy = _write_policy(tmp_path)
        result = runner.invoke(
            cli,
            [
                "serve",
                str(policy),
                "--http",
                "8123",
                "--host",
                "0.0.0.0",
                "--auth-token",
                "secret",
                "--cors-origin",
                "https://a.example",
                "--cors-origin",
                "https://b.example",
                "--max-body",
                "2048",
                "-q",
            ],
        )

        assert result.exit_code == 0
        assert captured["transport"] == "http"
        assert captured["host"] == "0.0.0.0"
        assert captured["port"] == 8123
        assert captured["auth_token"] == "secret"
        assert captured["cors_origins"] == ["https://a.example", "https://b.example"]
        assert captured["max_request_bytes"] == 2048

    def test_http_host_defaults_to_loopback(
        self, runner: CliRunner, monkeypatch, tmp_path: Path
    ):
        from apl.cli.commands import serve_command

        captured: dict[str, object] = {}

        class _FakeServer:
            def run(self, **kwargs):
                captured.update(kwargs)

        monkeypatch.setattr(
            serve_command, "load_policy_server", lambda *a, **k: _FakeServer()
        )

        policy = _write_policy(tmp_path)
        result = runner.invoke(cli, ["serve", str(policy), "--http", "8124", "-q"])

        assert result.exit_code == 0
        assert captured["host"] == "127.0.0.1"

    def test_load_failure_exits_nonzero(self, runner: CliRunner, tmp_path: Path):
        empty = tmp_path / "empty.py"
        empty.write_text("x = 1\n")  # no PolicyServer
        result = runner.invoke(cli, ["serve", str(empty), "-q"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# `test`
# ---------------------------------------------------------------------------


class TestTestCommand:
    def test_happy_path_renders_verdicts(self, runner: CliRunner, tmp_path: Path):
        policy = _write_policy(tmp_path, decision="deny")
        result = runner.invoke(cli, ["test", str(policy)])
        assert result.exit_code == 0
        assert "Policy Verdicts" in result.output
        assert "DENY" in result.output

    def test_bad_event_exits_cleanly(self, runner: CliRunner, tmp_path: Path):
        """
        A bogus ``--event`` is rejected by ``click.Choice`` with a usage error —
        not an unhandled ``ValueError`` traceback as before.
        """
        policy = _write_policy(tmp_path)
        result = runner.invoke(cli, ["test", str(policy), "-e", "bogus.event"])
        assert result.exit_code == 2
        assert not isinstance(result.exception, ValueError)
        assert "bogus.event" in result.output

    def test_explicit_valid_event(self, runner: CliRunner, tmp_path: Path):
        policy = _write_policy(tmp_path)
        result = runner.invoke(cli, ["test", str(policy), "-e", "tool.pre_invoke"])
        assert result.exit_code == 0

    def test_bad_payload_json_exits_cleanly(self, runner: CliRunner, tmp_path: Path):
        policy = _write_policy(tmp_path)
        result = runner.invoke(cli, ["test", str(policy), "-p", "{not valid json"])
        assert result.exit_code == 2
        assert not isinstance(result.exception, ValueError)

    def test_valid_payload_used(self, runner: CliRunner, tmp_path: Path):
        policy = _write_policy(tmp_path)
        result = runner.invoke(
            cli,
            ["test", str(policy), "-p", '{"output_text": "hello"}'],
        )
        assert result.exit_code == 0
        assert "Policy Verdicts" in result.output


# ---------------------------------------------------------------------------
# `validate`
# ---------------------------------------------------------------------------


class TestValidate:
    def test_valid_python_passes(self, runner: CliRunner, tmp_path: Path):
        policy = _write_policy(tmp_path)
        result = runner.invoke(cli, ["validate", str(policy)])
        assert result.exit_code == 0
        assert "passed" in result.output.lower()

    def test_python_without_server_fails(self, runner: CliRunner, tmp_path: Path):
        bad = tmp_path / "bad.py"
        bad.write_text("x = 1\n")
        result = runner.invoke(cli, ["validate", str(bad)])
        assert result.exit_code == 1
        assert "No PolicyServer" in result.output

    def test_invalid_yaml_operator_fails(self, runner: CliRunner, tmp_path: Path):
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text(
            textwrap.dedent(
                """
                name: bad
                policies:
                  - name: p
                    events: [output.pre_send]
                    rules:
                      - when:
                          output_text: {contians: secret}
                        then:
                          decision: deny
                """
            )
        )
        result = runner.invoke(cli, ["validate", str(bad_yaml)])
        assert result.exit_code == 1
        assert "contians" in result.output

    def test_valid_yaml_passes(self, runner: CliRunner, tmp_path: Path):
        good_yaml = tmp_path / "good.yaml"
        good_yaml.write_text(
            textwrap.dedent(
                """
                name: good
                policies:
                  - name: p
                    events: [output.pre_send]
                    rules:
                      - when:
                          output_text: {contains: secret}
                        then:
                          decision: deny
                """
            )
        )
        result = runner.invoke(cli, ["validate", str(good_yaml)])
        assert result.exit_code == 0
        assert "passed" in result.output.lower()


# ---------------------------------------------------------------------------
# `init`
# ---------------------------------------------------------------------------


class TestInit:
    def test_creates_project(self, runner: CliRunner):
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["init", "my-policy"])
            assert result.exit_code == 0
            assert Path("my-policy").is_dir()

    def test_existing_dir_fails(self, runner: CliRunner):
        with runner.isolated_filesystem():
            Path("my-policy").mkdir()
            result = runner.invoke(cli, ["init", "my-policy"])
            assert result.exit_code == 1
            assert "Failed" in result.output

    def test_bad_template_rejected(self, runner: CliRunner):
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["init", "my-policy", "--template", "nonsense"])
            assert result.exit_code == 2


# ---------------------------------------------------------------------------
# policy_source (loading + validation directly)
# ---------------------------------------------------------------------------


class TestPolicySource:
    def test_duplicate_policy_names_in_directory_refused(self, tmp_path: Path):
        from apl.cli import policy_source
        from apl.logging import get_logger

        _write_policy(tmp_path, "a.py", server_name="a", policy_name="dup")
        _write_policy(tmp_path, "b.py", server_name="b", policy_name="dup")

        server = policy_source.load_policy_server(tmp_path, get_logger("test"))
        assert server is None  # fail closed on ambiguous policy set

    def test_distinct_policy_names_in_directory_load(self, tmp_path: Path):
        from apl.cli import policy_source
        from apl.logging import get_logger

        _write_policy(tmp_path, "a.py", server_name="a", policy_name="alpha")
        _write_policy(tmp_path, "b.py", server_name="b", policy_name="beta")

        server = policy_source.load_policy_server(tmp_path, get_logger("test"))
        assert server is not None
        names = sorted(p.name for p in server.registry.all_policies())
        assert names == ["alpha", "beta"]

    def test_unique_module_name_no_shared_key(self, tmp_path: Path):
        """
        Loading a Python policy must not register it under a shared
        ``"policy_module"`` key, which let one file clobber another.
        """
        from apl.cli import policy_source
        from apl.logging import get_logger

        sys.modules.pop("policy_module", None)
        policy = _write_policy(tmp_path)
        policy_source.load_policy_server(policy, get_logger("test"))

        assert "policy_module" not in sys.modules
        assert any(name.startswith("apl_policy_") for name in sys.modules)

    def test_unsupported_suffix_returns_none(self, tmp_path: Path):
        from apl.cli import policy_source
        from apl.logging import get_logger

        weird = tmp_path / "policy.txt"
        weird.write_text("nope")
        assert policy_source.load_policy_server(weird, get_logger("test")) is None
        assert not policy_source.is_supported_path(weird)

    def test_invalid_yaml_refused_at_load(self, tmp_path: Path):
        from apl.cli import policy_source
        from apl.logging import get_logger

        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text(
            "name: bad\n"
            "policies:\n"
            "  - name: p\n"
            "    events: [output.pre_send]\n"
            "    rules:\n"
            "      - when: {output_text: {contians: x}}\n"
            "        then: {decision: deny}\n"
        )
        server = policy_source.load_policy_server(bad_yaml, get_logger("test"))
        assert server is None  # validate-on-load fails closed

    def test_within_file_duplicate_names_refused(self, tmp_path: Path):
        """
        A single file defining two policies with the same name must fail closed,
        not silently keep only the last one (the registry rejects the duplicate).
        """
        from apl.cli import policy_source
        from apl.logging import get_logger

        dup = tmp_path / "dup.py"
        dup.write_text(
            "from apl.server import PolicyServer\n"
            "from apl.types import Verdict\n"
            "server = PolicyServer(name='s')\n"
            "@server.policy(name='dup', events=['output.pre_send'])\n"
            "async def a(event):\n"
            "    return Verdict.allow()\n"
            "@server.policy(name='dup', events=['output.pre_send'])\n"
            "async def b(event):\n"
            "    return Verdict.allow()\n"
        )
        assert policy_source.load_policy_server(dup, get_logger("test")) is None


class TestWithinFileDuplicateCli:
    def test_validate_within_file_duplicate_fails(
        self, runner: CliRunner, tmp_path: Path
    ):
        dup = tmp_path / "dup.py"
        dup.write_text(
            "from apl.server import PolicyServer\n"
            "from apl.types import Verdict\n"
            "server = PolicyServer(name='s')\n"
            "@server.policy(name='dup', events=['output.pre_send'])\n"
            "async def a(event):\n"
            "    return Verdict.allow()\n"
            "@server.policy(name='dup', events=['output.pre_send'])\n"
            "async def b(event):\n"
            "    return Verdict.allow()\n"
        )
        result = runner.invoke(cli, ["validate", str(dup)])
        assert result.exit_code == 1
        assert "Duplicate policy name" in result.output
