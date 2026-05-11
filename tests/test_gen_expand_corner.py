"""Corner case tests for semantic/gen_expand.py."""

import pytest
from pathlib import Path

from slip.ast.base import SourceLocation
from slip.ast.expressions import (
    BinaryExpr, CallExpr, CastExpr, ConcatExpr, IdentExpr,
    IndexExpr, IntLiteralExpr, ParenExpr, ReplicationExpr,
    StringLiteralExpr, TernaryExpr, TickConstExpr, TickIdentExpr,
    UnaryExpr,
)
from slip.ast.instance import Connection, InstanceStmt, NamedParam
from slip.ast.statements import (
    AssignStmt, BlockStmt, CombBlock, ForStmt, IfStmt,
    LocalParamDecl, LValue, SeqBlock, SignalDecl,
)
from slip.errors.semantic import SlipSemanticError
from slip.semantic.gen_expand import (
    _eval_int, _parse_int_literal, _sub_expr, _sub_stmt, expand_module,
)

from conftest import compile_source, parse_module

LOC = SourceLocation("test.slip", 1, 1)


# ── _eval_int: division/modulo by zero ──────────────────────────

class TestEvalDivModByZero:
    def test_div_by_zero_returns_zero(self):
        expr = BinaryExpr(LOC, "/", IntLiteralExpr(LOC, "10"), IntLiteralExpr(LOC, "0"))
        assert _eval_int(expr, {}, LOC) == 0

    def test_mod_by_zero_returns_zero(self):
        expr = BinaryExpr(LOC, "%", IntLiteralExpr(LOC, "10"), IntLiteralExpr(LOC, "0"))
        assert _eval_int(expr, {}, LOC) == 0


# ── _eval_int: untested operators ───────────────────────────────

class TestEvalUntestedOperators:
    def test_greater_than(self):
        expr = BinaryExpr(LOC, ">", IntLiteralExpr(LOC, "5"), IntLiteralExpr(LOC, "3"))
        assert _eval_int(expr, {}, LOC) == 1

    def test_greater_than_false(self):
        expr = BinaryExpr(LOC, ">", IntLiteralExpr(LOC, "2"), IntLiteralExpr(LOC, "3"))
        assert _eval_int(expr, {}, LOC) == 0

    def test_less_equal(self):
        src = "module m #(param N = 3) (y) { `if (N <= 3) { assign y = 1; } }"
        sv = compile_source(src)
        assert "assign y = 1" in sv["m"]

    def test_not_equal(self):
        src = "module m #(param N = 5) (y) { `if (N != 3) { assign y = 1; } }"
        sv = compile_source(src)
        assert "assign y = 1" in sv["m"]

    def test_bitwise_not(self):
        expr = UnaryExpr(LOC, "~", IntLiteralExpr(LOC, "0"))
        assert _eval_int(expr, {}, LOC) == -1

    def test_division(self):
        expr = BinaryExpr(LOC, "/", IntLiteralExpr(LOC, "10"), IntLiteralExpr(LOC, "3"))
        assert _eval_int(expr, {}, LOC) == 3

    def test_modulo(self):
        expr = BinaryExpr(LOC, "%", IntLiteralExpr(LOC, "10"), IntLiteralExpr(LOC, "3"))
        assert _eval_int(expr, {}, LOC) == 1

    def test_right_shift(self):
        expr = BinaryExpr(LOC, ">>", IntLiteralExpr(LOC, "8"), IntLiteralExpr(LOC, "1"))
        assert _eval_int(expr, {}, LOC) == 4


# ── _eval_int: unsupported operator errors ──────────────────────

class TestEvalUnsupportedOps:
    def test_unsupported_binary_op(self):
        expr = BinaryExpr(LOC, "**", IntLiteralExpr(LOC, "2"), IntLiteralExpr(LOC, "3"))
        with pytest.raises(SlipSemanticError, match="unsupported operator"):
            _eval_int(expr, {}, LOC)

    def test_unsupported_unary_op(self):
        expr = UnaryExpr(LOC, "&", IntLiteralExpr(LOC, "1"))
        with pytest.raises(SlipSemanticError, match="unsupported unary operator"):
            _eval_int(expr, {}, LOC)


# ── _eval_int: unsupported expression types ─────────────────────

class TestEvalUnsupportedExprTypes:
    def test_call_expr_error(self):
        expr = CallExpr(LOC, "foo", (IntLiteralExpr(LOC, "1"),))
        with pytest.raises(SlipSemanticError, match="not evaluable"):
            _eval_int(expr, {}, LOC)

    def test_concat_expr_error(self):
        expr = ConcatExpr(LOC, (IntLiteralExpr(LOC, "1"),))
        with pytest.raises(SlipSemanticError, match="not evaluable"):
            _eval_int(expr, {}, LOC)

    def test_ternary_expr_error(self):
        expr = TernaryExpr(LOC, IntLiteralExpr(LOC, "1"),
                           IntLiteralExpr(LOC, "2"), IntLiteralExpr(LOC, "3"))
        with pytest.raises(SlipSemanticError, match="not evaluable"):
            _eval_int(expr, {}, LOC)


