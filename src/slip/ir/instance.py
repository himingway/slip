from dataclasses import dataclass


@dataclass(frozen=True)
class HDLInstance:
    inst_name: str
    target: str
    param_map: tuple = ()       # tuple[tuple[str, str], ...]  (name, sv_expr)
    port_map: tuple = ()        # tuple[tuple[str, str], ...]  (port, sv_expr)
    regex_rules: tuple = ()     # tuple[tuple[str, str], ...]  (port_regex, signal_regex)
