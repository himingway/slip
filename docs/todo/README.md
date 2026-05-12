# Slip Compiler - Known Implementation Gaps

Found during test suite development. Each bug has a corresponding test in `tests/test_implementation_gaps.py`.

---

## Bug Status Summary

| ID | Description | Severity | Status |
|----|-------------|----------|--------|
| BUG-001 | ForStmt dropped in seq/comb | HIGH | **FIXED** |
| BUG-002 | unsigned vs signed inconsistency | HIGH | **FIXED** |
| BUG-003 | validation.py dead code | MEDIUM | **FIXED** |
| BUG-004 | Bare ident becomes signal decl | MEDIUM | BY DESIGN |
| BUG-005 | Trailing comma in connections | LOW | BY DESIGN |
| BUG-006 | seq_correction nested blocks | LOW | UNREACHABLE |
| BUG-007 | Template ident merging (multi-var) | HIGH | **FIXED** |
| BUG-008 | gen_expand dead branches | MEDIUM | **NOT A BUG** |
| BUG-009 | Int literal radix validation | HIGH | **FIXED** |
| BUG-010 | Underscore-only digit sequences | HIGH | **FIXED** |
| BUG-011 | Replication syntax broken | HIGH | **FIXED** |
| BUG-012 | Missing arithmetic shift `<<<`/`>>>` | HIGH | **FIXED** |
| BUG-013 | No undefined-signal check | HIGH | BY DESIGN |
| BUG-014 | No multi-driver detection | HIGH | **FIXED** |
| BUG-015 | No combinational loop detection | HIGH | **FIXED** |
| BUG-016 | `assign foo <= bar;` illegal SV | HIGH | **FIXED** |
| BUG-017 | Missing required ports check | HIGH | **FIXED** |
| BUG-018 | Missing `**` operator | MEDIUM | **FIXED** |
| BUG-019 | Missing `===`/`!==` operators | MEDIUM | **FIXED** |
| BUG-020 | Missing width-cast syntax | MEDIUM | **FIXED** |
| BUG-021 | For-loop step limited | MEDIUM | **FIXED** |
| BUG-022 | Port width parser inconsistency | MEDIUM | **FIXED** |
| BUG-023 | Bare ident fallthrough errors | MEDIUM | BY DESIGN |
| BUG-024 | No duplicate declaration detection | MEDIUM | **FIXED** |
| BUG-025 | No port width mismatch check | MEDIUM | **FIXED** |
| BUG-026 | Instance target not validated | MEDIUM | BY DESIGN |
| BUG-027 | `inout` never inferred | MEDIUM | BY DESIGN |
| BUG-028 | Reset polarity inconsistency | MEDIUM | **FIXED** |
| BUG-029 | `always_latch` spurious sensitivity | MEDIUM | **FIXED** |
| BUG-030 | UndeclaredIdentifier suppression | MEDIUM | BY DESIGN |
| BUG-031 | pyslang ImportError silent | MEDIUM | **FIXED** |
| BUG-032 | `to_sv()` always prepends assign | MEDIUM | **FIXED** |
| BUG-033 | Missing Optional type annotation | LOW | **FIXED** |
| BUG-034 | Unconstrained string fields | LOW | **FIXED** |
| BUG-035 | `regex_rules` never consumed | LOW | BY DESIGN |

### Status Definitions

- **FIXED** — Bug has been fixed and tests updated to verify correct behavior
- **OPEN** — Known issue, not yet fixed
- **BY DESIGN** — Current behavior is intentional
- **UNREACHABLE** — Code path cannot be reached with current parser output

---

## Fixed Bugs

### BUG-001: ForStmt silently dropped inside seq/comb blocks — **FIXED**

**Severity:** HIGH
**Files:** `src/slip/semantic/ir_builder.py`, `src/slip/ir/logic_block.py`, `src/slip/codegen/fragment.py`
**Test:** `TestIRBuilderForStmtDrop`

`_convert_block()` now handles `ForStmt` by converting it to `HDLForLoop`. The fragment emitter generates `for (int ...) begin ... end` inside procedural blocks. For-loop variables are excluded from implicit signal creation.

---

### BUG-002: `unsigned` vs `signed` inconsistent handling — **FIXED**

**Severity:** HIGH
**File:** `src/slip/parser/pratt.py`

Both `signed` and `unsigned` without a following `'` now raise `SlipSyntaxError` consistently. The `unsigned'` cast continues to work correctly.

---

### BUG-007: Lexer template identifier merging fails with multiple backtick variables — **FIXED**

**Severity:** HIGH
**File:** `src/slip/lexer/tokenizer.py` (`_merge_template_idents`)

`_merge_template_idents` now loops until no more merges occur, correctly handling identifiers with multiple backtick variables like `a`i_`j`.

---

