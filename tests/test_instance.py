"""Tests for instance statements: named, same-name, and regex port connections."""

import pytest
from pathlib import Path

from slip.lexer import Lexer, TokenType
from slip.parser import Parser
from slip.ast.instance import InstanceStmt, Connection
from slip.semantic import SemanticAnalyzer
from slip.ir import HDLModule, HDLInstance, HDLPort, HDLSignal, HDLType
from slip.codegen import CodeGenerator
from slip.errors.semantic import SlipSemanticError

from conftest import FIXTURES, compile_source, parse_source as parse_modules

# Slip source strings with regex backreferences use raw strings to preserve \1
_REGEX_CHILD = r'module child (clk, data_in, data_out) { logic clk; logic [7:0] data_in; logic [7:0] data_out; assign data_out = data_in; }'
_REGEX_PARENT = r'module parent (clk, fifo_in, fifo_out) { logic clk; logic [7:0] fifo_in; logic [7:0] fifo_out; child u1 { .clk, "data_(.*)" => "fifo_\1" }; }'


# ────────────────────────────────────────────────────────────────
# Parser: connection forms
# ────────────────────────────────────────────────────────────────

class TestConnectionParsing:
    def test_named_connection(self):
        mod = parse_modules(
            "module m (clk) { Other inst1 { .clk(clk) }; }"
        )[0]
        inst = mod.body[0]
        assert isinstance(inst, InstanceStmt)
        assert inst.connections[0].port == "clk"
        assert inst.connections[0].signal is not None

    def test_same_name_connection(self):
        mod = parse_modules(
            "module m (clk) { Other inst1 { .clk }; }"
        )[0]
        inst = mod.body[0]
        assert isinstance(inst, InstanceStmt)
        assert inst.connections[0].port == "clk"
        assert inst.connections[0].signal is None

    def test_regex_connection(self):
        source = r'module m (clk) { Other inst1 { "data_(.*)" => "fifo_\1" }; }'
        mod = parse_modules(source)[0]
        inst = mod.body[0]
        assert isinstance(inst, InstanceStmt)
        assert inst.connections[0].port is None
        assert inst.connections[0].port_regex == "data_(.*)"
        assert inst.connections[0].signal_regex == r"fifo_\1"

    def test_mixed_connections(self):
        source = r'module m (clk, din) { Other inst1 { .clk, .din(din), "data_out(.*)" => "fifo_\1" }; }'
        mod = parse_modules(source)[0]
        inst = mod.body[0]
        assert isinstance(inst, InstanceStmt)
        assert len(inst.connections) == 3
        assert inst.connections[0].port == "clk" and inst.connections[0].signal is None
        assert inst.connections[1].port == "din" and inst.connections[1].signal is not None
        assert inst.connections[2].port_regex is not None


# ────────────────────────────────────────────────────────────────
# IR: regex_rules captured
# ────────────────────────────────────────────────────────────────

class TestIRCapture:
    def test_named_only_no_regex(self):
        modules = parse_modules(
            "module m (clk) { Other inst1 { .clk(clk) }; }"
        )
        ir = SemanticAnalyzer().analyze(modules)
        inst = ir[0].instances[0]
        assert len(inst.regex_rules) == 0
        assert inst.port_map == (("clk", "clk"),)

    def test_same_name_in_port_map(self):
        modules = parse_modules(
            "module m (clk) { Other inst1 { .clk }; }"
        )
        ir = SemanticAnalyzer().analyze(modules)
        inst = ir[0].instances[0]
        assert inst.port_map == (("clk", "clk"),)

    def test_regex_captured(self):
        source = (
            r'module other_mod (clk, data_in) { logic clk; logic [7:0] data_in; assign data_in = 0; }'
            r' module m (clk) { other_mod inst1 { .clk, "data_(.*)" => "fifo_\1" }; }'
        )
        modules = parse_modules(source)
        ir = SemanticAnalyzer().analyze(modules)
        m_mod = [mod for mod in ir if mod.name == "m"][0]
        inst = m_mod.instances[0]
        assert len(inst.regex_rules) == 0  # resolved
        port_dict = dict(inst.port_map)
        assert port_dict["clk"] == "clk"
        assert port_dict["data_in"] == "fifo_in"


# ────────────────────────────────────────────────────────────────
# Instance resolution
# ────────────────────────────────────────────────────────────────

