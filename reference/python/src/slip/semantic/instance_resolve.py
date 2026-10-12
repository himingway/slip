from __future__ import annotations

import re
import warnings
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from slip.errors.semantic import SlipSemanticError
from slip.ir import HDLDesign, HDLInstance, HDLModule, HDLParam, HDLPort, HDLSignal, HDLType
from slip.semantic.regex_funcs import evaluate_replacement
from slip.slang_integration.ip_scanner import IPIndex, build_ip_index


def resolve_instances(
    ir_modules: list[HDLModule],
    ip_dirs: list[Path],
    filelists: list[Path] | None = None,
) -> HDLDesign:
    """Resolve regex port mappings for all instances across all modules."""
    module_index: dict[str, HDLModule] = {m.name: m for m in ir_modules}

    # Build IP index from filelists and IP directories
    ip_index = build_ip_index(filelists, ip_dirs)

    from slip.ir.dependency import topological_sort

    for mod in topological_sort(ir_modules):
        module_index[mod.name] = _resolve_module(mod, module_index, ip_index)
    return HDLDesign([module_index[m.name] for m in ir_modules], ip_index)


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
    driven_by = _local_drivers(mod)

    for inst in mod.instances:
        _check_duplicate_connections(inst)
        if inst.target in module_index:
            target = module_index[inst.target]
        else:
            info = ip_index.get_module(inst.target)
            if info is None:
                raise _unknown_module_error(inst)
            target = HDLModule(
                name=inst.target,
                params=tuple(HDLParam(p.name, p.expression or p.default or "0")
                             for p in info.params if not p.is_local),
                localparams=tuple(HDLParam(p.name, p.expression or p.default or "0")
                                  for p in info.params if p.is_local),
                ports=tuple(HDLPort(
                    p.name, p.direction,
                    HDLType(width_sv=p.width_expression or p.width, is_signed=p.is_signed),
                    array_dim=p.array_dim,
                ) for p in info.ports),
            )
        _validate_interface(inst, target)
        target_ports = _instantiate_interface(inst, target)

        _apply_connection_inference(
            inst.port_map, target_ports, new_signals, new_ports, inst.target
        )

        if not inst.regex_rules:
            # Check required ports for explicit (non-regex) connections
            _check_required_ports(inst, module_index)
            _check_instance_drivers(inst, target_ports, driven_by)
            new_instances.append(inst)
            continue
        expanded_inst, extra_signals = _expand_regex_connections(
            inst, mod, target_ports, new_signals, new_ports
        )
        _check_instance_drivers(expanded_inst, target_ports, driven_by)
        new_instances.append(expanded_inst)
        new_signals.extend(extra_signals)

    return replace(mod, ports=tuple(new_ports), signals=tuple(new_signals),
                   instances=tuple(new_instances))


@lru_cache(maxsize=1024)
def _connection_expr(text):
    from slip.lexer import Lexer
    from slip.parser.pratt import PrattParser
    return PrattParser(Lexer(text, "<connection>").tokenize(), 0, "<connection>").parse_expression()


def _storage(expr):
    """Lvalue storage, excluding names read to calculate its indices."""
    from slip.ast.expressions import IdentExpr, IndexExpr, ConcatExpr, ParenExpr
    from slip.semantic.indexing import index_spec
    if isinstance(expr, IdentExpr):
        return [(expr.name, ())]
    if isinstance(expr, IndexExpr):
        spec = index_spec([(expr.index, expr.high)] if expr.is_slice else [expr.index])
        return [(name, prior + spec if prior is not None and spec is not None else None)
                for name, prior in _storage(expr.base)]
    if isinstance(expr, ConcatExpr):
        return [item for part in expr.parts for item in _storage(part)]
    if isinstance(expr, ParenExpr):
        return _storage(expr.inner)
    return []


def _local_drivers(mod):
    from slip.ir import HDLAssignment, HDLIfBlock, HDLCaseBlock, HDLForLoop
    drivers = {}
    def add(target, source, whole=False):
        for name, spec in _storage(_connection_expr(target)):
            drivers.setdefault(name, []).append((None if whole else spec, source))
    def walk(items, source):
        for item in items:
            if isinstance(item, HDLAssignment):
                add(item.target, source, whole=True)
            elif isinstance(item, HDLIfBlock):
                walk(item.then_body, source)
                walk(item.else_body or (), source)
            elif isinstance(item, HDLCaseBlock):
                for arm in item.items:
                    walk(arm.body, source)
            elif isinstance(item, HDLForLoop):
                walk(item.body, source)
    for assignment in mod.assigns:
        add(assignment.target, "continuous assignment")
    for i, block in enumerate(mod.logic_blocks):
        if block.kind != "initial":
            walk(block.body, f"{block.kind} block {i + 1}")
    return drivers


def _check_instance_drivers(inst, target_ports, drivers):
    from slip.semantic.indexing import specs_overlap
    outputs = {p.name for p in target_ports if p.direction == "output"}
    for port, connection in inst.port_map:
        if port not in outputs or connection == "_":
            continue
        storage = _storage(_connection_expr(connection))
        if not storage:
            raise SlipSemanticError(*_inst_loc(inst), f"output port '{port}' requires an assignable connection")
        for name, spec in storage:
            source = f"{inst.inst_name}.{port}"
            for prior_spec, prior_source in drivers.get(name, ()):
                if specs_overlap(spec, prior_spec):
                    raise SlipSemanticError(
                        *_inst_loc(inst), f"signal '{name}' driven by multiple drivers "
                        f"({prior_source} and {source})"
                    )
            drivers.setdefault(name, []).append((spec, source))


