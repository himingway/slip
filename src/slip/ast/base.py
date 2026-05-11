from dataclasses import dataclass


@dataclass(frozen=True)
class SourceLocation:
    file: str
    line: int
    col: int


@dataclass(frozen=True)
class ASTNode:
    loc: SourceLocation
