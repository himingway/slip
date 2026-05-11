from __future__ import annotations

from dataclasses import dataclass, field

from slip.ast.base import ASTNode, SourceLocation
from slip.ast.expressions import Expr
from slip.ast.statements import Statement


@dataclass(frozen=True)
class Param(ASTNode):
    name: str = ""
    default: Expr = field(default_factory=lambda: IntLiteralExpr(SourceLocation("", 0, 0), "0"))


@dataclass(frozen=True)
class PortItem(ASTNode):
    name: str = ""
    width: Expr | None = None


@dataclass(frozen=True)
class Module(ASTNode):
    name: str = ""
    params: tuple[Param, ...] = ()
    ports: tuple[PortItem, ...] = ()  # empty = implicit
    body: tuple = ()  # tuple[Statement, ...]


from slip.ast.expressions import IntLiteralExpr  # noqa: E402