def _validate_interface(inst: HDLInstance, target: HDLModule) -> None:
    loc = _inst_loc(inst)
    ports = {p.name for p in target.ports}
    params = {p.name for p in target.params}
    locals_ = {p.name for p in target.localparams}
    seen = set()
    for name, _ in inst.param_map:
        if name in seen:
            raise SlipSemanticError(*loc, f"duplicate parameter override '{name}'")
        seen.add(name)
        if name in locals_:
            raise SlipSemanticError(*loc, f"cannot override localparam '{name}' of module '{target.name}'")
        if name not in params:
            raise SlipSemanticError(*loc, f"parameter '{name}' does not exist in '{target.name}'")
        if name in dict(target.frozen_params):
            raise SlipSemanticError(
                *loc, f"cannot override parameter '{name}' of '{target.name}': "
                "it controls Slip compile-time expansion; use a separate module configuration"
            )
    for name, _ in inst.port_map:
        if name not in ports:
            raise SlipSemanticError(*loc, f"port '{name}' does not exist in '{target.name}'")


_IDENT = re.compile(r"(?<![\w$'])\b([A-Za-z_]\w*)\b")


def _instantiate_interface(inst: HDLInstance, target: HDLModule) -> list[HDLPort]:
    """Translate target-scoped dimensions into the caller's parameter scope.

    Overrides are opaque caller expressions: their names must never be
    substituted a second time as if they belonged to the child module.
    """
    overrides = dict(inst.param_map)
    defaults = {p.name: p.default for p in (*target.params, *target.localparams)}
    resolved = {name: f"({expression})" for name, expression in overrides.items()}
    visiting = set()

    def substitute(expression):
        return _IDENT.sub(lambda match: resolve(match[0]) if match[0] in defaults else match[0], expression)

    def resolve(name):
        if name in resolved:
            return resolved[name]
        if name in visiting:
            raise SlipSemanticError(*_inst_loc(inst), f"cyclic parameter dependency in '{target.name}'")
        visiting.add(name)
        resolved[name] = f"({substitute(defaults[name])})"
        visiting.remove(name)
        return resolved[name]

    def dimension(text):
        if text is None:
            return None
        result = substitute(text)
        # Simplify literal bounds only; caller parameter expressions remain
        # symbolic so downstream parameter overrides keep working.
        from slip.slang_integration.constants import evaluate_constant
        def simplify(match):
            try:
                high = evaluate_constant(match[1], {})
                low = evaluate_constant(match[2], {})
                return f"[{high}:{low}]"
            except ValueError:
                return match[0]
        return re.sub(r"\[([^\[\]]+):([^\[\]]+)\]", simplify, result)

    return [replace(
        p, type_=replace(p.type_, width_sv=dimension(p.type_.width_sv)) if p.type_ else None,
        array_dim=dimension(p.array_dim),
    ) for p in target.ports]


def _apply_connection_inference(
    port_map: tuple[tuple[str, str], ...],
    target_ports: list[HDLPort],
    signals: list[HDLSignal],
    ports: list[HDLPort],
    target_name: str,
) -> None:
    target_info = {p.name: p for p in target_ports}
    for port_name, connection in port_map:
        target = target_info.get(port_name)
        if target is None or connection == "_":
            continue
        # Direction follows the storage driven by output/inout connections,
        # including selects and concatenations. Width inference only applies
        # to a whole signal, never to an expression or individual selected bit.
        expr = _connection_expr(connection)
        from slip.ast.expressions import IdentExpr
        whole = expr.name if isinstance(expr, IdentExpr) else None
        driven_names = {name for name, _ in _storage(expr)}
        for collection in (signals, ports):
            for i, item in enumerate(collection):
                updated = item
                if whole == item.name:
                    item_type = item.type_ or HDLType()
                    if item_type.width_sv is None and target.type_ and target.type_.width_sv is not None:
                        updated = replace(
                            updated,
                            type_=replace(item_type, width_sv=target.type_.width_sv,
                                          is_signed=item_type.is_signed or target.type_.is_signed),
                            width_inferred_from=f"{target_name}.{port_name}",
                        )
                    if item.array_dim is None and target.array_dim:
                        updated = replace(updated, array_dim=target.array_dim)
                if isinstance(item, HDLPort) and item.name in driven_names:
                    if target.direction == "output" and item.direction == "input":
                        updated = replace(updated, direction="output")
                    elif target.direction == "inout":
                        updated = replace(updated, direction="inout")
                collection[i] = updated


def _expand_regex_connections(
    inst: HDLInstance,
    parent_mod: HDLModule,
    target_ports: list[HDLPort],
    existing_signals: list[HDLSignal],
    existing_ports: list,
) -> tuple[HDLInstance, list[HDLSignal]]:
    """Expand regex port connections for a single instance."""
    port_map = dict(inst.port_map)

    signal_names_in_scope = (
        {p.name for p in parent_mod.ports}
        | {s.name for s in parent_mod.signals}
        | {p.name for p in parent_mod.params}
        | {p.name for p in parent_mod.localparams}
        | {s.name for s in existing_signals}
    )

    implicit_signals: list[HDLSignal] = []

    for target_port in target_ports:
        port_name, direction = target_port.name, target_port.direction
        width_sv = target_port.type_.width_sv if target_port.type_ else None
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
                    for signals in (existing_signals, implicit_signals):
                        _apply_connection_inference(
                            ((port_name, candidate),), [target_port],
                            signals, existing_ports, inst.target,
                        )
                    matched = True
                    break
                implicit_signals.append(HDLSignal(
                    candidate,
                    target_port.type_,
                    array_dim=target_port.array_dim,
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
