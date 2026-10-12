"""Module dependency ordering shared by interface resolution and generation."""

from collections import deque
from typing import Sequence

from slip.errors.semantic import SlipSemanticError
from slip.ir.module import HDLModule


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
    if len(by_name) != len(name_list):
        raise SlipSemanticError("<generator>", 0, 0, "duplicate module definition")

    # Build adjacency list and in-degree map
    # Edges point from child modules to the parents that instantiate them.
    in_degree: dict[str, int] = {name: 0 for name in name_list}
    dependents: dict[str, list[str]] = {name: [] for name in name_list}

    for mod in modules:
        for inst in mod.instances:
            target = inst.target
            if target in by_name:
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
    completed = set(sorted_names)
    remaining = [n for n in name_list if n not in completed]
    if remaining:
        raise SlipSemanticError(
            "<generator>", 0, 0,
            f"cyclic module dependency detected among: {', '.join(remaining)}. "
            f"Cyclic instantiation is illegal in synthesizable hardware."
        )

    return [by_name[n] for n in sorted_names]
