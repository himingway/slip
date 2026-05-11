"""Corner case tests for semantic analysis modules."""

import pytest
from pathlib import Path

from slip.ast.base import SourceLocation
from slip.ast.expressions import BinaryExpr, IdentExpr, IntLiteralExpr
from slip.ast.statements import (
    AssignStmt, BlockStmt, CombBlock, ForStmt, IfStmt, LValue, SeqBlock,
)
from slip.semantic.symbol_collector import collect, SymbolTable
from slip.semantic.driver_analysis import analyze, infer_port_directions
from slip.semantic.seq_correction import correct, _correct_stmt
from slip.semantic.ir_builder import build
from slip.errors.semantic import SlipSemanticError

from conftest import compile_source, parse_module


# ── Symbol collector ────────────────────────────────────────────

class TestSymbolCollector:
    def test_instances_collected(self):
        src = "module m (clk) { child u1 { .clk }; }"
        mod = parse_module(src)
        syms = collect(mod)
        assert "u1" in syms.instances

    def test_declared_property(self):
        src = "module m #(param W = 8) (a, b) { logic x; assign x = a; }"
        mod = parse_module(src)
        syms = collect(mod)
        declared = syms.declared
        assert "W" in declared
        assert "a" in declared
        assert "b" in declared
        assert "x" in declared

    def test_for_stmt_refs(self):
        src = (
            "module m (y) { "
            "for (i = 0; i < 8; i = i + 1) { assign y = i; } "
            "}"
        )
        mod = parse_module(src)
        syms = collect(mod)
        assert "i" in syms.all_refs
        assert "y" in syms.all_refs

    def test_instance_connections_refs(self):
        src = "module m (clk, data) { child u1 { .clk(clk), .d(data) }; }"
        mod = parse_module(src)
        syms = collect(mod)
        assert "clk" in syms.all_refs
        assert "data" in syms.all_refs

    def test_indexed_assign_target(self):
        src = "module m (a, b) { logic [7:0] a; assign a[3] = b; }"
        mod = parse_module(src)
        syms = collect(mod)
        assert "a" in syms.all_refs
        assert "b" in syms.all_refs

    def test_localparam_collected(self):
        src = "module m (y) { localparam K = 5; assign y = K; }"
        mod = parse_module(src)
        syms = collect(mod)
        assert "K" in syms.localparams


# ── Driver analysis ─────────────────────────────────────────────

class TestDriverAnalysis:
    def test_unused_port_defaults_input(self):
        src = "module m (a, y) { assign y = 1; }"
        mod = parse_module(src)
        syms = collect(mod)
        info = analyze(mod, syms)
        directions = infer_port_directions(syms, info, explicit_ports=True)
        # 'a' is declared but never referenced -> defaults to input
        assert directions.get("a", "input") == "input"

    def test_indexed_assignment_drives_base(self):
        src = "module m (a, b) { logic [7:0] a; assign a[3] = b; }"
        mod = parse_module(src)
        syms = collect(mod)
        info = analyze(mod, syms)
        assert "a" in info.drivers

    def test_for_stmt_scanning(self):
        src = (
            "module m (y) { logic [7:0] y; "
            "for (i = 0; i < 8; i = i + 1) { assign y = i; } "
            "}"
        )
        mod = parse_module(src)
        syms = collect(mod)
        info = analyze(mod, syms)
        assert "i" in info.readers

    def test_instance_connection_reads(self):
        src = "module m (clk, data) { child u1 { .clk(clk), .d(data) }; }"
        mod = parse_module(src)
        syms = collect(mod)
        info = analyze(mod, syms)
        assert "clk" in info.readers
        assert "data" in info.readers

    def test_driven_is_output(self):
        src = "module m (a, y) { assign y = a; }"
        mod = parse_module(src)
        syms = collect(mod)
        info = analyze(mod, syms)
        directions = infer_port_directions(syms, info, explicit_ports=True)
        assert directions["y"] == "output"
        assert directions["a"] == "input"


# ── Seq correction ──────────────────────────────────────────────

