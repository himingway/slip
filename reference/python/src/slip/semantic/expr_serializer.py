from slip.ast.expressions import (
    BinaryExpr,
    CallExpr,
    CastExpr,
    ConcatExpr,
    Expr,
    IdentExpr,
    IndexExpr,
    IntLiteralExpr,
    MethodCallExpr,
    ParenExpr,
    ReplicationExpr,
    StringLiteralExpr,
    TernaryExpr,
    TickConstExpr,
    TickIdentExpr,
    UnaryExpr,
)

# Precedence levels mirroring IEEE 1800-2017 Table 11-2 (must match
# INFIX_BP in slip.parser.pratt). Higher binds tighter. The serializer
# uses these to parenthesize operands whose precedence is lower than the
# context requires, so the emitted text always re-parses to the same
# grouping as the AST -- even if the parser's table ever drifts again.
_OP_LEVEL: dict[str, int] = {
    "||": 2,
    "&&": 3,
    "|": 4,
    "^": 5,
    "&": 6,
    "==": 7,
    "!=": 7,
    "===": 7,
    "!==": 7,
    "<": 8,
    "<=": 8,
    ">": 8,
    ">=": 8,
    "inside": 8,
    "<<": 9,
    ">>": 9,
    "<<<": 9,
    ">>>": 9,
    "+": 10,
    "-": 10,
    "*": 11,
    "/": 11,
    "%": 11,
    "**": 12,
}
_UNARY_LEVEL = 13
_ATOM_LEVEL = 99  # literals, identifiers, postfix chains, braces, casts, parens


def _level(expr: Expr) -> int:
    if isinstance(expr, BinaryExpr):
        return _OP_LEVEL.get(expr.op, 0)  # unknown ops parenthesize conservatively
    if isinstance(expr, TernaryExpr):
        return 1
    if isinstance(expr, UnaryExpr):
        return _UNARY_LEVEL
    return _ATOM_LEVEL


def _sv(expr: Expr, min_level: int) -> str:
    """Serialize expr, parenthesizing it if its precedence is below min_level."""
    text = _serialize(expr)
    if _level(expr) < min_level:
        return f"({text})"
    return text


def _serialize(expr: Expr) -> str:
    if isinstance(expr, IdentExpr):
        return expr.name
    if isinstance(expr, TickIdentExpr):
        return expr.name
    if isinstance(expr, IntLiteralExpr):
        return expr.raw
    if isinstance(expr, StringLiteralExpr):
        return expr.value
    if isinstance(expr, ParenExpr):
        return f"({_serialize(expr.inner)})"
    if isinstance(expr, BinaryExpr):
        level = _level(expr)
        # All Slip binary operators are left-associative: the right operand
        # must bind at least one level tighter to avoid re-grouping.
        left = _sv(expr.left, level)
        right = _sv(expr.right, level + 1)
        return f"{left} {expr.op} {right}"
    if isinstance(expr, UnaryExpr):
        if expr.prefix:
            return f"{expr.op}{_sv(expr.operand, _UNARY_LEVEL)}"
        return f"{_sv(expr.operand, _UNARY_LEVEL)}{expr.op}"
    if isinstance(expr, TernaryExpr):
        # ?: is right-associative and loosest: the condition needs parens
        # only if it is itself a ternary; the false branch never does.
        cond = _sv(expr.cond, 2)
        true_expr = _sv(expr.true_expr, 0)
        false_expr = _sv(expr.false_expr, 0)
        return f"{cond} ? {true_expr} : {false_expr}"
    if isinstance(expr, IndexExpr):
        base = _sv(expr.base, _ATOM_LEVEL)
        if expr.is_slice:
            start = expr_to_sv(expr.index) if expr.index is not None else ""
            end = expr_to_sv(expr.high) if expr.high is not None else ""
            return f"{base}[{start}:{end}]"
        return f"{base}[{expr_to_sv(expr.index)}]"
    if isinstance(expr, ConcatExpr):
        parts = ", ".join(expr_to_sv(p) for p in expr.parts)
        return f"{{{parts}}}"
    if isinstance(expr, ReplicationExpr):
        count = expr_to_sv(expr.count)
        inner = expr_to_sv(expr.inner)
        return "{" + count + "{" + inner + "}}"
    if isinstance(expr, CastExpr):
        return f"{expr.target}({expr_to_sv(expr.inner)})"
    if isinstance(expr, CallExpr):
        args = ", ".join(expr_to_sv(a) for a in expr.args)
        return f"{expr.func}({args})"
    if isinstance(expr, MethodCallExpr):
        args = ", ".join(expr_to_sv(a) for a in expr.args)
        return f"{expr_to_sv(expr.obj)}.{expr.method}({args})"
    if isinstance(expr, TickConstExpr):
        return expr.raw
    raise ValueError(f"unknown expression type: {type(expr).__name__}")


def expr_to_sv(expr: Expr) -> str:
    """Serialize an AST expression to SystemVerilog text."""
    return _sv(expr, 0)