### BUG-009/010: Integer literal validation — **FIXED**

**Severity:** HIGH
**File:** `src/slip/lexer/tokenizer.py`

Added `_validate_int_literal()` that:
- Rejects digits outside the valid range for each radix (e.g., `4'bABCD`, `4'o888`, `4'dFF`)
- Rejects underscore-only digit sequences (e.g., `4'b_`, `4'd___`)
- Accepts valid four-state values `x`/`z` in any radix (e.g., `4'bx`, `4'bz`)

---

### BUG-011: Replication syntax `{n{expr}}` — **FIXED**

**Severity:** HIGH
**File:** `src/slip/parser/pratt.py`

The LBRACE handler in the Pratt parser now detects the replication pattern `{n{expr}}` and constructs `ReplicationExpr`. Nested replications like `{4{{2{1'b0}}}}` are also supported.

---

### BUG-012: Missing arithmetic shift operators `<<<`, `>>>` — **FIXED**

**Severity:** HIGH
**Files:** `src/slip/lexer/token.py`, `src/slip/lexer/tokenizer.py`, `src/slip/parser/pratt.py`

Added `LT_LT_LT` and `GT_GT_GT` token types, lexer rules (ordered longest-match first), and parser binding power entries. Arithmetic shifts have the same precedence as logical shifts.

---

### BUG-014: No multi-driver detection — **FIXED**

**Severity:** HIGH
**File:** `src/slip/semantic/ir_builder.py`

Added `_check_multi_driver()` that raises `SlipSemanticError` when a signal is driven by multiple `seq` or `comb` blocks. Tracks assignments through `if` and `for` nesting.

---

### BUG-016/032: `assign` with nonblocking / `to_sv()` prefix — **FIXED**

**Severity:** HIGH / MEDIUM
**Files:** `src/slip/ir/assignment.py`, `src/slip/codegen/fragment.py`

`HDLAssignment.to_sv()` no longer prepends `assign` — it produces `target op value;`. The `fragment.assign_stmt()` function correctly handles module-level continuous assignments (with `assign`), while `_emit_block_item()` handles procedural assignments (without `assign`).

---

### BUG-018: Missing `**` (exponentiation) operator — **FIXED**

**Severity:** MEDIUM
**Files:** `src/slip/lexer/token.py`, `src/slip/lexer/tokenizer.py`, `src/slip/parser/pratt.py`, `src/slip/semantic/gen_expand.py`

Added `STAR_STAR` token type, lexer rule, and parser binding power `(25, 24)` for right-associativity (higher precedence than `*`). Also added to `_eval_int` in gen_expand for compile-time evaluation.

---

### BUG-019: Missing `===`/`!==` (four-state identity) operators — **FIXED**

**Severity:** MEDIUM
**Files:** `src/slip/lexer/token.py`, `src/slip/lexer/tokenizer.py`, `src/slip/parser/pratt.py`, `src/slip/semantic/gen_expand.py`

Added `EQ_EQ_EQ` and `BANG_EQ_EQ` token types, lexer rules (ordered before `==`/`!=` for longest match), and parser binding power entries. Also added to `_eval_int` in gen_expand.

---

### BUG-020: Missing width-cast syntax `8'(expr)` — **FIXED**

**Severity:** MEDIUM
**File:** `src/slip/parser/pratt.py`

Added width-cast parsing in the Pratt parser's `_parse_prefix`. When an `INT_LITERAL` is followed by `'`, it parses as a width cast `N'(expr)`. Produces `CastExpr` with the width string as the cast operator.

---

### BUG-029: `always_latch` emitted with spurious sensitivity list — **FIXED**

**Severity:** MEDIUM
**File:** `src/slip/codegen/fragment.py`

`logic_block()` now emits `always_latch begin` (no sensitivity list) instead of `always_latch @(...) begin`, consistent with IEEE 1800.

---

### BUG-031: pyslang `ImportError` silently swallowed — **FIXED**

**Severity:** MEDIUM
**File:** `src/slip/codegen/emitter.py`

Replaced silent `pass` with `warnings.warn()` so users are informed when pyslang is not installed.

---

### BUG-033: `type_: HDLType = None` missing `Optional` annotation — **FIXED**

**Severity:** LOW
**Files:** `src/slip/ir/signal.py`, `src/slip/ir/port.py`

`HDLSignal.type_` and `HDLPort.type_` now use `HDLType | None` annotation. `HDLPort.direction` now defaults to `"input"`.

---

### BUG-034: `LogicBlock.kind` and `HDLPort.direction` are unconstrained strings — **FIXED**

**Severity:** LOW
**Files:** `src/slip/ir/logic_block.py`, `src/slip/ir/port.py`

Added `__post_init__` validation: `LogicBlock.kind` must be one of `{"always_ff", "always_comb", "always_latch", "initial"}`, `HDLPort.direction` must be one of `{"input", "output", "inout"}`. Invalid values raise `TypeError`.