class TestSeqCorrection:
    def test_seq_blocking_to_nonblocking(self):
        src = (
            "module m (clk, rst_n, d, q) { "
            "logic [7:0] d; logic [7:0] q; "
            "seq (clk, neg: rst_n) { "
            "q = d; "
            "} }"
        )
        sv = compile_source(src)
        # Inside seq, blocking = should become <=
        assert "<=" in sv["m"]

    def test_comb_block_unchanged(self):
        src = (
            "module m (a, b, y) { "
            "comb { y = a & b; } "
            "}"
        )
        sv = compile_source(src)
        # In comb block, = stays as =
        assert "y = a & b;" in sv["m"] or "assign y = a & b" in sv["m"]

    def test_nested_if_in_seq(self):
        # IfStmt nested inside a seq block
        src = (
            "module m (clk, rst_n, en, d, q) { "
            "logic [7:0] d; logic [7:0] q; "
            "seq (clk, neg: rst_n) { "
            "if (en) { q = d; } "
            "} }"
        )
        sv = compile_source(src)
        assert "<=" in sv["m"]

    def test_correct_stmt_ifstmt(self):
        # Direct test: _correct_stmt on IfStmt
        LOC = SourceLocation("test.slip", 1, 1)
        assign = AssignStmt(LOC, target=LValue(LOC, "q", ()),
                            value=IdentExpr(LOC, "d"), is_nonblocking=False)
        body = BlockStmt(LOC, statements=(assign,))
        if_stmt = IfStmt(LOC, cond=IdentExpr(LOC, "en"),
                         then_body=body, else_body=None)
        result = _correct_stmt(if_stmt)
        assert isinstance(result, IfStmt)
        assert result.then_body.statements[0].is_nonblocking is True

    def test_correct_stmt_forstmt(self):
        # Direct test: _correct_stmt on ForStmt
        LOC = SourceLocation("test.slip", 1, 1)
        assign = AssignStmt(LOC, target=LValue(LOC, "q", ()),
                            value=IdentExpr(LOC, "d"), is_nonblocking=False)
        body = BlockStmt(LOC, statements=(assign,))
        for_stmt = ForStmt(LOC, var="i", init=IntLiteralExpr(LOC, "0"),
                           cond=IntLiteralExpr(LOC, "1"), step_var="i",
                           step=IntLiteralExpr(LOC, "1"), body=body)
        result = _correct_stmt(for_stmt)
        assert isinstance(result, ForStmt)
        assert result.body.statements[0].is_nonblocking is True

    def test_correct_assign_in_stmt_nested_if(self):
        # IfStmt nested inside a seq block body (exercises _correct_assign_in_stmt)
        src = (
            "module m (clk, rst_n, en, d, q) { "
            "logic [7:0] d; logic [7:0] q; "
            "seq (clk, neg: rst_n) { "
            "if (en) { if (en) { q = d; } } "
            "} }"
        )
        sv = compile_source(src)
        assert "<=" in sv["m"]

    def test_correct_assign_in_stmt_for_in_seq(self):
        # ForStmt nested inside a seq block body
        LOC = SourceLocation("test.slip", 1, 1)
        assign = AssignStmt(LOC, target=LValue(LOC, "q", ()),
                            value=IdentExpr(LOC, "d"), is_nonblocking=False)
        body = BlockStmt(LOC, statements=(assign,))
        for_stmt = ForStmt(LOC, var="i", init=IntLiteralExpr(LOC, "0"),
                           cond=IntLiteralExpr(LOC, "1"), step_var="i",
                           step=IntLiteralExpr(LOC, "1"), body=body)
        seq_body = BlockStmt(LOC, statements=(for_stmt,))
        seq = SeqBlock(LOC, clock=IdentExpr(LOC, "clk"), reset=None, body=seq_body)
        result = _correct_stmt(seq)
        inner_for = result.body.statements[0]
        assert isinstance(inner_for, ForStmt)
        assert inner_for.body.statements[0].is_nonblocking is True


# ── IR builder ──────────────────────────────────────────────────

class TestIRBuilder:
    def test_system_func_skip(self):
        src = "module m (y) { logic [7:0] y; assign y = $clog2(8); }"
        # Should not crash - $clog2 should not create an implicit signal
        sv = compile_source(src)
        assert "m" in sv

    def test_gen_node_silent_skip(self):
        # After expansion, gen nodes should not appear. This tests the safety net.
        src = (
            "module m () { "
            "logic y_0; logic y_1; "
            "`for (`i = 0; `i < 2; `i = `i + 1) { assign y_`i = `i; } "
            "}"
        )
        sv = compile_source(src)
        assert "y_0" in sv["m"]
        assert "y_1" in sv["m"]


# ── Instance resolve ────────────────────────────────────────────

class TestInstanceResolve:
    def test_regex_existing_signal(self):
        src = (
            "module child (data_in, data_out) { "
            "logic [7:0] data_in; logic [7:0] data_out; "
            "assign data_out = data_in; "
            "} "
            "module parent (bus_in, bus_out) { "
            "logic [7:0] bus_in; logic [7:0] bus_out; "
            'child u1 { "data_(.*)" => "bus_\\1" }; '
            "}"
        )
        sv = compile_source(src)
        # bus_in and bus_out already exist, should be reused
        assert "bus_in" in sv["parent"]
        assert "bus_out" in sv["parent"]

    def test_multiple_regex_rules(self):
        src = (
            "module child (a_in, b_in, y_out) { "
            "logic [7:0] a_in; logic [7:0] b_in; logic [7:0] y_out; "
            "assign y_out = a_in + b_in; "
            "} "
            "module parent (x, y, z) { "
            "logic [7:0] x; logic [7:0] y; logic [7:0] z; "
            'child u1 { "a_(.*)" => "x", "b_(.*)" => "y", "y_(.*)" => "z" }; '
            "}"
        )
        sv = compile_source(src)
        assert "child" in sv["parent"]
