# Python reference implementation

The production compiler is the C++20 project at the repository root. This
directory preserves the Python implementation as an executable specification
and regression oracle. It is not required to build, install or run the C++
compiler. Its historical architecture and issue log live in `docs/`.

Requires Python >= 3.10. From the repository root:

```sh
uv sync --directory reference/python
uv run --directory reference/python slip-reference check ../../tests/fixtures/simple.slip
uv run --directory reference/python pytest -q tests
SLIP_BIN="$PWD/build/release/slip" uv run --directory reference/python pytest -q migration
```

Without uv, install with `python -m pip install -e reference/python pytest`, then
run `python -m pytest -q reference/python/tests reference/python/migration`.
The package exposes `slip-reference`, leaving `slip` for the C++ compiler.
The Python import package remains `slip` so existing reference tests continue
to work. Shared HDL fixtures and the independent simulation sources live in
the root `tests/` directory.

The migration suite compares generated SV syntax trees and rejected programs.
It uses `SLIP_BIN` or defaults to `build/release/slip`. Verilator is needed for
the behavioral comparison. See [C++ development](../../docs/development.md)
for the intentional compatibility boundaries.
