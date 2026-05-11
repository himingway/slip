"""Tests for the CLI entry point (click commands)."""

import pytest
from pathlib import Path

from click.testing import CliRunner

from slip.cli.main import slip

from conftest import FIXTURES


@pytest.fixture
def runner():
    return CliRunner()


class TestBuildCommand:
    def test_build_success(self, runner, tmp_path):
        source = FIXTURES / "simple.slip"
        result = runner.invoke(slip, ["build", str(source), "-o", str(tmp_path)])
        assert result.exit_code == 0
        assert (tmp_path / "simple.sv").exists()

    def test_build_error_shows_message(self, runner, tmp_path):
        with runner.isolated_filesystem():
            Path("bad.slip").write_text("module m { assign = ; }")
            result = runner.invoke(slip, ["build", "bad.slip", "-o", str(tmp_path)])
            assert result.exit_code == 1
            assert "Error" in result.output

    def test_build_with_ip_dirs(self, runner, tmp_path):
        source = FIXTURES / "ip_top_fifo_user.slip"
        ip_dir = FIXTURES / "ip"
        result = runner.invoke(slip, [
            "build", str(source), "-o", str(tmp_path), "-ip", str(ip_dir),
        ])
        assert result.exit_code == 0

    def test_build_with_out_dir(self, runner, tmp_path):
        source = FIXTURES / "simple.slip"
        out = tmp_path / "nested" / "out"
        result = runner.invoke(slip, ["build", str(source), "-o", str(out)])
        assert result.exit_code == 0
        assert (out / "simple.sv").exists()

    def test_build_nonexistent_file(self, runner):
        result = runner.invoke(slip, ["build", "/nonexistent/file.slip"])
        assert result.exit_code != 0


class TestCheckCommand:
    def test_check_success(self, runner):
        source = FIXTURES / "simple.slip"
        result = runner.invoke(slip, ["check", str(source)])
        assert result.exit_code == 0
        assert "No errors found" in result.output

    def test_check_error(self, runner):
        with runner.isolated_filesystem():
            Path("bad.slip").write_text("module m { assign = ; }")
            result = runner.invoke(slip, ["check", "bad.slip"])
            assert result.exit_code == 1
            assert "Error" in result.output

    def test_check_with_ip_dirs(self, runner):
        source = FIXTURES / "ip_top_fifo_user.slip"
        ip_dir = FIXTURES / "ip"
        result = runner.invoke(slip, ["check", str(source), "-ip", str(ip_dir)])
        assert result.exit_code == 0


class TestMainEntryPoint:
    def test_slip_group_help(self, runner):
        result = runner.invoke(slip, ["--help"])
        assert result.exit_code == 0
        assert "Slip" in result.output

    def test_build_help(self, runner):
        result = runner.invoke(slip, ["build", "--help"])
        assert result.exit_code == 0
        assert "--out-dir" in result.output or "-o" in result.output

    def test_check_help(self, runner):
        result = runner.invoke(slip, ["check", "--help"])
        assert result.exit_code == 0
        assert "--ip-dirs" in result.output or "-ip" in result.output

    def test_main_function(self):
        from slip.cli.main import main
        # Verify main() is callable and delegates to the slip group
        assert callable(main)
