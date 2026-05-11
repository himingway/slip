from __future__ import annotations

from dataclasses import dataclass, field

from slip.ast.base import ASTNode, SourceLocation
from slip.ast.expressions import Expr


@dataclass(frozen=True)
class Statement(ASTNode):
    """Base class for all statement nodes."""


@dataclass(frozen=True)
class BlockStmt(ASTNode):
    statements: tuple[Statement, ...] = ()


@dataclass(frozen=True)
class SignalDecl(Statement):
    is_signed: bool = False
    width: Expr | None = None
    name: str = ""
    array_range: tuple[Expr, Expr] | None = None


@dataclass(frozen=True)
class LValue(ASTNode):
    name: str = ""
    indices: tuple = ()  # each element: Expr (single) or (Expr, Expr) (range)


@dataclass(frozen=True)
class AssignStmt(Statement):
    target: LValue = field(default_factory=lambda: LValue(SourceLocation("", 0, 0)))
    value: Expr = field(default_factory=lambda: IdentExpr(SourceLocation("", 0, 0), ""))
    is_nonblocking: bool = False


@dataclass(frozen=True)
class SeqBlock(Statement):
    clock: str = ""
    reset: tuple[str, str] | None = None  # ('neg', 'rst_n') or ('pos', 'rst')
    body: BlockStmt = field(default_factory=lambda: BlockStmt(SourceLocation("", 0, 0)))


@dataclass(frozen=True)
class CombBlock(Statement):
    body: BlockStmt = field(default_factory=lambda: BlockStmt(SourceLocation("", 0, 0)))


@dataclass(frozen=True)
class IfStmt(Statement):
    cond: Expr = field(default_factory=lambda: IdentExpr(SourceLocation("", 0, 0), ""))
    then_body: BlockStmt = field(default_factory=lambda: BlockStmt(SourceLocation("", 0, 0)))
    else_body: BlockStmt | None = None


@dataclass(frozen=True)
class ForStmt(Statement):
    var: str = ""
    init: Expr = field(default_factory=lambda: IntLiteralExpr(SourceLocation("", 0, 0), "0"))
    cond: Expr = field(default_factory=lambda: IdentExpr(SourceLocation("", 0, 0), ""))
    step_var: str = ""
    step: Expr = field(default_factory=lambda: IntLiteralExpr(SourceLocation("", 0, 0), "1"))
    body: BlockStmt = field(default_factory=lambda: BlockStmt(SourceLocation("", 0, 0)))


@dataclass(frozen=True)
class LocalParamDecl(Statement):
    name: str = ""
    value: Expr = field(default_factory=lambda: IntLiteralExpr(SourceLocation("", 0, 0), "0"))


# Re-import needed for field defaults
from slip.ast.expressions import IdentExpr, IntLiteralExpr  # noqa: E402
