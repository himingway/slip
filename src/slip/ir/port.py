from dataclasses import dataclass

from slip.ir.types import HDLType


@dataclass(frozen=True)
class HDLPort:
    name: str
    direction: str  # 'input', 'output', 'inout'
    type_: HDLType = None

    def decl_sv(self) -> str:
        if self.type_ and self.type_.width_sv:
            return f"{self.direction} logic {self.type_.width_sv} {self.name}"
        if self.type_ and self.type_.is_signed:
            return f"{self.direction} logic signed {self.name}"
        return f"{self.direction} logic {self.name}"
