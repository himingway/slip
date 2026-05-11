"""Corner case tests for parser/pratt.py expression parsing."""

import pytest

from slip.ast.expressions import (
    BinaryExpr, CallExpr, CastExpr, ConcatExpr, IdentExpr,
    IndexExpr, IntLiteralExpr, ParenExpr, TernaryExpr, UnaryExpr,
)
from conftest import parse_module


class TestPrefixOperators:
    def test_prefix_bitwise_and(self):
        mod = parse_module("module m (a, y) { assign y = &a; }")
        stmt = mod.body[0]
        assert isinstance(stmt.value, UnaryExpr)
        assert stmt.value.op == "&"

    def test_prefix_bitwise_or(self):
        mod = parse_module("module m (a, y) { assign y = |a; }")
        stmt = mod.body[0]
        assert isinstance(stmt.value, UnaryExpr)
        assert stmt.value.op == "|"

    def test_prefix_bitwise_xor(self):
        mod = parse_module("module m (a, y) { assign y = ^a; }")
        stmt = mod.body[0]
        assert isinstance(stmt.value, UnaryExpr)
        assert stmt.value.op == "^"

    def test_prefix_logical_not(self):
        mod = parse_module("module m (a, y) { assign y = !a; }")
        stmt = mod.body[0]
        assert isinstance(stmt.value, UnaryExpr)
        assert stmt.value.op == "!"

    def test_prefix_bitwise_not(self):
        mod = parse_module("module m (a, y) { assign y = ~a; }")
        stmt = mod.body[0]
        assert isinstance(stmt.value, UnaryExpr)
        assert stmt.value.op == "~"

    def test_prefix_negate(self):
        mod = parse_module("module m (a, y) { assign y = -a; }")
        stmt = mod.body[0]
        assert isinstance(stmt.value, UnaryExpr)
        assert stmt.value.op == "-"


class TestPostfixOperators:
    def test_function_call(self):
        mod = parse_module("module m (y) { assign y = foo(1, 2); }")
        stmt = mod.body[0]
        assert isinstance(stmt.value, CallExpr)
        assert stmt.value.func == "foo"
        assert len(stmt.value.args) == 2

    def test_index_single(self):
        mod = parse_module("module m (a, y) { assign y = a[3]; }")
        stmt = mod.body[0]
        assert isinstance(stmt.value, IndexExpr)
        assert stmt.value.high is None

    def test_index_range(self):
        mod = parse_module("module m (a, y) { assign y = a[7:0]; }")
        stmt = mod.body[0]
        assert isinstance(stmt.value, IndexExpr)
        assert stmt.value.high is not None


class TestCastExpressions:
    def test_signed_cast(self):
        mod = parse_module("module m (a, y) { assign y = signed'(a); }")
        stmt = mod.body[0]
        assert isinstance(stmt.value, CastExpr)
        assert stmt.value.target == "signed'"

    def test_unsigned_cast(self):
        mod = parse_module("module m (a, y) { assign y = unsigned'(a); }")
        stmt = mod.body[0]
        assert isinstance(stmt.value, CastExpr)
        assert stmt.value.target == "unsigned'"


class TestConcatenation:
    def test_simple_concat(self):
        mod = parse_module("module m (a, b, y) { assign y = {a, b}; }")
        stmt = mod.body[0]
        assert isinstance(stmt.value, ConcatExpr)
        assert len(stmt.value.parts) == 2

    def test_three_part_concat(self):
        mod = parse_module("module m (a, b, c, y) { assign y = {a, b, c}; }")
        stmt = mod.body[0]
        assert isinstance(stmt.value, ConcatExpr)
        assert len(stmt.value.parts) == 3


class TestTernary:
    def test_ternary_basic(self):
        mod = parse_module("module m (sel, a, b, y) { assign y = sel ? a : b; }")
        stmt = mod.body[0]
        assert isinstance(stmt.value, TernaryExpr)

    def test_ternary_right_associative(self):
        mod = parse_module("module m (a, b, c, d, e, y) { assign y = a ? b : c ? d : e; }")
        stmt = mod.body[0]
        assert isinstance(stmt.value, TernaryExpr)
        # Right-associative: a ? b : (c ? d : e)
        assert isinstance(stmt.value.false_expr, TernaryExpr)


class TestOperatorPrecedence:
    def test_mul_over_add(self):
        mod = parse_module("module m (a, b, c, y) { assign y = a + b * c; }")
        stmt = mod.body[0]
        assert isinstance(stmt.value, BinaryExpr)
        assert stmt.value.op == "+"
        assert isinstance(stmt.value.right, BinaryExpr)
        assert stmt.value.right.op == "*"

    def test_parentheses_override(self):
        mod = parse_module("module m (a, b, c, y) { assign y = (a + b) * c; }")
        stmt = mod.body[0]
        assert isinstance(stmt.value, BinaryExpr)
        assert stmt.value.op == "*"
        assert isinstance(stmt.value.left, ParenExpr)
