"""Expression serialization is meaning-preserving.

``expr_to_sv`` emits SystemVerilog text that is later re-parsed by the
downstream toolchain (and by Slip itself when the generated file is read
back).  The invariants pinned here:

* the emitted text re-parses, under Slip's own grammar — which mirrors
  IEEE 1800-2017 operator precedence — into a tree structurally
  identical to the original AST (parentheses ignored);
* explicit parentheses are preserved when they change grouping;
* the emitter never re-emits a piece of text that would bind differently.

Every failure here is a silent wrong-hardware bug, so this file is
deliberately exhaustive about operator combinations.
"""

import pytest

from slip.ast.expressions import (
    BinaryExpr,
    CallExpr,
    CastExpr,
    ConcatExpr,
    Expr,
    IdentExpr,
    IndexExpr,
    IntLiteralExpr,
    ParenExpr,
    ReplicationExpr,
    TernaryExpr,
    TickConstExpr,
    TickIdentExpr,
    UnaryExpr,
)
from slip.lexer import Lexer
from slip.parser import Parser
from slip.semantic.expr_serializer import expr_to_sv


def _parse_expr(source: str) -> Expr:
    """Parse a bare expression by embedding it in an assignment."""
    src = f"module m (a, b, c, d, e, y) {{ assign y = {source}; }}"
    unit = Parser(Lexer(src, "t.slip").tokenize(), "t.slip").parse()
    return unit.modules[0].body[0].value


def _shape(expr: Expr):
    """Structural shape of an expression, ignoring locations and parens."""
    if isinstance(expr, ParenExpr):
        return _shape(expr.inner)
    if isinstance(expr, IdentExpr):
        return ("id", expr.name)
    if isinstance(expr, TickIdentExpr):
        return ("tick", expr.name)
    if isinstance(expr, IntLiteralExpr):
        return ("int", expr.raw)
    if isinstance(expr, TickConstExpr):
        return ("tickconst", expr.raw)
    if isinstance(expr, BinaryExpr):
        return ("bin", expr.op, _shape(expr.left), _shape(expr.right))
    if isinstance(expr, UnaryExpr):
        return ("un", expr.op, bool(expr.prefix), _shape(expr.operand))
    if isinstance(expr, TernaryExpr):
        return ("tern", _shape(expr.cond), _shape(expr.true_expr), _shape(expr.false_expr))
    if isinstance(expr, IndexExpr):
        return (
            "idx", _shape(expr.base),
            _shape(expr.index) if expr.index is not None else None,
            _shape(expr.high) if expr.high is not None else None,
            expr.is_slice,
        )
    if isinstance(expr, ConcatExpr):
        return ("cat", tuple(_shape(p) for p in expr.parts))
    if isinstance(expr, ReplicationExpr):
        return ("rep", _shape(expr.count), _shape(expr.inner))
    if isinstance(expr, CastExpr):
        return ("cast", expr.target, _shape(expr.inner))
    if isinstance(expr, CallExpr):
        return ("call", expr.func, tuple(_shape(a) for a in expr.args))
    raise AssertionError(f"unhandled {type(expr).__name__}")


# Operator combinations whose relative precedence/associativity differs
# between languages that get this wrong.  Each must round-trip.
ROUNDTRIP_CASES = [
    # shift vs relational vs equality (the classic inversion)
    "a << 2 == b",
    "a == b << 2",
    "a < b << c",
    "a >> 1 != b",
    "a + 1 << b",
    "a < b == c",
    # bitwise vs comparison
    "a & b == c",
    "a | b != c",
    "a ^ b == c",
    "a & b | c ^ d",
    # logical vs bitwise
    "a && b || c",
    "a && b & c",
    # arithmetic
    "a + b * c - d / e",
    "a % b + c",
    "a * b % c",
    # exponentiation: left-assoc, below unary
    "a ** b ** c",
    "a ** 2 * b",
    "-a ** b",
    "a ** -b",
    # unary
    "!a && b",
    "~a & b",
    "-a + b",
    "(a + b) * c",
    "-(a + b)",
    # ternary
    "a ? b : c ? d : e",
    "a ? b ? c : d : e",
    "a + b ? c : d",
    "a == b ? c + d : e * f",
    # inside
    "a inside {b, c}",
    "a == b inside {c}",
    "a + 1 inside {b, c}",
    # indexing and slices
    "a[b + 1]",
    "a[b:0]",
    "a[7:4] & b",
    "a[0] == b[1]",
    # concatenation / replication
    "{a, b} == c",
    "{2{a}} & b",
    "{a, b[1:0]}",
    # casts
    "8'(a + b)",
    "signed'(a) == b",
    # width interaction with shifts
    "a << b + 1",
    "a >> (b - 1)",
]


@pytest.mark.parametrize("source", ROUNDTRIP_CASES)
def test_serialization_roundtrips(source):
    """serialize(parse(e)) must re-parse to the same shape as parse(e)."""
    original = _parse_expr(source)
    emitted = expr_to_sv(original)
    reparsed = _parse_expr(emitted)
    assert _shape(reparsed) == _shape(original), (
        f"{source!r}: emitted {emitted!r} which re-parses differently\n"
        f"  original: {_shape(original)}\n"
        f"  reparsed: {_shape(reparsed)}"
    )


@pytest.mark.parametrize("source", ROUNDTRIP_CASES)
def test_serialization_is_stable(source):
    """A second round-trip is a fixed point (no paren accumulation)."""
    emitted = expr_to_sv(_parse_expr(source))
    again = expr_to_sv(_parse_expr(emitted))
    assert again == emitted


class TestExplicitParensPreserved:
    """User parentheses that change grouping survive serialization."""

    @pytest.mark.parametrize("source,expect_fragment", [
        ("(a + b) * c", "(a + b) * c"),
        ("a - (b - c)", "a - (b - c)"),
        ("a / (b * c)", "a / (b * c)"),
    ])
    def test_parens_kept(self, source, expect_fragment):
        assert expr_to_sv(_parse_expr(source)) == expect_fragment

    def test_redundant_parens_dropped_without_changing_meaning(self):
        original = _parse_expr("(a) + (b)")
        emitted = expr_to_sv(original)
        assert _shape(_parse_expr(emitted)) == _shape(original)

    def test_left_associativity_not_regrouped(self):
        """a - (b - c) must not be emitted as a - b - c."""
        original = _parse_expr("a - (b - c)")
        emitted = expr_to_sv(original)
        assert _shape(_parse_expr(emitted)) == _shape(original)
        assert emitted != "a - b - c"
