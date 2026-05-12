"""Tests for module topological sort in the code generator."""

import warnings

from slip.codegen.generator import topological_sort
from slip.ir import HDLInstance, HDLModule


def _mod(name: str, targets: tuple[str, ...] = ()) -> HDLModule:
    """Helper to build an HDLModule with instances targeting the given names."""
    instances = tuple(
        HDLInstance(inst_name=f"u_{t}", target=t) for t in targets
    )
    return HDLModule(name=name, instances=instances)


class TestTopologicalSort:
    def test_dependency_ordering(self):
        """Module that instantiates another comes after it."""
        a = _mod("A", targets=("B",))
        b = _mod("B")

        result = topological_sort([a, b])
        names = [m.name for m in result]
        assert names.index("B") < names.index("A")

    def test_independent_modules_preserve_order(self):
        """Independent modules maintain their relative order."""
        x = _mod("X")
        y = _mod("Y")
        z = _mod("Z")

        result = topological_sort([x, y, z])
        names = [m.name for m in result]
        assert names == ["X", "Y", "Z"]

    def test_three_level_chain(self):
        """Three-level dependency chain: C depends on B, B depends on A."""
        c = _mod("C", targets=("B",))
        b = _mod("B", targets=("A",))
        a = _mod("A")

        result = topological_sort([c, b, a])
        names = [m.name for m in result]
        assert names.index("A") < names.index("B") < names.index("C")

    def test_cycle_handling(self):
        """Cycles do not cause infinite loops; a warning is emitted."""
        a = _mod("A", targets=("B",))
        b = _mod("B", targets=("A",))

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = topological_sort([a, b])

        # Both modules must appear exactly once
        names = [m.name for m in result]
        assert sorted(names) == ["A", "B"]
        # A cycle warning should have been issued
        assert any("cycle" in str(warning.message).lower() for warning in w)

    def test_external_dependency_ignored(self):
        """Instances targeting modules outside the compilation unit are ignored."""
        a = _mod("A", targets=("ExternalIP",))
        b = _mod("B")

        result = topological_sort([a, b])
        names = [m.name for m in result]
        # Both should be present; external IP is not in the list so
        # A has no in-compile dependency and original order is preserved
        assert names == ["A", "B"]

    def test_empty_input(self):
        """Empty input returns empty list."""
        assert topological_sort([]) == []

    def test_single_module(self):
        """Single module with no dependencies passes through."""
        m = _mod("Lonely")
        assert topological_sort([m]) == [m]

    def test_diamond_dependency(self):
        """Diamond: D depends on B and C, both of which depend on A."""
        d = _mod("D", targets=("B", "C"))
        b = _mod("B", targets=("A",))
        c = _mod("C", targets=("A",))
        a = _mod("A")

        result = topological_sort([d, b, c, a])
        names = [m.name for m in result]
        assert names.index("A") < names.index("B")
        assert names.index("A") < names.index("C")
        assert names.index("B") < names.index("D")
        assert names.index("C") < names.index("D")

    def test_self_dependency_ignored(self):
        """A module listing itself as a target is not treated as a dependency."""
        a = _mod("A", targets=("A",))

        result = topological_sort([a])
        assert result == [a]
