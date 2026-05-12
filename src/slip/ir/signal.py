from dataclasses import dataclass

from slip.ir.types import HDLType


@dataclass(frozen=True)
class HDLSignal:
    name: str
    type_: HDLType | None = None
    array_dim: str | None = None  # SV text like "[0:15]"

    def decl_sv(self) -> str:
        width = ""
        if self.type_ and self.type_.width_sv:
            signed = "signed " if self.type_.is_signed else ""
            width = f"{signed}{self.type_.width_sv} "
        elif self.type_ and self.type_.is_signed:
            width = "signed "
        arr = f" {self.array_dim}" if self.array_dim else ""
        return f"logic {width}{self.name}{arr};"
