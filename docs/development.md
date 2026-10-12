# C++ compiler development

The native compiler implements the Slip language in C++20. Its lexer, Pratt
parser, metaprogram expander, semantic analysis, interface resolution and SV
emitter run without Python. It links directly to slang for IP reflection,
SystemVerilog constant evaluation and whole-design elaboration.

The Python implementation lives in `reference/python/` as a migration oracle.
It has a separate package, dependencies, tests and `slip-reference` CLI;
the C++ build does not inspect or import it. The CLI keeps `build`, `check`, `-o`, `-ip`, `-f`, and `--strict`.
Native additions are stdin input (`-`), `build --stdout`, and
`--diagnostics=json`. Exit codes are 0 for success, 1 for compilation failure,
and 2 for invalid arguments. Diagnostics use stable codes such as `E_PARSE`,
`E_CONSTANT`, `E_CONNECTION`, `E_MULTIPLE_DRIVERS`, and `E_SV`.

## Build

Requirements: a C++20 compiler, CMake >= 3.24, PCRE2 8-bit development libraries,
and slang 10. If slang is not installed, CMake downloads the pinned upstream
commit `ace09c5d7c9f4e28eed654d2f353c6dc792ebf67` into the ignored build
directory. Upstream slang also needs fmt >= 12.1 and a Python interpreter to
generate its C++ headers during its build. The resulting executable does not
need Python or pyslang at runtime.

On Ubuntu, install `build-essential cmake git python3 libpcre2-dev` first.

```sh
cmake --preset release
cmake --build --preset release --parallel 2
ctest --preset release
build/release/slip build tests/fixtures/simple.slip -o build/rtl
build/release/slip check tests/fixtures/ip_top_fifo_user.slip -ip tests/fixtures/ip
```

An offline build can use an installed slang and fmt prefix:

```sh
cmake --preset release -DCMAKE_PREFIX_PATH=/path/to/dependencies -DSLIP_FETCH_SLANG=OFF
```

Alternatively, use `-DFETCHCONTENT_SOURCE_DIR_SLANG=/path/to/slang/source` with
an installed fmt package. Keep the slang and Slip debug/release configurations
compatible; their allocator layouts differ. CMake rejects a mismatched
single-configuration installed package.

```sh
cmake --preset sanitize
cmake --build --preset sanitize --parallel 2
ctest --preset sanitize
```

LeakSanitizer cannot inspect processes under some traced or restricted sandboxes.
In that environment, use `ASAN_OPTIONS=detect_leaks=0 ctest --preset sanitize`;
address and undefined-behavior checks remain enabled. CI uses the default
sanitizer settings.

## Architecture

- `include/slip/ast.hpp`: source locations and typed `std::variant` AST nodes;
  expression subtrees have immutable shared ownership and bounded depth.
- `include/slip/ir.hpp`: resolved module interfaces, storage, processes and instances.
- `include/slip/compiler.hpp`: reusable `compile` / `compile_file` API and options.
- `src/frontend.cpp`: lexer, Pratt parser, serializer, and expression traversal.
- `src/functions.cpp`: a typed interpreter for `defun` and regex replacements;
  no Python `eval`, global function registry, or shell execution.
- `src/pattern.cpp`: PCRE2 patterns with bounded match work and recursion.
- `src/slang_backend.cpp`: an owned source manager, retained IP syntax tree,
  per-compilation constant cache, and whole-design validation.
- `src/compiler.cpp`: ordered compilation passes, dependency sorting, instance
  inference, driver checks, combinational dependency analysis and SV emission.
- `src/main.cpp`: CLI and human-readable / JSON diagnostics.

Each compilation owns its state. There are no mutable global registries, so
independent compilations can run concurrently. Output ordering is deterministic.
All generated modules and IP pass elaboration before any output is published.
`--strict` rejects implicit declarations and width mismatches; the default emits
width warnings and annotates implicit / inferred declarations.

## Tests and repository layout

The default CMake/CTest build uses only C++ and CMake tests. Independent named
regressions cover AST precedence, widths and signedness, parameter scope,
overlapping drivers, diagnostic locations, integer boundaries, resource limits,
object ownership and concurrent compilations with different functions and IP.
CTest also covers all shared `.slip` fixtures and CLI behavior. With Verilator,
four simulations cover pipeline arithmetic, combinational logic, a state machine,
and arrays with different widths and depths. Their expected behavior is defined
in independent RTL or testbench models, without the Python implementation.
CI runs Release, ASan/UBSan, GCC coverage and Clang libFuzzer jobs.
See [testing and coverage](testing.md) for commands, report scope and fuzz replay.

```sh
ctest --preset release
cmake --install build/release --prefix "$PWD/build/install"
build/install/bin/slip check tests/fixtures/simple.slip
```

- `include/slip/`: public C++ AST, IR and compiler API.
- `src/`: C++ implementation and CLI.
- `tests/`: C++ API tests, CMake CLI/simulation tests and shared HDL fixtures.
- `reference/python/`: Python oracle, its own package and regression suite.
- `docs/`: current language specification and C++ user/developer documentation.

The C++ `slip::core` build target exposes the reusable compiler API.
Installation currently publishes the CLI executable. Python is needed only
when generating slang headers from source or running the reference suite.

For optional migration comparison, see [the Python reference](../reference/python/README.md):

```sh
uv sync --directory reference/python
uv run --directory reference/python pytest -q tests
SLIP_BIN="$PWD/build/release/slip" uv run --directory reference/python pytest -q migration
```

The migration suite extracts complete literal programs from the reference
Python tests and includes the shared behavioral source. Successful programs
compare generated SV syntax trees, ignoring trivia, redundant parentheses and
ordering of independent module declarations / ports. Rejected programs must
also fail in C++. Shared project fixtures are compared. The same independent
Verilator simulation is exercised through the reference test adapter.

One intentional semantic correction is covered separately: a runtime `for`
variable stays inside its procedural scope and is not exported as an implicit
module input. It is removed from the Python oracle's expected implicit interface
for that comparison; all other generated syntax is compared.

## Bounds and compatibility

Compilation defaults cap metaprogram iterations at 10,000 across a module,
expanded statements at 100,000, and include depth at 128. A repeated loop value
is diagnosed immediately. The API exposes these limits in `Options`. Expression
depth is capped at 256 and each source at 1,000,000 tokens. Regex matching and
defun evaluation have separate depth / work / string-size limits.

Metaprogram control results and defun integers must fit a signed 64-bit integer;
overflow is an error. Hardware literals and arithmetic retain their full SV
widths and four-state semantics. The native defun string interpreter operates
on bytes; Python Unicode case conversion and indexing are not reproduced.
Defun string methods support the documented helpers and diagnose unsupported
arities. PCRE2 covers the common Python
regex syntax used by Slip, including named groups and inline flags, but it is
not an implementation of every Python `re` extension. External SV interface
ports and type parameters are explicitly rejected rather than silently ignored.

This suite establishes compatibility for existing examples and test programs;
it is not a formal proof of equivalence for every possible input.
