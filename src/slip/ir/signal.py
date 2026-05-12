from dataclasses import dataclass

from slip.ir.types import HDLType


@dataclass(frozen=True)
class HDLSignal:
    name: str
    type_: HDLType | None = None
    array_dim: str | None = None  # SV text like "[0:15]"
    width_inferred_from: str | None = None  # e.g. "child.data_out"
    declared: bool = True  # False for implicit signals

    def decl_sv(self) -> str:
        width = ""
        has_width = self.type_ and self.type_.width_sv
        if has_width:
            signed = "signed " if self.type_.is_signed else ""
            width = f"{signed}{self.type_.width_sv} "
        elif self.type_ and self.type_.is_signed:
            width = "signed "
        arr = f" {self.array_dim}" if self.array_dim else ""
        tags = []
        if not self.declared:
            tags.append("implicit")
        if not has_width:
            tags.append("no width")
        if self.width_inferred_from:
            tags.append(f"width from {self.width_inferred_from}")
        comment = f"  // {', '.join(tags)}" if tags else ""
        return f"logic {width}{self.name}{arr};{comment}"
