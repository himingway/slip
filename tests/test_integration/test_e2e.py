import pytest
from pathlib import Path
from slip.cli._pipeline import run_build, run_check


FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestFixtureFiles:
    def test_simple(self):
        source = FIXTURES / "simple.slip"
        result = run_check(source, [])
        assert result is None  # no error

    def test_seq_block(self):
        source = FIXTURES / "seq_block.slip"
        result = run_check(source, [])
        assert result is None

    def test_implicit_ports(self):
        source = FIXTURES / "implicit_ports.slip"
        result = run_check(source, [])
        assert result is None

    def test_params(self):
        source = FIXTURES / "params.slip"
        result = run_check(source, [])
        assert result is None


class TestBuildOutput:
    def test_simple_build(self, tmp_path):
        source = FIXTURES / "simple.slip"
        result = run_build(source, tmp_path, [])
        assert "simple" in result
        assert (tmp_path / "simple.sv").exists()

        sv = (tmp_path / "simple.sv").read_text()
        assert "module simple" in sv
        assert "endmodule" in sv
        assert "a & b" in sv

    def test_seq_build(self, tmp_path):
        source = FIXTURES / "seq_block.slip"
        result = run_build(source, tmp_path, [])
        sv = result["counter"]
        assert "always_ff" in sv
        assert "posedge clk" in sv
        assert "negedge rst_n" in sv
        assert "<=" in sv

    def test_implicit_ports_build(self, tmp_path):
        source = FIXTURES / "implicit_ports.slip"
        result = run_build(source, tmp_path, [])
        sv = result["implicit"]
        assert "module implicit" in sv

    def test_params_build(self, tmp_path):
        source = FIXTURES / "params.slip"
        result = run_build(source, tmp_path, [])
        sv = result["adder"]
        assert "parameter W = 8" in sv
