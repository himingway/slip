from __future__ import annotations

import re
import warnings
from pathlib import Path

from slip.errors.semantic import SlipSemanticError
from slip.ir import HDLInstance, HDLModule, HDLSignal, HDLType
from slip.semantic.regex_funcs import evaluate_replacement
from slip.slang_integration.ip_scanner import IPIndex, build_ip_index


def resolve_instances(
    ir_modules: list[HDLModule],
    ip_dirs: list[Path],
    filelists: list[Path] | None = None,
) -> list[HDLModule]:
    """Resolve regex port mappings for all instances across all modules."""
    module_index: dict[str, HDLModule] = {m.name: m for m in ir_modules}

    # Build IP index from filelists and IP directories
    ip_index = build_ip_index(filelists, ip_dirs)

    results: list[HDLModule] = []
    for mod in ir_modules:
        results.append(_resolve_module(mod, module_index, ip_index))
    return results


def _check_required_ports(
    inst: HDLInstance,
    module_index: dict[str, HDLModule],
) -> None:
    """Check that all required (input) ports of the target module are connected.

    Only checks when the target module is in the current compilation unit
    (not external IP).  Ports explicitly marked as dangling with ``"_"`` are
    excluded from the check.
    """
    if inst.target not in module_index:
        return  # External IP — skip

    target = module_index[inst.target]

    connected_ports = {name for name, _sig in inst.port_map}
    regex_ports = {name for name, _sig in inst.regex_rules}
    all_connected = connected_ports | regex_ports

    for port in target.ports:
        if port.direction != "input":
            continue
        if port.name in all_connected:
            # Port is connected (even if to "_", it's intentional)
            continue
        raise SlipSemanticError(
            "<instance>", 0, 0,
            f"unconnected input port '{port.name}' of module '{inst.target}'"
        )


def _resolve_module(
    mod: HDLModule,
    module_index: dict[str, HDLModule],
    ip_index: IPIndex,
) -> HDLModule:
    new_signals = list(mod.signals)
    new_instances: list[HDLInstance] = []

    for inst in mod.instances:
        # Check localparam override
        if inst.param_map:
            lp_names = _get_target_localparams(inst.target, module_index, ip_index)
            for pname, _ in inst.param_map:
                if pname in lp_names:
                    raise SlipSemanticError(
                        "<instance>", 0, 0,
                        f"cannot override localparam '{pname}'"
                    )

        if not inst.regex_rules:
            # Check required ports for explicit (non-regex) connections
            _check_required_ports(inst, module_index)
            new_instances.append(inst)
            continue
        expanded_inst, extra_signals = _expand_regex_connections(
            inst, mod, module_index, ip_index, new_signals
        )
        new_instances.append(expanded_inst)
        new_signals.extend(extra_signals)

    return HDLModule(
        name=mod.name,
        params=mod.params,
        localparams=mod.localparams,
        ports=mod.ports,
        signals=tuple(new_signals),
        assigns=mod.assigns,
        logic_blocks=mod.logic_blocks,
        instances=tuple(new_instances),
    )


def _get_target_ports(
    target_name: str,
    module_index: dict[str, HDLModule],
    ip_index: IPIndex,
) -> list[tuple[str, str, str | None]]:
    """Get target module ports as (name, direction, width_sv) tuples."""
    # Check local modules first
    if target_name in module_index:
        target = module_index[target_name]
        return [
            (p.name, p.direction, p.type_.width_sv if p.type_ else None)
            for p in target.ports
        ]

    # Check IP index
    ports = ip_index.get_ports(target_name)
    if ports is not None:
        return ports

    raise SlipSemanticError(
        "<instance>", 0, 0,
        f"cannot resolve target module '{target_name}'"
    )


def _get_target_localparams(
    target_name: str,
    module_index: dict[str, HDLModule],
    ip_index: IPIndex,
) -> set[str]:
    """Get the set of localparam names for a target module."""
    # Check local modules first
    if target_name in module_index:
        return {lp.name for lp in module_index[target_name].localparams}

    # Check IP index
    return ip_index.get_localparams(target_name)


def _expand_regex_connections(
    inst: HDLInstance,
    parent_mod: HDLModule,
    module_index: dict[str, HDLModule],
    ip_index: IPIndex,
    existing_signals: list[HDLSignal],
) -> tuple[HDLInstance, list[HDLSignal]]:
    """Expand regex port connections for a single instance."""
    target_ports = _get_target_ports(inst.target, module_index, ip_index)

    port_map = dict(inst.port_map)

    signal_names_in_scope = (
        {p.name for p in parent_mod.ports}
        | {s.name for s in parent_mod.signals}
        | {p.name for p in parent_mod.params}
        | {s.name for s in existing_signals}
    )

    implicit_signals: list[HDLSignal] = []

    for port_name, direction, width_sv in target_ports:
        if port_name in port_map:
            if port_map[port_name] == "_":
                continue  # intentionally dangling
            continue

        matched = False
        for port_regex, signal_regex in inst.regex_rules:
            if re.fullmatch(port_regex, port_name):
                candidate = evaluate_replacement(signal_regex, port_name, port_regex)
                if candidate in signal_names_in_scope:
                    port_map[port_name] = candidate
                    matched = True
                    break
                implicit_signals.append(HDLSignal(candidate, HDLType(width_sv=width_sv)))
                signal_names_in_scope.add(candidate)
                port_map[port_name] = candidate
                matched = True
                break

        if not matched:
            if direction == "output":
                warnings.warn(
                    f"unconnected output port '{port_name}' in instance '{inst.inst_name}'"
                )
            else:
                raise SlipSemanticError(
                    "<instance>", 0, 0,
                    f"unconnected input port '{port_name}' in instance '{inst.inst_name}'"
                )

    updated_inst = HDLInstance(
        inst_name=inst.inst_name,
        target=inst.target,
        param_map=inst.param_map,
        port_map=tuple(port_map.items()),
        regex_rules=(),
    )
    return updated_inst, implicit_signals
