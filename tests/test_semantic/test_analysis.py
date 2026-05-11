import pytest
from slip.lexer import Lexer
from slip.parser import Parser
from slip.semantic import SemanticAnalyzer
from slip.semantic.symbol_collector import collect
from slip.semantic.driver_analysis import analyze, infer_port_directions
from slip.semantic.seq_correction import correct
from slip.semantic.expr_serializer import expr_to_sv
from slip.ast.expressions import BinaryExpr, IdentExpr, IntLiteralExpr, UnaryExpr
from slip.ir import HDLModule

from conftest import parse_module


class TestSymbolCollector:
    def test_explicit_ports(self):
        mod = parse_module("module m (a, b, y) { logic [7:0] a; logic [7:0] b; assign y = a + b; }")
        syms = collect(mod)
        assert "a" in syms.ports
        assert "b" in syms.ports
        assert "y" in syms.ports
        assert "a" in syms.signals

    def test_params_collected(self):
        mod = parse_module("module m #(param W = 8) (a) { assign a = 0; }")
        syms = collect(mod)
        assert "W" in syms.params

    def test_references_tracked(self):
        mod = parse_module("module m (a, b, y) { assign y = a + b; }")
        syms = collect(mod)
        assert "a" in syms.all_refs
        assert "b" in syms.all_refs
        assert "y" in syms.all_refs


class TestDriverAnalysis:
    def test_simple_drivers(self):
        mod = parse_module("module m (a, b, y) { assign y = a + b; }")
        syms = collect(mod)
        drivers = analyze(mod, syms)
        assert "y" in drivers.drivers
        assert "a" in drivers.readers
        assert "b" in drivers.readers

    def test_port_directions_explicit(self):
        mod = parse_module("module m (a, b, y) { assign y = a + b; }")
        syms = collect(mod)
        drivers = analyze(mod, syms)
        dirs = infer_port_directions(syms, drivers, explicit_ports=True)
        assert dirs["a"] == "input"
        assert dirs["b"] == "input"
        assert dirs["y"] == "output"

    def test_seq_drivers(self):
        mod = parse_module("module m (clk, count) { seq (clk) { count = count + 1; } }")
        syms = collect(mod)
        drivers = analyze(mod, syms)
        assert "count" in drivers.drivers
        assert "clk" in drivers.readers


class TestSeqCorrection:
    def test_blocking_to_nonblocking(self):
        mod = parse_module("module m (clk, count) { seq (clk) { count = 0; } }")
        corrected = correct(mod)
        seq = corrected.body[0]
        assign = seq.body.statements[0]
        assert assign.is_nonblocking is True

    def test_nested_if_correction(self):
        mod = parse_module(
            "module m (clk, rst, count) { "
            "seq (clk, neg: rst) { "
            "if (!rst) { count = 0; } else { count = count + 1; } "
            "} }"
        )
        corrected = correct(mod)
        seq = corrected.body[0]
        if_stmt = seq.body.statements[0]
        then_assign = if_stmt.then_body.statements[0]
        assert then_assign.is_nonblocking is True


class TestExprSerializer:
    def test_ident(self):
        expr = IdentExpr(None, "foo")
        assert expr_to_sv(expr) == "foo"

    def test_binary(self):
        expr = BinaryExpr(None, "+", IdentExpr(None, "a"), IdentExpr(None, "b"))
        assert expr_to_sv(expr) == "a + b"

    def test_int_literal(self):
        expr = IntLiteralExpr(None, "8'hFF")
        assert expr_to_sv(expr) == "8'hFF"

    def test_unary(self):
        expr = UnaryExpr(None, "!", IdentExpr(None, "a"))
        assert expr_to_sv(expr) == "!a"


class TestSemanticAnalyzer:
    def test_full_pipeline_simple(self):
        mod = parse_module("module m (a, b, y) { assign y = a & b; }")
        result = SemanticAnalyzer().analyze([mod])
        assert len(result) == 1
        assert isinstance(result[0], HDLModule)
        assert result[0].name == "m"

    def test_full_pipeline_seq(self):
        mod = parse_module(
            "module counter (clk, rst_n, count) { "
            "seq (clk, neg: rst_n) { "
            "if (!rst_n) { count = 0; } else { count = count + 1; } "
            "} }"
        )
        result = SemanticAnalyzer().analyze([mod])
        ir = result[0]
        assert len(ir.logic_blocks) == 1
        assert "posedge clk" in ir.logic_blocks[0].sensitivity
