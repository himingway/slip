from __future__ import annotations

import re
import warnings
from dataclasses import replace
from pathlib import Path

from slip.errors.semantic import SlipSemanticError
from slip.ir import HDLInstance, HDLModule, HDLPort, HDLSignal, HDLType
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


def _inst_loc(inst: HDLInstance):
    if inst.loc is not None:
        return inst.loc.file, inst.loc.line, inst.loc.col
    return "<instance>", 0, 0


def _unknown_module_error(inst: HDLInstance) -> SlipSemanticError:
    file, line, col = _inst_loc(inst)
    return SlipSemanticError(
        file, line, col,
        f"cannot resolve target module '{inst.target}' of instance "
        f"'{inst.inst_name}': not defined in the current compilation and "
        f"not found in the IP index (pass -ip/-f if this is external IP)"
    )


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

    for port in target.ports:
        if port.direction != "input":
            continue
        if port.name in connected_ports:
            continue
        file, line, col = _inst_loc(inst)
        raise SlipSemanticError(
            file, line, col,
            f"unconnected input port '{port.name}' of module "
            f"'{inst.target}' (instance '{inst.inst_name}')"
        )


def _check_duplicate_connections(inst: HDLInstance) -> None:
    """Reject connecting the same target port twice on one instance."""
    seen: set[str] = set()
    for name, _sig in inst.port_map:
        if name in seen:
            file, line, col = _inst_loc(inst)
            raise SlipSemanticError(
                file, line, col,
                f"duplicate connection to port '{name}' of instance "
                f"'{inst.inst_name}' (module '{inst.target}')"
            )
        seen.add(name)


def _resolve_module(
    mod: HDLModule,
    module_index: dict[str, HDLModule],
    ip_index: IPIndex,
) -> HDLModule:
    new_signals = list(mod.signals)
    new_ports = list(mod.ports)
    new_instances: list[HDLInstance] = []

    for inst in mod.instances:
        # Check localparam override
        if inst.param_map:
            lp_names = _get_target_localparams(inst.target, module_index, ip_index)
            for pname, _ in inst.param_map:
                if pname in lp_names:
                    file, line, col = _inst_loc(inst)
                    raise SlipSemanticError(
                        file, line, col,
                        f"cannot override localparam '{pname}' of module "
                        f"'{inst.target}' (instance '{inst.inst_name}')"
                    )

        _check_duplicate_connections(inst)

        # Resolve target ports — an unknown module is always an error, so
        # typos are caught even when every port is connected by name.
        if inst.target in module_index:
            target = module_index[inst.target]
            target_ports = [
                (p.name, p.direction, p.type_.width_sv if p.type_ else None)
                for p in target.ports
            ]
        else:
            ports = ip_index.get_ports(inst.target)
            if ports is None:
                raise _unknown_module_error(inst)
            target_ports = ports

        _apply_connection_inference(
            inst.port_map, target_ports, new_signals, new_ports, inst.target
        )

        if not inst.regex_rules:
            # Check required ports for explicit (non-regex) connections
            _check_required_ports(inst, module_index)
            new_instances.append(inst)
            continue
        expanded_inst, extra_signals = _expand_regex_connections(
            inst, mod, target_ports, new_signals, new_ports
        )
        new_instances.append(expanded_inst)
        new_signals.extend(extra_signals)

    return HDLModule(
        name=mod.name,
        params=mod.params,
        localparams=mod.localparams,
        ports=tuple(new_ports),
        signals=tuple(new_signals),
        assigns=mod.assigns,
        logic_blocks=mod.logic_blocks,
        instances=tuple(new_instances),
    )


