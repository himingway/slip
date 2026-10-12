# Native compiler validation

The native tests run without Python. Python remains an optional compatibility
oracle; matching its output does not replace independent behavior checks.

## Regression tests

`tests/regression/` contains 70 individually named CTest cases:

| File | Independent expectations |
|---|---|
| `frontend.cpp` | AST structure for precedence, associativity, selects, casts and malformed expressions |
| `semantic.cpp` | Signed widths, caller parameter scope, frozen local parameters, overlapping drivers and feedback |
| `diagnostics.cpp` | Error codes, filenames, exact lines/columns and nested include context |
| `runtime.cpp` | Signed 64-bit arithmetic, resource boundaries, ownership and compilation isolation |

Runtime checks include valid and overflowing boundary arithmetic, division and
remainder, recursion and string expansion, cumulative metaprogram work, source
tokens, expression depth, include depth/cycles and regex match budgets. Ownership
checks retain AST and compilation results after their input buffers, options and
temporary IP files are destroyed. The concurrent test runs 12 threads, each
compiling five designs with different functions, widths and same-named IP modules.

```sh
cmake --preset release
cmake --build --preset release --parallel 2
ctest --preset release
ctest --preset release -R compiler.regression

cmake --preset sanitize
cmake --build --preset sanitize --parallel 2
ctest --preset sanitize
```

With Verilator installed, the release/sanitize suite has 96 CTest entries.
ASan/UBSan check address safety and undefined behavior; they do not detect data
races. Concurrent isolation assertions are not a replacement for ThreadSanitizer.
In sandboxes where LeakSanitizer cannot inspect processes, use
`ASAN_OPTIONS=detect_leaks=0`; this leaves ASan and UBSan enabled.

## RTL behavior

Verilator builds the generated RTL and testbench separately for each design.
Compilation or any `$fatal` fails the test; a success marker is required.

| Design | Independent model and stimulus |
|---|---|
| Pipeline | Reference RTL; 128 cycles with resets and arithmetic width checks |
| Combinational | Integer arithmetic/parity model; 1,024 samples including signed shifts, carry and mux choices |
| State machine | Deadline model instead of a countdown; 256 cycles, async resets and every state visited |
| Parameterized arrays | Circular history instead of a shift register; 256 cycles each for width/depth `(3,1)`, `(8,3)`, `(16,5)`, stalls and resets |

```sh
ctest --preset release -L behavior
```

## GCC coverage

```sh
cmake --preset coverage
cmake --build --preset coverage --parallel 2
ctest --preset coverage --parallel 2
cmake --build --preset coverage --target coverage_report
```

The coverage preset also runs deterministic mutation fuzzing (97 CTest entries
with Verilator). `build/coverage/coverage/report.md` gives per-file and total line
and branch coverage; `summary.json` provides counts for automation. Compressed
gcov JSON contains individual uncovered lines and branches. Only the six
production `src/*.cpp` files are counted. Headers, tests, standard library and
slang are excluded. Lines are deduplicated across template instantiations;
branch totals exclude gcov's exception-only arcs but include other
compiler-generated arcs. These numbers measure executed code, not correctness
or equivalence. No arbitrary percentage is treated as proof of completeness.

The initial native-only measurement on 2026-10-12 with GCC 16.2 and all 97
coverage-preset tests passing was **1,552/1,776 lines (87.38%)** and
**3,870/5,996 branches (64.54%)**. The largest line-coverage gaps were
`functions.cpp` (68.58%) and `slang_backend.cpp` (75.32%), making string-method
variants and external SV interface diagnostics useful next targets. This is a
baseline, not a gate: compiler versions and generated branch arcs affect counts.

For a fresh measurement, remove previous `.gcda` files before running tests:

```sh
find build/coverage -name '*.gcda' -delete
ctest --preset coverage --parallel 2
cmake --build --preset coverage --target coverage_report
```

The CI coverage job uploads the Markdown/JSON reports, raw gcov data and CTest
log, and includes the report in the job summary. Use a gcov version matching GCC.
For installed offline dependencies, add
`-DCMAKE_PREFIX_PATH=/path/to/dependencies -DSLIP_FETCH_SLANG=OFF` when configuring.

## Mutation fuzzing and libFuzzer

