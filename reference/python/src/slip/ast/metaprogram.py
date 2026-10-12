from __future__ import annotations

from dataclasses import dataclass, field

from slip.ast.base import ASTNode, SourceLocation
from slip.ast.expressions import Expr, IdentExpr, IntLiteralExpr
from slip.ast.statements import BlockStmt, Statement


@dataclass(frozen=True)
class GenForStmt(Statement):
    var: str = ""
    init: Expr = field(default_factory=lambda: IntLiteralExpr(SourceLocation("", 0, 0), "0"))
    cond: Expr = field(default_factory=lambda: IdentExpr(SourceLocation("", 0, 0), ""))
    step_var: str = ""
    step: Expr = field(default_factory=lambda: IntLiteralExpr(SourceLocation("", 0, 0), "1"))
    body: BlockStmt = field(default_factory=lambda: BlockStmt(SourceLocation("", 0, 0)))


@dataclass(frozen=True)
class GenIfStmt(Statement):
    cond: Expr = field(default_factory=lambda: IdentExpr(SourceLocation("", 0, 0), ""))
    then_body: BlockStmt = field(default_factory=lambda: BlockStmt(SourceLocation("", 0, 0)))
    else_body: BlockStmt | None = None