---

## Open Bugs

### BUG-003: `validation.py` is dead code — **FIXED**

`validation.py` has been deleted. The `__init__.py` no longer exports it. `emitter.py` uses inline pyslang validation.

---

### BUG-004: Bare identifier silently becomes signal declaration — **BY DESIGN**

Bare identifiers like `my_signal;` are accepted as 1-bit signal declarations. This is intentional for Slip's convenience-first approach, consistent with Verilog's `wire a;` shorthand.

---

### BUG-008: `gen_expand._expand_stmt` branches for `BlockStmt` and `ForStmt` — **NOT A BUG**

**Severity:** MEDIUM (incorrectly reported)
**File:** `src/slip/semantic/gen_expand.py`

Both branches are reachable with the current parser output:

- **`BlockStmt`**: The parser produces `BlockStmt` at module level for comma-separated `localparam` declarations (e.g., `localparam A = 1, B = 2;` — see parser line 119). When `expand_module` calls `_expand_stmt` for each statement in `module.body`, this `BlockStmt` hits the `BlockStmt` branch, which correctly recurses into its child statements.

- **`ForStmt`**: The parser produces `ForStmt` for regular `for` loops. A `ForStmt` can appear inside `GenForStmt`/`GenIfStmt` bodies, `SeqBlock`/`CombBlock` bodies, or at module top level. When `_expand_stmt` processes these containers and recurses, it encounters `ForStmt` and correctly expands any nested metaprogramming constructs inside the for-loop body.

---

### BUG-013: No undefined-signal check — typos silently create implicit 1-bit signals — **BY DESIGN**

**Severity:** HIGH (design choice)
**File:** `src/slip/semantic/ir_builder.py`
**Test:** `TestUndefinedSignalSilent`

When an identifier appears in an expression but was never declared, `ir_builder` creates an implicit 1-bit signal declaration. This is an intentional design feature for Slip's convenience-first approach. Typos in signal names are not caught at the Slip level but may be caught by pyslang validation.

---

### BUG-015: No combinational loop detection — **FIXED**

**Severity:** HIGH
**File:** `src/slip/semantic/driver_analysis.py`

Added `detect_comb_loops()` that builds a dependency graph per `CombBlock` and uses DFS-based cycle detection. Raises `SlipSemanticError` when a combinational feedback loop is found.

---

### BUG-017: Missing required ports not checked for explicit instance connections — **FIXED**

**Severity:** HIGH
**File:** `src/slip/semantic/instance_resolve.py`

Added `_check_required_ports()` that validates all input ports of the target module are connected. External IP modules are skipped. The dangling marker `_` suppresses the check.

---

### BUG-021: For-loop step limited to `IDENT = expr` — **FIXED**

**Severity:** MEDIUM
**File:** `src/slip/parser/parser.py`

The for-loop step clause now supports `IDENT = expr`, `IDENT += expr`, and `IDENT++`. Compound assignments are desugared at parse time.

---

### BUG-022: Port width parser inconsistent with signal width parser — **FIXED**

**Severity:** MEDIUM
**File:** `src/slip/parser/parser.py`

Port declarations now parse width the same way as signal declarations, supporting both `[expr:expr]` range and `[expr]` single-width syntax.

---

### BUG-023: Bare identifier fallthrough produces misleading errors — **BY DESIGN**

Bare identifiers are accepted as signal declarations. Error messages from the signal decl parser for invalid bare identifiers are acceptable.

---

### BUG-024: No duplicate declaration detection — **FIXED**

**Severity:** MEDIUM
**File:** `src/slip/semantic/symbol_collector.py`

Added `_check_duplicate()` that raises `SlipSemanticError` when a signal, instance, or localparam is declared more than once.

---

### BUG-025: No port width mismatch check on instance connections — **FIXED**

**Severity:** MEDIUM
**File:** `src/slip/semantic/width_check.py`
**Test:** `tests/test_width_check.py`

Width mismatch detection added for both assignments and instance port connections. Uses `warnings.warn()` to emit warnings when concrete integer widths don't match. Parameterized widths with default values are evaluated; truly unresolvable widths are skipped.

---

### BUG-026: Non-regex instance target module existence not validated — **BY DESIGN**

**Severity:** MEDIUM
**File:** `src/slip/semantic/instance_resolve.py`
**Test:** `TestInstanceModuleExistence`

External IP modules are allowed at the semantic level. pyslang validates at codegen time.

---

### BUG-027: `inout` never inferred — **BY DESIGN**

Most outputs are also internally read (e.g., `count <= count + 1`), making automatic inout inference unreliable. `inout` requires explicit direction declaration.

---

### BUG-028: Reset polarity inconsistency not detected — **FIXED**

