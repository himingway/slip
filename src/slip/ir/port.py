from dataclasses import dataclass

from slip.ir.types import HDLType

_VALID_DIRECTIONS = {"input", "output", "inout"}


@dataclass(frozen=True)
class HDLPort:
    name: str
    direction: str = "input"
    type_: HDLType | None = None

    def __post_init__(self):
        if self.direction not in _VALID_DIRECTIONS:
            raise TypeError(
                f"invalid HDLPort.direction: {self.direction!r} "
                f"(expected one of {', '.join(sorted(_VALID_DIRECTIONS))})"
            )

    def decl_sv(self) -> str:
        if self.type_ and self.type_.width_sv:
            return f"{self.direction} logic {self.type_.width_sv} {self.name}"
        if self.type_ and self.type_.is_signed:
            return f"{self.direction} logic signed {self.name}"
        return f"{self.direction} logic {self.name}"