# ── _eval_int: TickIdentExpr error path ─────────────────────────

class TestEvalTickIdentErrors:
    def test_tick_ident_not_in_params(self):
        expr = TickIdentExpr(LOC, "x")
        with pytest.raises(SlipSemanticError, match="cannot evaluate"):
            _eval_int(expr, {}, LOC)


# ── _sub_expr: untested expression types ────────────────────────

class TestSubExprCornerCases:
    def test_sub_ternary_expr(self):
        expr = TernaryExpr(
            LOC,
            cond=IdentExpr(LOC, "i"),
            true_expr=IntLiteralExpr(LOC, "1"),
            false_expr=IntLiteralExpr(LOC, "0"),
        )
        result = _sub_expr(expr, "i", 5)
        assert isinstance(result, TernaryExpr)
        assert isinstance(result.cond, IntLiteralExpr)
        assert result.cond.raw == "5"

    def test_sub_replication_expr(self):
        expr = ReplicationExpr(
            LOC,
            count=IdentExpr(LOC, "i"),
            inner=IntLiteralExpr(LOC, "1"),
        )
        result = _sub_expr(expr, "i", 4)
        assert isinstance(result, ReplicationExpr)
        assert isinstance(result.count, IntLiteralExpr)
        assert result.count.raw == "4"

    def test_sub_cast_expr(self):
        expr = CastExpr(LOC, "signed'", IdentExpr(LOC, "i"))
        result = _sub_expr(expr, "i", 7)
        assert isinstance(result, CastExpr)
        assert isinstance(result.inner, IntLiteralExpr)
        assert result.inner.raw == "7"

    def test_sub_call_expr(self):
        expr = CallExpr(LOC, "foo", (IdentExpr(LOC, "i"), IntLiteralExpr(LOC, "2")))
        result = _sub_expr(expr, "i", 3)
        assert isinstance(result, CallExpr)
        assert result.args[0].raw == "3"
        assert result.args[1].raw == "2"

    def test_sub_string_literal_passthrough(self):
        expr = StringLiteralExpr(LOC, '"hello"')
        result = _sub_expr(expr, "i", 0)
        assert result is expr

    def test_sub_tick_const_passthrough(self):
        expr = TickConstExpr(LOC, "'0")
        result = _sub_expr(expr, "i", 0)
        assert result is expr

    def test_sub_postfix_unary(self):
        expr = UnaryExpr(LOC, "++", IdentExpr(LOC, "i"), prefix=False)
        result = _sub_expr(expr, "i", 5)
        assert isinstance(result, UnaryExpr)
        assert result.prefix is False
        assert isinstance(result.operand, IntLiteralExpr)

    def test_sub_index_expr(self):
        expr = IndexExpr(LOC, IdentExpr(LOC, "arr"), IdentExpr(LOC, "i"))
        result = _sub_expr(expr, "i", 3)
        assert isinstance(result, IndexExpr)
        assert isinstance(result.index, IntLiteralExpr)
        assert result.index.raw == "3"

    def test_sub_index_expr_with_range(self):
        expr = IndexExpr(LOC, IdentExpr(LOC, "arr"), IdentExpr(LOC, "i"),
                         high=IdentExpr(LOC, "i"))
        result = _sub_expr(expr, "i", 1)
        assert isinstance(result.index, IntLiteralExpr)
        assert isinstance(result.high, IntLiteralExpr)

    def test_sub_concat_expr(self):
        expr = ConcatExpr(LOC, (IdentExpr(LOC, "i"), IntLiteralExpr(LOC, "1")))
        result = _sub_expr(expr, "i", 7)
        assert isinstance(result, ConcatExpr)
        assert isinstance(result.parts[0], IntLiteralExpr)
        assert result.parts[0].raw == "7"

    def test_sub_paren_expr(self):
        expr = ParenExpr(LOC, IdentExpr(LOC, "i"))
        result = _sub_expr(expr, "i", 9)
        assert isinstance(result, ParenExpr)
        assert isinstance(result.inner, IntLiteralExpr)
        assert result.inner.raw == "9"

    def test_sub_unknown_expr_passthrough(self):
        # Fallthrough: expression type not explicitly handled returns as-is
        expr = IntLiteralExpr(LOC, "42")
        result = _sub_expr(expr, "i", 0)
        assert result is expr


# ── _sub_stmt: statement-level substitution ────────────────────