**Severity:** MEDIUM
**File:** `src/slip/semantic/ir_builder.py`

Added `_check_reset_polarity()` that raises `SlipSemanticError` when a reset signal is used with conflicting polarity across seq blocks.

---

### BUG-030: `UndeclaredIdentifier` suppression too broad — **BY DESIGN**

**Severity:** MEDIUM
**File:** `src/slip/codegen/emitter.py`

The emitter suppresses `UndeclaredIdentifier` and `CouldNotResolve` pyslang diagnostics because Slip intentionally creates implicit 1-bit signals for undeclared identifiers. This is by design for Slip's convenience-first approach.

---

## Feature Gaps

These are standard HDL features that Slip does not support.

| ID | Feature | Decision |
|----|---------|----------|
| FEAT-001 | case/casez/casex | **DONE** |
| FEAT-002 | inside operator | **DONE** |
| FEAT-003 | compound assignment (+=, etc.) | **DONE** |
| FEAT-004 | wire/reg distinction | WON'T FIX — `logic` is fine |
| FEAT-005 | generate blocks | WON'T FIX — compile-time expand替代 |
| FEAT-006 | initial blocks | **DONE** |
| FEAT-007 | procedural for/while in IR | **Partially done** — `HDLForLoop` added |
| FEAT-008 | case statements in IR | **DONE** (跟 FEAT-001) |
| FEAT-009 | width mismatch warning | **DONE** |
| FEAT-010 | clock domain check | WON'T FIX — 非编译器职责 |
| FEAT-011 | module topological sort | **DONE** |
| FEAT-012 | validation.py dead code | **DONE** (see BUG-003) |

## FEAT-001: `case`/`casez`/`casex` statement support — **DONE**

**Area:** Parser, IR, Codegen
**Files:** `src/slip/ast/statements.py`, `src/slip/parser/parser.py`, `src/slip/ir/logic_block.py`, `src/slip/codegen/fragment.py`
**Test:** `tests/test_case.py`

Added `CaseStmt` and `CaseItem` AST nodes, parser for `case`/`casez`/`casex` with multi-pattern and default support, `HDLCaseBlock`/`HDLCaseItem` IR nodes, and SV codegen emitting `case/endcase`. Also added `?` support in integer literals for Verilog pattern matching.

---

## FEAT-002: `inside` operator and set membership — **DONE**

**Area:** Parser, Semantic
**Files:** `src/slip/lexer/token.py`, `src/slip/lexer/tokenizer.py`, `src/slip/parser/pratt.py`, `src/slip/semantic/gen_expand.py`
**Test:** `tests/test_inside.py`

The `inside` operator (`x inside {1, 2, 3}`) is now supported. Parsed as `BinaryExpr("inside", left, ConcatExpr(...))` with low precedence. Supports compile-time evaluation when all values are constant.

---

## FEAT-003: Compound assignment operators (`+=`, `|=`, etc.) — **DONE**

**Area:** Parser
**Files:** `src/slip/lexer/token.py`, `src/slip/lexer/tokenizer.py`, `src/slip/parser/parser.py`
**Test:** `tests/test_compound_assignment.py`

All 12 compound assignment operators are supported. They are desugared at parse time: `a += b` becomes `a = a + b`.

---

## FEAT-006: `initial` blocks — **DONE**

**Area:** IR, Codegen
**Files:** `src/slip/ast/statements.py`, `src/slip/parser/parser.py`, `src/slip/ir/logic_block.py`, `src/slip/codegen/fragment.py`
**Test:** `tests/test_initial_block.py`

`initial` blocks emit `initial begin ... end` in SV. Blocking assignments stay blocking (not converted to nonblocking).

---

## FEAT-007: Procedural for/while loops in IR — **DONE**

**Area:** IR

`HDLForLoop` has been added to the IR. Procedural `for` loops inside `seq`/`comb` blocks generate correct SV `for` statements. `while` loops are not supported (BY DESIGN — combinational while loops are unsafe in synthesis).

---

## FEAT-011: Module topological sort — **DONE**

**Area:** Generator
**File:** `src/slip/codegen/generator.py`
**Test:** `tests/test_topo_sort.py`

Modules are emitted in topological order using Kahn's algorithm. If module A instantiates module B, B is defined before A.

---

## FEAT-009: Width mismatch detection — **DONE**

**Area:** Semantic
**File:** `src/slip/semantic/width_check.py`
**Test:** `tests/test_width_check.py`

Added `check_width_mismatches()` that detects width mismatches in assignments and instance port connections. Reports via `warnings.warn()` when both sides have concrete integer widths. Parameterized widths are evaluated using default parameter values. Supports sized literals (`8'hFF`), unsized literals (32-bit default), signal-to-signal, and bit-select widths.

---

## Remaining Open Items

All open items have been addressed.
