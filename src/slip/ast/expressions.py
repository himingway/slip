from __future__ import annotations

from dataclasses import dataclass, field

from slip.ast.base import ASTNode, SourceLocation


@dataclass(frozen=True)
class Expr(ASTNode):
    """Base class for all expression nodes."""


@dataclass(frozen=True)
class IdentExpr(Expr):
    name: str


@dataclass(frozen=True)
class IntLiteralExpr(Expr):
    raw: str


@dataclass(frozen=True)
class TickConstExpr(Expr):
    raw: str  # "'0" or "'1"


@dataclass(frozen=True)
class TickIdentExpr(Expr):
    name: str  # "i" (without backtick prefix)


@dataclass(frozen=True)
class StringLiteralExpr(Expr):
    value: str


@dataclass(frozen=True)
class BinaryExpr(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(frozen=True)
class UnaryExpr(Expr):
    op: str
    operand: Expr
    prefix: bool = True


@dataclass(frozen=True)
class TernaryExpr(Expr):
    cond: Expr
    true_expr: Expr
    false_expr: Expr


@dataclass(frozen=True)
class IndexExpr(Expr):
    base: Expr
    index: Expr | None = None  # None = omitted (e.g., s[:3])
    high: Expr | None = None  # None = single index or slice to end (e.g., s[3:])
    is_slice: bool = False  # True if this is a slice (has :)


@dataclass(frozen=True)
class ConcatExpr(Expr):
    parts: tuple[Expr, ...]


@dataclass(frozen=True)
class ReplicationExpr(Expr):
    count: Expr
    inner: Expr


@dataclass(frozen=True)
class CastExpr(Expr):
    target: str  # "signed'" or "unsigned'"
    inner: Expr


@dataclass(frozen=True)
class CallExpr(Expr):
    func: str
    args: tuple[Expr, ...]


@dataclass(frozen=True)
class ParenExpr(Expr):
    inner: Expr


@dataclass(frozen=True)
class MethodCallExpr(Expr):
    obj: Expr
    method: str
    args: tuple[Expr, ...] = ()