class TestInstanceResolve:
    def test_intra_design_regex(self):
        source = _REGEX_CHILD + " " + _REGEX_PARENT
        modules = parse_modules(source)
        ir = SemanticAnalyzer().analyze(modules)
        parent = [m for m in ir if m.name == "parent"][0]
        inst = parent.instances[0]
        port_dict = dict(inst.port_map)
        assert port_dict["clk"] == "clk"
        assert port_dict["data_in"] == "fifo_in"
        assert port_dict["data_out"] == "fifo_out"
        assert len(inst.regex_rules) == 0  # resolved

    def test_implicit_signal_creation(self):
        child = r'module child (clk, data_in) { logic clk; logic [7:0] data_in; assign data_in = 0; }'
        parent = r'module parent (clk) { logic clk; child u1 { .clk, "data_(.*)" => "auto_\1" }; }'
        modules = parse_modules(child + " " + parent)
        ir = SemanticAnalyzer().analyze(modules)
        parent_mod = [m for m in ir if m.name == "parent"][0]
        signal_names = [s.name for s in parent_mod.signals]
        assert "auto_in" in signal_names

    def test_unconnected_input_error(self):
        child = r'module child (clk, req_in) { logic clk; logic req_in; }'
        parent = r'module parent (clk) { logic clk; child u1 { .clk, "nonmatching_(.*)" => "x_\1" }; }'
        with pytest.raises(SlipSemanticError, match="unconnected input port"):
            modules = parse_modules(child + " " + parent)
            SemanticAnalyzer().analyze(modules)

    def test_named_takes_priority(self):
        child = r'module child (clk, data_in) { logic clk; logic [7:0] data_in; assign data_in = 0; }'
        parent = r'module parent (clk, my_signal) { logic clk; logic [7:0] my_signal; child u1 { .clk, .data_in(my_signal), "data_(.*)" => "other_\1" }; }'
        modules = parse_modules(child + " " + parent)
        ir = SemanticAnalyzer().analyze(modules)
        parent_mod = [m for m in ir if m.name == "parent"][0]
        inst = parent_mod.instances[0]
        port_dict = dict(inst.port_map)
        assert port_dict["data_in"] == "my_signal"

    def test_no_regex_passthrough(self):
        child = "module child (clk) { logic clk; assign clk = 0; }"
        parent = "module parent (clk) { logic clk; child u1 { .clk }; }"
        modules = parse_modules(child + " " + parent)
        ir = SemanticAnalyzer().analyze(modules)
        parent_mod = [m for m in ir if m.name == "parent"][0]
        inst = parent_mod.instances[0]
        assert len(inst.regex_rules) == 0
        assert inst.port_map == (("clk", "clk"),)


# ────────────────────────────────────────────────────────────────
# Codegen: SV output
# ────────────────────────────────────────────────────────────────

class TestInstanceCodegen:
    def test_named_connection_sv(self):
        sv = compile_source(
            "module m (clk) { Other inst1 { .clk(clk) }; }"
        )
        text = sv["m"]
        assert "Other" in text
        assert "inst1" in text
        assert ".clk(clk)" in text

    def test_same_name_sv(self):
        sv = compile_source(
            "module m (clk) { Other inst1 { .clk }; }"
        )
        assert ".clk(clk)" in sv["m"]

    def test_with_params_sv(self):
        sv = compile_source(
            "module m (clk) { Other #(.W(8)) inst1 { .clk(clk) }; }"
        )
        assert ".W(8)" in sv["m"]

    def test_full_regex_sv(self):
        source = _REGEX_CHILD + " " + _REGEX_PARENT
        sv = compile_source(source)
        parent_sv = sv["parent"]
        assert ".clk(clk)" in parent_sv
        assert ".data_in(fifo_in)" in parent_sv
        assert ".data_out(fifo_out)" in parent_sv


# ────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────

class TestInstanceFixtures:
    def test_instance_regex_fixture_compiles(self):
        sv = compile_source((FIXTURES / "instance_regex.slip").read_text())
        assert "top" in sv
        assert "submod" in sv

    def test_instance_regex_fixture_connections(self):
        sv = compile_source((FIXTURES / "instance_regex.slip").read_text())["top"]
        assert ".clk(clk)" in sv
        assert ".rst_n(rst_n)" in sv
        assert ".data_in(submod_in)" in sv
        assert ".data_out(submod_out)" in sv


# ────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────

class TestInstanceCLI:
    def test_build_instance_regex(self, tmp_path):
        from slip.cli._pipeline import run_build
        result = run_build(FIXTURES / "instance_regex.slip", tmp_path, [])
        assert (tmp_path / "top.sv").exists()
        assert (tmp_path / "submod.sv").exists()

    def test_check_instance_regex(self):
        from slip.cli._pipeline import run_check
        run_check(FIXTURES / "instance_regex.slip", [])
