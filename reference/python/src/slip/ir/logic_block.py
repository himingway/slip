from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from slip.ir.assignment import HDLAssignment

_VALID_KINDS = {"always_ff", "always_comb", "always_latch", "initial"}


@dataclass(frozen=True)
class HDLIfBlock:
    cond: str  # SV expression text
    then_body: tuple[HDLBlockItem, ...] = ()
    else_body: tuple[HDLBlockItem, ...] | None = None


@dataclass(frozen=True)
class HDLForLoop:
    var: str
    init: str  # SV expression text
    cond: str  # SV expression text
    step: str  # SV expression text (e.g. "i = i + 1")
    body: tuple[HDLBlockItem, ...] = ()


@dataclass(frozen=True)
class HDLCaseItem:
    patterns: tuple[str, ...] = ()  # SV text per pattern; empty = default
    body: tuple[HDLBlockItem, ...] = ()


@dataclass(frozen=True)
class HDLCaseBlock:
    kind: Literal["case", "casez", "casex"] = "case"
    expr: str = ""  # SV expression text
    items: tuple[HDLCaseItem, ...] = ()


@dataclass(frozen=True)
class LogicBlock:
    sensitivity: str  # e.g. "posedge clk or negedge rst_n"
    body: tuple[HDLBlockItem, ...] = ()
    kind: Literal["always_ff", "always_comb", "always_latch", "initial"] = "always_ff"

    def __post_init__(self):
        if self.kind not in _VALID_KINDS:
            raise TypeError(
                f"invalid LogicBlock.kind: {self.kind!r} "
                f"(expected one of {', '.join(sorted(_VALID_KINDS))})"
            )


HDLBlockItem = HDLAssignment | HDLIfBlock | HDLForLoop | HDLCaseBlock
