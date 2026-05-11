from dataclasses import dataclass


@dataclass(frozen=True)
class HDLIfBlock:
    cond: str  # SV expression text
    then_body: tuple = ()  # tuple of HDLAssignment | HDLIfBlock
    else_body: tuple | None = None  # tuple of HDLAssignment | HDLIfBlock | None


@dataclass(frozen=True)
class LogicBlock:
    sensitivity: str  # e.g. "posedge clk or negedge rst_n"
    body: tuple = ()  # tuple of HDLAssignment | HDLIfBlock
    kind: str = "always_ff"
