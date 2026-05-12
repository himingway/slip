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
    StringLiteralExpr,
    TernaryExpr,
    TickConstExpr,
    TickIdentExpr,
    UnaryExpr,
)


def expr_to_sv(expr: Expr) -> str:
    """Serialize an AST expression to SystemVerilog text."""
    if isinstance(expr, IdentExpr):
        return expr.name
    if isinstance(expr, TickIdentExpr):
        return expr.name
    if isinstance(expr, IntLiteralExpr):
        return expr.raw
    if isinstance(expr, StringLiteralExpr):
        return expr.value
    if isinstance(expr, ParenExpr):
        return f"({expr_to_sv(expr.inner)})"
    if isinstance(expr, BinaryExpr):
        return f"{expr_to_sv(expr.left)} {expr.op} {expr_to_sv(expr.right)}"
    if isinstance(expr, UnaryExpr):
        if expr.prefix:
            return f"{expr.op}{expr_to_sv(expr.operand)}"
        return f"{expr_to_sv(expr.operand)}{expr.op}"
    if isinstance(expr, TernaryExpr):
        return f"{expr_to_sv(expr.cond)} ? {expr_to_sv(expr.true_expr)} : {expr_to_sv(expr.false_expr)}"
    if isinstance(expr, IndexExpr):
        base = expr_to_sv(expr.base)
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
    if isinstance(expr, TickConstExpr):
        return expr.raw
    raise ValueError(f"unknown expression type: {type(expr).__name__}")
