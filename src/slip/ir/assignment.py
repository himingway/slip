from dataclasses import dataclass


@dataclass(frozen=True)
class HDLAssignment:
    target: str
    value: str  # SV expression text
    is_nonblocking: bool = False

    def to_sv(self) -> str:
        op = "<=" if self.is_nonblocking else "="
        return f"{self.target} {op} {self.value};"
