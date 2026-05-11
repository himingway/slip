"""Corner case tests for semantic/expr_serializer.py."""

import pytest

from slip.ast.base import SourceLocation
from slip.ast.expressions import (
    BinaryExpr, CallExpr, CastExpr, ConcatExpr, IdentExpr,
    IndexExpr, IntLiteralExpr, ParenExpr, ReplicationExpr,
    StringLiteralExpr, TernaryExpr, TickConstExpr, TickIdentExpr,
    UnaryExpr,
)
from slip.semantic.expr_serializer import expr_to_sv

LOC = SourceLocation("test.slip", 1, 1)


class TestExprToSvCornerCases:
    def test_tick_ident(self):
        expr = TickIdentExpr(LOC, "i")
        assert expr_to_sv(expr) == "i"

    def test_string_literal(self):
        expr = StringLiteralExpr(LOC, '"hello"')
        assert expr_to_sv(expr) == '"hello"'

    def test_postfix_unary(self):
        expr = UnaryExpr(LOC, "++", IdentExpr(LOC, "i"), prefix=False)
        assert expr_to_sv(expr) == "i++"

    def test_prefix_unary(self):
        expr = UnaryExpr(LOC, "-", IdentExpr(LOC, "x"), prefix=True)
        assert expr_to_sv(expr) == "-x"

    def test_replication(self):
        expr = ReplicationExpr(LOC, count=IntLiteralExpr(LOC, "4"), inner=IntLiteralExpr(LOC, "1"))
        assert expr_to_sv(expr) == "{4{1}}"

    def test_cast(self):
        expr = CastExpr(LOC, "signed'", IdentExpr(LOC, "x"))
        assert expr_to_sv(expr) == "signed'(x)"

    def test_tick_const(self):
        expr = TickConstExpr(LOC, "'0")
        assert expr_to_sv(expr) == "'0"

    def test_tick_const_one(self):
        expr = TickConstExpr(LOC, "'1")
        assert expr_to_sv(expr) == "'1"

    def test_call_expr(self):
        expr = CallExpr(LOC, "foo", (IntLiteralExpr(LOC, "1"), IdentExpr(LOC, "x")))
        assert expr_to_sv(expr) == "foo(1, x)"

    def test_index_expr_single(self):
        expr = IndexExpr(LOC, IdentExpr(LOC, "a"), IntLiteralExpr(LOC, "3"))
        assert expr_to_sv(expr) == "a[3]"

    def test_index_expr_range(self):
        expr = IndexExpr(LOC, IdentExpr(LOC, "a"), IntLiteralExpr(LOC, "7"), IntLiteralExpr(LOC, "0"))
        assert expr_to_sv(expr) == "a[7:0]"

    def test_concat_expr(self):
        expr = ConcatExpr(LOC, (IdentExpr(LOC, "a"), IdentExpr(LOC, "b")))
        assert expr_to_sv(expr) == "{a, b}"

    def test_ternary_expr(self):
        expr = TernaryExpr(LOC, IdentExpr(LOC, "sel"), IntLiteralExpr(LOC, "1"), IntLiteralExpr(LOC, "0"))
        assert expr_to_sv(expr) == "sel ? 1 : 0"

    def test_binary_expr(self):
        expr = BinaryExpr(LOC, "+", IdentExpr(LOC, "a"), IdentExpr(LOC, "b"))
        assert expr_to_sv(expr) == "a + b"

    def test_paren_expr(self):
        expr = ParenExpr(LOC, BinaryExpr(LOC, "+", IdentExpr(LOC, "a"), IdentExpr(LOC, "b")))
        assert expr_to_sv(expr) == "(a + b)"

    def test_unknown_type_error(self):
        with pytest.raises(ValueError, match="unknown expression type"):
            expr_to_sv("not an expr")
