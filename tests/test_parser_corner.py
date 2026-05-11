"""Corner case tests for the parser."""

import pytest

from slip.ast import *
from slip.ast.expressions import *
from slip.errors.syntax import SlipSyntaxError

from conftest import parse_source, parse_module


class TestModuleParsing:
    def test_module_no_ports(self):
        mod = parse_module("module m { logic x; }")
        assert mod.name == "m"
        assert len(mod.ports) == 0

    def test_module_with_params(self):
        mod = parse_module("module m #(param W = 8) (a, b) { assign b = a; }")
        assert len(mod.params) == 1
        assert mod.params[0].name == "W"

    def test_module_empty_body(self):
        mod = parse_module("module m (a) { }")
        assert mod.name == "m"


class TestSignalDeclarations:
    def test_signal_with_width(self):
        mod = parse_module("module m (a) { logic [7:0] a; }")
        assert len(mod.body) == 1
        assert isinstance(mod.body[0], SignalDecl)

    def test_signal_signed(self):
        mod = parse_module("module m (a) { signed logic [7:0] a; }")
        assert mod.body[0].is_signed is True

    def test_signal_with_array_range(self):
        mod = parse_module("module m (a) { logic [7:0] a [0:15]; }")
        assert mod.body[0].array_range is not None


class TestAssignments:
    def test_assign_with_keyword(self):
        mod = parse_module("module m (a, b) { assign b = a; }")
        assert isinstance(mod.body[0], AssignStmt)

    def test_assign_without_keyword(self):
        mod = parse_module("module m (a, b) { b = a; }")
        assert isinstance(mod.body[0], AssignStmt)

    def test_assign_nonblocking(self):
        mod = parse_module("module m (clk, d, q) { seq (clk) { q <= d; } }")
        seq = mod.body[0]
        assert isinstance(seq, SeqBlock)
        assign = seq.body.statements[0]
        assert assign.is_nonblocking is True


class TestSeqBlock:
    def test_seq_with_clock_and_reset(self):
        mod = parse_module("module m (clk, rst_n) { seq (clk, neg: rst_n) { } }")
        seq = mod.body[0]
        assert isinstance(seq, SeqBlock)
        assert seq.clock == "clk"
        assert seq.reset == ("neg", "rst_n")

    def test_seq_clock_only(self):
        mod = parse_module("module m (clk) { seq (clk) { } }")
        seq = mod.body[0]
        assert isinstance(seq, SeqBlock)
        assert seq.reset is None


class TestCombBlock:
    def test_comb_block(self):
        mod = parse_module("module m (y) { comb { assign y = 1; } }")
        assert isinstance(mod.body[0], CombBlock)


class TestIfStatement:
    def test_if_else(self):
        mod = parse_module("module m (sel, a, b, y) { if (sel) { y = a; } else { y = b; } }")
        stmt = mod.body[0]
        assert isinstance(stmt, IfStmt)
        assert stmt.else_body is not None

    def test_if_no_else(self):
        mod = parse_module("module m (en, y) { if (en) { y = 1; } }")
        stmt = mod.body[0]
        assert isinstance(stmt, IfStmt)
        assert stmt.else_body is None


class TestForStatement:
    def test_basic_for(self):
        mod = parse_module(
            "module m (y) { for (i = 0; i < 8; i = i + 1) { assign y = i; } }"
        )
        stmt = mod.body[0]
        assert isinstance(stmt, ForStmt)
        assert stmt.var == "i"


class TestInstanceStatement:
    def test_same_name_connection(self):
        mod = parse_module("module m (clk) { child u1 { .clk }; }")
        inst = mod.body[0]
        assert isinstance(inst, InstanceStmt)
        assert inst.inst_name == "u1"

    def test_named_connection(self):
        mod = parse_module("module m (clk) { child u1 { .clk(clk) }; }")
        inst = mod.body[0]
        assert inst.connections[0].port == "clk"

    def test_regex_connection(self):
        mod = parse_module('module m (clk) { child u1 { "data_(.*)" => "bus_\\1" }; }')
        inst = mod.body[0]
        assert inst.connections[0].port_regex is not None

    def test_parameterized_instance(self):
        mod = parse_module("module m (clk) { child #(.W(8)) u1 { .clk }; }")
        inst = mod.body[0]
        assert len(inst.params) == 1
        assert inst.params[0].name == "W"


class TestMetaprogramming:
    def test_gen_for(self):
        mod = parse_module(
            "module m (y) { `for (`i = 0; `i < 4; `i = `i + 1) { assign y_`i = `i; } }"
        )
        assert isinstance(mod.body[0], GenForStmt)

    def test_gen_if(self):
        mod = parse_module(
            "module m #(param MODE = 1) (y) { `if (MODE) { assign y = 1; } }"
        )
        assert isinstance(mod.body[0], GenIfStmt)


class TestLocalParam:
    def test_localparam(self):
        mod = parse_module("module m (y) { localparam K = 5; assign y = K; }")
        assert isinstance(mod.body[0], LocalParamDecl)
        assert mod.body[0].name == "K"


class TestErrorRecovery:
    def test_unexpected_token(self):
        with pytest.raises(SlipSyntaxError):
            parse_source("module m { = ; }")

    def test_missing_closing_brace(self):
        with pytest.raises(SlipSyntaxError):
            parse_source("module m { assign y = 1; ")
