from dataclasses import dataclass


@dataclass(frozen=True)
class HDLType:
    base: str = "logic"
    width_sv: str | None = None  # raw SV text like "[7:0]" or "[W-1:0]"
    is_signed: bool = False

    def width_str(self) -> str:
        return self.width_sv if self.width_sv else ""