def _apply_connection_inference(
    port_map: tuple[tuple[str, str], ...],
    target_ports: list[tuple[str, str, str | None]],
    signals: list[HDLSignal],
    ports: list,
    target_name: str,
) -> None:
    """Propagate target-port information into connected signals and ports.

    - Width: a width-less connected signal/port inherits the target port's
      width (annotated with "width from <target>.<port>"), preserving an
      explicit ``signed`` qualifier.
    - Direction: a local port connected to a target *output* is driven by
      that instance and must be an output (fixes pass-through wrappers
      whose only driver is a child module's output port).
    """
    target_info = {name: (direction, width) for name, direction, width in target_ports}

    for port_name, signal_name in port_map:
        if signal_name == "_":
            continue
        info = target_info.get(port_name)
        if info is None:
            continue
        t_direction, t_width = info

        if t_width is not None:
            for i, sig in enumerate(signals):
                if sig.name == signal_name and (sig.type_ is None or sig.type_.width_sv is None):
                    is_signed = sig.type_.is_signed if sig.type_ else False
                    signals[i] = HDLSignal(
                        sig.name,
                        type_=HDLType(width_sv=t_width, is_signed=is_signed),
                        array_dim=sig.array_dim,
                        width_inferred_from=f"{target_name}.{port_name}",
                    )
                    break
            for i, p in enumerate(ports):
                if p.name == signal_name and (p.type_ is None or p.type_.width_sv is None):
                    is_signed = p.type_.is_signed if p.type_ else False
                    ports[i] = HDLPort(
                        name=p.name,
                        direction=p.direction,
                        type_=HDLType(width_sv=t_width, is_signed=is_signed),
                        array_dim=p.array_dim,
                        width_inferred_from=f"{target_name}.{port_name}",
                        declared=p.declared,
                    )
                    break

        if t_direction == "output":
            for i, p in enumerate(ports):
                if p.name == signal_name and p.direction == "input":
                    ports[i] = replace(p, direction="output")
                    break


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
    target_ports: list[tuple[str, str, str | None]],
    existing_signals: list[HDLSignal],
    existing_ports: list,
) -> tuple[HDLInstance, list[HDLSignal]]:
    """Expand regex port connections for a single instance."""
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
                try:
                    candidate = evaluate_replacement(signal_regex, port_name, port_regex)
                except ValueError as e:
                    file, line, col = _inst_loc(inst)
                    raise SlipSemanticError(
                        file, line, col,
                        f"regex port mapping error for port '{port_name}' of "
                        f"instance '{inst.inst_name}': {e}"
                    ) from e
                inferred_from = f"{inst.target}.{port_name}"
                if candidate in signal_names_in_scope:
                    port_map[port_name] = candidate
                    _apply_connection_inference(
                        ((port_name, candidate),),
                        [(port_name, direction, width_sv)],
                        existing_signals, existing_ports, inst.target,
                    )
                    matched = True
                    break
                implicit_signals.append(HDLSignal(
                    candidate,
                    HDLType(width_sv=width_sv),
                    width_inferred_from=inferred_from,
                    declared=False,
                ))
                signal_names_in_scope.add(candidate)
                port_map[port_name] = candidate
                matched = True
                break

        if not matched:
            if direction == "output":
                warnings.warn(
                    f"unconnected output port '{port_name}' in instance "
                    f"'{inst.inst_name}' of module '{inst.target}'"
                )
            else:
                active_rules = ", ".join(
                    f"\"{pr}\" => \"{sr}\"" for pr, sr in inst.regex_rules
                ) if inst.regex_rules else "(none)"
                file, line, col = _inst_loc(inst)
                raise SlipSemanticError(
                    file, line, col,
                    f"unconnected input port '{port_name}' in instance "
                    f"'{inst.inst_name}' of module '{inst.target}' — "
                    f"no explicit connection or regex match "
                    f"(active regex rules: {active_rules})"
                )

    updated_inst = HDLInstance(
        inst_name=inst.inst_name,
        target=inst.target,
        param_map=inst.param_map,
        port_map=tuple(port_map.items()),
        regex_rules=(),
        loc=inst.loc,
    )
    return updated_inst, implicit_signals
