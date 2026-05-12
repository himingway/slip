from dataclasses import dataclass

_VALID_KINDS = {"always_ff", "always_comb", "always_latch", "initial"}


@dataclass(frozen=True)
class HDLIfBlock:
    cond: str  # SV expression text
    then_body: tuple = ()  # tuple of HDLAssignment | HDLIfBlock | HDLForLoop
    else_body: tuple | None = None  # tuple of HDLAssignment | HDLIfBlock | HDLForLoop | None


@dataclass(frozen=True)
class HDLForLoop:
    var: str
    init: str  # SV expression text
    cond: str  # SV expression text
    step: str  # SV expression text (e.g. "i = i + 1")
    body: tuple = ()  # tuple of HDLAssignment | HDLIfBlock | HDLForLoop


@dataclass(frozen=True)
class HDLCaseItem:
    patterns: tuple[str, ...] = ()  # SV text per pattern; empty = default
    body: tuple = ()  # tuple of HDLAssignment | HDLIfBlock | HDLForLoop | HDLCaseBlock


@dataclass(frozen=True)
class HDLCaseBlock:
    kind: str = "case"  # "case", "casez", "casex"
    expr: str = ""  # SV expression text
    items: tuple[HDLCaseItem, ...] = ()


@dataclass(frozen=True)
class LogicBlock:
    sensitivity: str  # e.g. "posedge clk or negedge rst_n"
    body: tuple = ()  # tuple of HDLAssignment | HDLIfBlock | HDLForLoop
    kind: str = "always_ff"

    def __post_init__(self):
        if self.kind not in _VALID_KINDS:
            raise TypeError(
                f"invalid LogicBlock.kind: {self.kind!r} "
                f"(expected one of {', '.join(sorted(_VALID_KINDS))})"
            )
