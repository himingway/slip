from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Sequence

from slip.codegen.emitter import emit
from slip.errors.semantic import SlipSemanticError
from slip.ir import HDLModule


def topological_sort(modules: Sequence[HDLModule]) -> list[HDLModule]:
    """Return modules sorted so that dependencies come before dependents.

    If module A instantiates module B (and B is in *modules*), then B
    will appear before A in the result.

    Uses Kahn's algorithm.  Cyclic dependencies raise SlipSemanticError.
    """
    if not modules:
        return []

    # Index by name for fast lookup
    by_name: dict[str, HDLModule] = {m.name: m for m in modules}
    name_list = [m.name for m in modules]

    # Build adjacency list and in-degree map
    # edge child -> parent means "child depends on parent"
    in_degree: dict[str, int] = {name: 0 for name in name_list}
    dependents: dict[str, list[str]] = {name: [] for name in name_list}

    for mod in modules:
        for inst in mod.instances:
            target = inst.target
            if target in by_name and target != mod.name:
                # mod depends on target
                dependents[target].append(mod.name)
                in_degree[mod.name] += 1

    # Kahn's algorithm: seed with zero-in-degree nodes
    queue: deque[str] = deque(
        name for name in name_list if in_degree[name] == 0
    )
    sorted_names: list[str] = []

    while queue:
        name = queue.popleft()
        sorted_names.append(name)
        for dep_name in dependents[name]:
            in_degree[dep_name] -= 1
            if in_degree[dep_name] == 0:
                queue.append(dep_name)

    # Cycle detection: anything not yet sorted is part of a cycle
    remaining = [n for n in name_list if n not in set(sorted_names)]
    if remaining:
        raise SlipSemanticError(
            "<generator>", 0, 0,
            f"cyclic module dependency detected among: {', '.join(remaining)}. "
            f"Cyclic instantiation is illegal in synthesizable hardware."
        )

    return [by_name[n] for n in sorted_names]


class CodeGenerator:
    def generate(
        self,
        ir_modules: list[HDLModule],
        output_dir: Path | None = None,
    ) -> dict[str, str]:
        """Generate SystemVerilog for all IR modules.

        Modules are topologically sorted so that dependencies are emitted
        before the modules that instantiate them.

        Returns a mapping of module_name -> sv_text.
        """
        results: dict[str, str] = {}
        sorted_modules = topological_sort(ir_modules)

        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)

        for mod in sorted_modules:
            sv_text = emit(mod)
            results[mod.name] = sv_text

            if output_dir is not None:
                out_file = output_dir / f"{mod.name}.sv"
                out_file.write_text(sv_text, encoding="utf-8")

        if output_dir is not None:
            _warn_stale_outputs(output_dir, set(results))

        return results


def _warn_stale_outputs(output_dir: Path, written: set[str]) -> None:
    """Warn about .sv files in the output directory this run did not write.

    Stale modules (e.g. left behind after a module was renamed or deleted)
    get picked up by downstream glob-based compile flows, so surface them
    rather than letting them silently mix into the build.
    """
    stale = sorted(
        p.name for p in output_dir.glob("*.sv")
        if p.stem not in written
    )
    if stale:
        import warnings
        warnings.warn(
            f"output directory {output_dir} contains SystemVerilog files not "
            f"produced by this run: {', '.join(stale)}. Remove them if they "
            f"are stale — downstream tools that compile the whole directory "
            f"would include them.",
            stacklevel=2,
        )
