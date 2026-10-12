from __future__ import annotations

from dataclasses import dataclass, field

from slip.ast.base import ASTNode, SourceLocation
from slip.ast.expressions import Expr


@dataclass(frozen=True)
class NamedParam(ASTNode):
    name: str = ""
    value: Expr = field(default_factory=lambda: IdentExpr(SourceLocation("", 0, 0), ""))


@dataclass(frozen=True)
class Connection(ASTNode):
    port: str | None = None
    signal: Expr | None = None
    port_regex: str | None = None
    signal_regex: str | None = None


@dataclass(frozen=True)
class InstanceStmt(ASTNode):
    module_name: str = ""
    params: tuple[NamedParam, ...] = ()
    inst_name: str = ""
    connections: tuple[Connection, ...] = ()


from slip.ast.expressions import IdentExpr  # noqa: E402