```sh
cmake --preset fuzz
cmake --build --preset fuzz --parallel 2
ctest --preset fuzz -R compiler.fuzz
```

The portable runner replays eight corpus seeds and performs 3,000 byte mutations
with a fixed RNG seed. It shares a target with libFuzzer, exercises lexer/parser
and compilation, checks expression serialization round trips, and generates six
families of valid programs with variable widths and values. Valid programs must
compile deterministically; expected rejection of arbitrary input catches only
`slip::Error`. Unexpected exceptions, crashes and sanitizer findings fail.
Fuzz input is capped at 8 KiB, metaprogram work is bounded and filesystem includes
are never followed. The runner writes `fuzz-last-input` before each invocation
and removes it only on success. Change `--seed` or `--runs` for longer sweeps:

```sh
mkdir -p build/fuzz/sweep
cd build/fuzz/sweep
../slip_mutation_fuzz --corpus ../../../tests/fuzz/corpus --runs 20000 --seed 123
```

Portable mutations do not use coverage feedback. For coverage-guided fuzzing,
use Clang in a fresh build directory and enable the optional libFuzzer target:

```sh
cmake --preset fuzz -DCMAKE_CXX_COMPILER=clang++ -DSLIP_LIBFUZZER=ON
cmake --build --preset fuzz --parallel 2
mkdir -p build/fuzz/corpus build/fuzz/artifacts
cp tests/fuzz/corpus/* build/fuzz/corpus/
build/fuzz/slip_fuzzer build/fuzz/corpus -dict=tests/fuzz/slip.dict \
  -max_len=8192 -max_total_time=60 -timeout=10 -rss_limit_mb=2048 \
  -artifact_prefix=build/fuzz/artifacts/
```

Do not switch compilers inside an existing GCC build directory: remove it or set
`-B build/fuzz-clang` and adjust subsequent paths. CI runs this Clang configuration
with ASan/UBSan and uploads the evolved corpus, crash artifacts and logs.
Replay a libFuzzer artifact directly with `slip_fuzzer path/to/artifact`. To replay
the portable runner's last input, put it alone in a temporary corpus directory
and pass `--corpus /path/to/repro --runs 0`; retain any confirmed regression as
a named C++ test or committed corpus seed.

### Packaged runtime allocator conflicts

The locally installed Clang 23.1.1 engine reproduced an ASan allocator mismatch
even in a target containing only nothrow `operator new` followed by `operator
delete`. Its embedded C++ runtime exports weak allocation functions that conflict
with ASan; changing link order alone also caused an embedded-runtime assertion.
This is separate from Slip compilation. A private ELF engine copy with those
functions made local keeps the engine's allocator internal and leaves ASan's
global interceptors and mismatch checking enabled:

```sh
cmake -DENGINE="$(clang++ -print-file-name=libclang_rt.fuzzer-x86_64.a)" \
  -DOUTPUT="$PWD/build/fuzz-clang/runtime/libclang_rt.fuzzer-local.a" \
  -P tests/fuzz/prepare_runtime.cmake
cmake --preset fuzz -B build/fuzz-clang -DCMAKE_CXX_COMPILER=clang++ \
  -DSLIP_LIBFUZZER=ON \
  -DSLIP_LIBFUZZER_RUNTIME="$PWD/build/fuzz-clang/runtime/libclang_rt.fuzzer-local.a"
cmake --build build/fuzz-clang --parallel 2
```

This optional workaround uses `objcopy` and never modifies the installed archive.
Use it only for a confirmed runtime conflict; compatible toolchains keep the
normal libFuzzer configuration. `SLIP_LIBFUZZER_RUNTIME` can also select a
compatible rebuilt engine archive. Set
`UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1` when running sanitizer binaries
so findings fail immediately; CI sets this for its sanitizer and fuzz jobs.

Local validation on 2026-10-12 with Clang 23.1.1 and the private engine copy:
all 97 CTest entries passed, followed by 16,461 coverage-guided libFuzzer
executions in 61 seconds with RNG seed 42, the committed dictionary/corpus and
ASan/UBSan enabled. No target crash or sanitizer finding occurred. Leak detection
was disabled for the sandbox; allocation/deallocation mismatch checks remained
enabled. The evolved corpus and log are in `build/fuzz-clang/`.
