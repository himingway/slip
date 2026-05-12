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


# ────────────────────────────────────────────────────────────────
# Width inference annotation
# ────────────────────────────────────────────────────────────────

class TestWidthInference:
    def test_explicit_connection_inherits_width(self):
        """Port with no explicit width gets port width + annotation comment."""
        child = r'module child (clk, data) { logic clk; logic [15:0] data; }'
        parent = r'module parent (clk, my_data) { logic clk; logic my_data; child u1 { .clk, .data(my_data) }; }'
        sv = compile_source(child + " " + parent)
        text = sv["parent"]
        assert "input logic [15:0] my_data" in text
        assert "// width from child.data" in text

    def test_explicit_connection_existing_width_preserved(self):
        """Port with declared width keeps it, no annotation."""
        child = r'module child (clk, data) { logic clk; logic [7:0] data; }'
        parent = r'module parent (clk, my_data) { logic clk; logic [31:0] my_data; child u1 { .clk, .data(my_data) }; }'
        sv = compile_source(child + " " + parent)
        text = sv["parent"]
        assert "input logic [31:0] my_data" in text
        assert "width from" not in text

    def test_same_name_shorthand_inherits_width(self):
        """Same-name .port shorthand: undeclared-width port gets target width."""
        child = r'module child (clk, bus) { logic clk; logic [11:0] bus; }'
        parent = r'module parent (clk, bus) { logic clk; child u1 { .clk, .bus }; }'
        sv = compile_source(child + " " + parent)
        text = sv["parent"]
        assert "input logic [11:0] bus" in text
        assert "// width from child.bus" in text

    def test_regex_implicit_signal_has_annotation(self):
        """Regex-created implicit signal gets width + implicit annotation."""
        child = r'module child (clk, data_out) { logic clk; logic [9:0] data_out; assign data_out = 0; }'
        parent = r'module parent (clk) { logic clk; child u1 { .clk, "data_(.*)" => "bus_\1" }; }'
        sv = compile_source(child + " " + parent)
        text = sv["parent"]
        assert "logic [9:0] bus_out;" in text
        assert "implicit" in text
        assert "width from child.data_out" in text

    def test_regex_existing_signal_inherits_width(self):
        """Pre-declared port without width gets updated via regex match."""
        child = r'module child (clk, data_out) { logic clk; logic [13:0] data_out; assign data_out = 0; }'
        parent = r'module parent (clk, bus_out) { logic clk; logic bus_out; child u1 { .clk, "data_(.*)" => "bus_\1" }; }'
        sv = compile_source(child + " " + parent)
        text = sv["parent"]
        assert "input logic [13:0] bus_out" in text
        assert "// width from child.data_out" in text

    def test_mixed_connections_width_inference(self):
        """Mix of named and regex connections — all get width annotations."""
        child = r'module child (clk, a_in, b_out, c_out) { logic clk; logic [3:0] a_in; logic [5:0] b_out; logic [7:0] c_out; assign b_out = 0; assign c_out = 0; }'
        parent = r'module parent (clk, sig_a, sig_b) { logic clk; logic sig_a; logic sig_b; child u1 { .clk, .a_in(sig_a), .b_out(sig_b), "c_(.*)" => "my_\1" }; }'
        sv = compile_source(child + " " + parent)
        text = sv["parent"]
        assert "input logic [3:0] sig_a" in text
        assert "// width from child.a_in" in text
        assert "input logic [5:0] sig_b" in text
        assert "// width from child.b_out" in text
        assert "logic [7:0] my_out;" in text
        assert "implicit" in text
        assert "width from child.c_out" in text

    def test_external_module_no_width_annotation(self):
        """External (unresolvable) module — no annotation, width stays 1-bit."""
        sv = compile_source(
            "module m (clk, sig) { logic clk; logic sig; ExternalIP u1 { .clk, .port(sig) }; }"
        )
        text = sv["m"]
        assert "input logic sig" in text
        assert "width from" not in text