class TestSubStmt:
    def test_sub_seq_block(self):
        assign = AssignStmt(LOC, target=LValue(LOC, "q", ()),
                            value=IdentExpr(LOC, "i"), is_nonblocking=True)
        body = BlockStmt(LOC, statements=(assign,))
        stmt = SeqBlock(LOC, clock=IdentExpr(LOC, "clk"), reset=None, body=body)
        result = _sub_stmt(stmt, "i", 5)
        assert isinstance(result, SeqBlock)

    def test_sub_comb_block(self):
        assign = AssignStmt(LOC, target=LValue(LOC, "y", ()),
                            value=IdentExpr(LOC, "i"), is_nonblocking=False)
        body = BlockStmt(LOC, statements=(assign,))
        stmt = CombBlock(LOC, body=body)
        result = _sub_stmt(stmt, "i", 2)
        assert isinstance(result, CombBlock)

    def test_sub_if_stmt(self):
        assign = AssignStmt(LOC, target=LValue(LOC, "y", ()),
                            value=IdentExpr(LOC, "i"), is_nonblocking=False)
        body = BlockStmt(LOC, statements=(assign,))
        stmt = IfStmt(LOC, cond=IdentExpr(LOC, "i"), then_body=body, else_body=None)
        result = _sub_stmt(stmt, "i", 1)
        assert isinstance(result, IfStmt)

    def test_sub_for_stmt(self):
        assign = AssignStmt(LOC, target=LValue(LOC, "y", ()),
                            value=IdentExpr(LOC, "i"), is_nonblocking=False)
        body = BlockStmt(LOC, statements=(assign,))
        stmt = ForStmt(LOC, var="i", init=IntLiteralExpr(LOC, "0"),
                       cond=IdentExpr(LOC, "i"), step_var="i",
                       step=IdentExpr(LOC, "i"), body=body)
        result = _sub_stmt(stmt, "i", 0)
        assert isinstance(result, ForStmt)

    def test_sub_instance_stmt(self):
        param = NamedParam(LOC, name="W", value=IdentExpr(LOC, "i"))
        conn = Connection(LOC, port="d", signal=IdentExpr(LOC, "i"),
                          port_regex=None, signal_regex=None)
        stmt = InstanceStmt(LOC, module_name="child", params=(param,),
                            inst_name="u1", connections=(conn,))
        result = _sub_stmt(stmt, "i", 8)
        assert isinstance(result, InstanceStmt)

    def test_sub_localparam_decl(self):
        stmt = LocalParamDecl(LOC, name="K", value=IdentExpr(LOC, "i"))
        result = _sub_stmt(stmt, "i", 42)
        assert isinstance(result, LocalParamDecl)
        assert isinstance(result.value, IntLiteralExpr)

    def test_sub_block_stmt(self):
        assign = AssignStmt(LOC, target=LValue(LOC, "y", ()),
                            value=IdentExpr(LOC, "i"), is_nonblocking=False)
        stmt = BlockStmt(LOC, statements=(assign,))
        result = _sub_stmt(stmt, "i", 3)
        assert isinstance(result, BlockStmt)

    def test_sub_signal_decl(self):
        stmt = SignalDecl(LOC, is_signed=False, width=None,
                          name="data_`i", array_range=None)
        result = _sub_stmt(stmt, "i", 0)
        assert isinstance(result, SignalDecl)
        assert result.name == "data_0"


# ── expand_module: gen_for in various containers ────────────────

class TestExpandInContainers:
    def test_gen_for_inside_seq(self):
        src = (
            "module m (clk, rst_n) { "
            "logic [7:0] data_0; logic [7:0] data_1; logic [7:0] data_2; "
            "seq (clk, neg: rst_n) { "
            "`for (`i = 0; `i < 3; `i = `i + 1) { "
            "assign data_`i = `i; "
            "} "
            "} }"
        )
        sv = compile_source(src)
        assert "data_0" in sv["m"]
        assert "data_1" in sv["m"]
        assert "data_2" in sv["m"]

    def test_gen_for_inside_comb(self):
        src = (
            "module m () { "
            "logic y_0; logic y_1; "
            "comb { "
            "`for (`i = 0; `i < 2; `i = `i + 1) { "
            "assign y_`i = `i; "
            "} "
            "} }"
        )
        sv = compile_source(src)
        assert "y_0" in sv["m"]
        assert "y_1" in sv["m"]

    def test_gen_for_inside_if(self):
        src = (
            "module m #(param MODE = 1) () { "
            "logic y_0; logic y_1; "
            "`if (MODE) { "
            "`for (`i = 0; `i < 2; `i = `i + 1) { "
            "assign y_`i = `i; "
            "} "
            "} }"
        )
        sv = compile_source(src)
        assert "y_0" in sv["m"]

    def test_nested_gen_for(self):
        # Nested gen_for with separate signal names per iteration
        src = (
            "module m () { "
            "logic a0; logic a1; logic b0; logic b1; "
            "`for (`i = 0; `i < 2; `i = `i + 1) { "
            "assign a`i = `i; "
            "`for (`j = 0; `j < 2; `j = `j + 1) { "
            "assign b`j = `i + `j; "
            "} "
            "} }"
        )
        sv = compile_source(src)
        assert "a0" in sv["m"]
        assert "a1" in sv["m"]
        assert "b0" in sv["m"]
        assert "b1" in sv["m"]
