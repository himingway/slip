from dataclasses import dataclass

from slip.ir.types import HDLType

_VALID_DIRECTIONS = {"input", "output", "inout"}


@dataclass(frozen=True)
class HDLPort:
    name: str
    direction: str = "input"
    type_: HDLType | None = None
    array_dim: str | None = None  # SV text like "[0:3]"
    width_inferred_from: str | None = None  # e.g. "child.data_out"
    declared: bool = True  # False for implicit ports

    def __post_init__(self):
        if self.direction not in _VALID_DIRECTIONS:
            raise TypeError(
                f"invalid HDLPort.direction: {self.direction!r} "
                f"(expected one of {', '.join(sorted(_VALID_DIRECTIONS))})"
            )

    def decl_sv(self) -> str:
        width = ""
        has_width = self.type_ and self.type_.width_sv
        if has_width:
            signed = "signed " if self.type_.is_signed else ""
            width = f"{signed}{self.type_.width_sv} "
        elif self.type_ and self.type_.is_signed:
            width = "signed "
        arr = f" {self.array_dim}" if self.array_dim else ""
        return f"{self.direction} logic {width}{self.name}{arr}"
