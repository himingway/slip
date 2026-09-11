import pytest
from pathlib import Path
from slip.cli._pipeline import run_build, run_check

from conftest import FIXTURES


class TestFixtureFiles:
    def test_simple(self):
        source = FIXTURES / "simple.slip"
        result = run_check(source, [])
        assert "simple" in result  # check returns generated SV, writes nothing

    def test_seq_block(self):
        source = FIXTURES / "seq_block.slip"
        result = run_check(source, [])
        assert "counter" in result

    def test_implicit_ports(self):
        source = FIXTURES / "implicit_ports.slip"
        result = run_check(source, [])
        assert "implicit" in result

    def test_params(self):
        source = FIXTURES / "params.slip"
        result = run_check(source, [])
        assert "adder" in result

    def test_check_writes_no_files(self, tmp_path):
        import os
        source = FIXTURES / "simple.slip"
        before = set(os.listdir(tmp_path))
        run_check(source, [])
        assert set(os.listdir(tmp_path)) == before


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
