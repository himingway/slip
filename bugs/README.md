# Slip Compiler - Known Implementation Gaps

Found during test suite development. Each bug has a corresponding test in `tests/test_implementation_gaps.py` that documents the current (broken) behavior.

---

## BUG-001: ForStmt silently dropped inside seq/comb blocks

**Severity:** HIGH
**File:** `src/slip/semantic/ir_builder.py` line 219-233
**Test:** `TestIRBuilderForStmtDrop`

### Description

`_convert_block()` only handles `AssignStmt` and `IfStmt`. All other statement types — including `ForStmt` — are silently ignored with no error or warning.

### Reproduction

```slip
module m (clk, rst_n) {
    logic [7:0] data;
    seq (clk, neg: rst_n) {
        for (i = 0; i < 4; i = i + 1) { data = i; }
    }
}
```

### Expected

`always_ff` block should contain the loop body assignments.

### Actual

`always_ff` block is empty. The for-loop body is completely lost.

### Impact

Any `for` loop inside a `seq` or `comb` block is silently discarded. This includes:
- Top-level for loops in seq/comb bodies
- For loops nested inside if statements within seq/comb bodies

### Fix

Add `ForStmt` handling to `_convert_block()`:
```python
elif isinstance(stmt, ForStmt):
    # Generate SV for-loop or unroll
```

---

## BUG-002: `unsigned` vs `signed` inconsistent handling in expression parser

**Severity:** HIGH
**File:** `src/slip/parser/pratt.py` line 207-236
**Test:** `TestUnsignedSignedInconsistency`

### Description

In the Pratt expression parser, `signed` without a following `'` raises `SlipSyntaxError`, but `unsigned` without `'` silently falls through and is consumed as an ordinary identifier.

### Reproduction

```slip
module m (y) { assign y = signed(1); }   // → SlipSyntaxError (correct)
module m (y) { assign y = unsigned(1); } // → parser accepts, pyslang rejects later
```

### Root Cause

`signed` has `TokenType.SIGNED` (a dedicated token type), so it only matches the cast branch. When no tick follows, it falls through to the error at line 253.

`unsigned` has `TokenType.IDENT` with value `"unsigned"`. When no tick follows, it falls through to the IDENT handler at line 234 and becomes a variable name.

### Fix

Either:
1. Add `unsigned` as a reserved keyword with its own `TokenType`, or
2. In the IDENT branch, check if value is `"unsigned"` and raise an error when not followed by a tick.

---

## BUG-003: `validation.py` is dead code

**Severity:** MEDIUM
**File:** `src/slip/slang_integration/validation.py`
**Test:** `TestValidationDeadCode`

### Description

`slang_integration.validation.validate_sv` is exported via `__init__.py` but never called by any production code. `emitter.py` has its own inline pyslang validation (lines 55-77) with different behavior:

| Aspect | `validation.py` | `emitter.py` (inline) |
|--------|-----------------|----------------------|
| Returns | `list[SVDiagnostic]` | raises `SlipCodegenError` |
| Filters | all diagnostics | errors only, filtered by `_is_relevant_diagnostic` |
| Reusable | yes | no (inline in emit) |

### Fix

Either:
1. Delete `validation.py` and use emitter's inline logic, or
2. Refactor emitter to call `validate_sv` and unify the validation paths.

---

## BUG-004: Bare identifier silently becomes signal declaration

**Severity:** MEDIUM
**File:** `src/slip/parser/parser.py` line 187-188
**Test:** `TestBareIdentBecomesSignalDecl`

### Description

`_parse_statement` dispatches any `IDENT` token that doesn't match instance or assignment patterns to `_parse_signal_decl`. A bare identifier like `foo;` is silently accepted as a signal declaration without requiring the `logic` keyword.

### Reproduction

```slip
module m (y) { my_signal; assign y = 1; }
```

### Expected

Parser should require `logic` keyword for signal declarations, or at minimum warn.

### Actual

`my_signal` is silently accepted as a signal declaration.

### Impact

Typos or incorrect syntax may be silently accepted. For example, a misspelled keyword like `asign` would be treated as a signal name instead of raising an error.

### Fix

Require explicit `logic` keyword for signal declarations, or add a warning for bare identifier fallback.

---

## BUG-005: Trailing comma silently accepted in connection lists

**Severity:** LOW
**File:** `src/slip/parser/parser.py` line 436-439
**Test:** `TestTrailingCommaInConnections`

### Description

Parser silently accepts trailing commas in instance connection lists.

### Reproduction

```slip
child u1 { .a(x), .b(y), };  // trailing comma after .b(y)
```

### Impact

Low — this is common in many languages and may be intentional for convenience. However, it's inconsistent if other comma-separated lists don't allow trailing commas.

---

## BUG-006: `seq_correction` doesn't handle nested SeqBlock/CombBlock

**Severity:** LOW
**File:** `src/slip/semantic/seq_correction.py` line 54-69
**Test:** (no dedicated test — currently unreachable)

### Description

`_correct_assign_in_stmt` handles `AssignStmt`, `IfStmt`, and `ForStmt`, but silently passes through `SeqBlock`, `CombBlock`, and other statement types. If a `SeqBlock` or `CombBlock` appears nested inside a seq body, its inner blocking assignments would not be corrected to nonblocking.

### Impact

Currently unreachable because the parser doesn't produce nested SeqBlock/CombBlock. But there's no defensive check — future parser changes could introduce this path silently.

---

## BUG-007: Lexer template identifier merging fails with multiple backtick variables

**Severity:** HIGH
**File:** `src/slip/lexer/tokenizer.py` line 149-166 (`_merge_template_idents`)
**Test:** `TestTemplateIdentifierMerging`

### Description

`_merge_template_idents` performs a single left-to-right pass, merging `IDENT + TICK_IDENT` pairs. When an identifier contains multiple backtick variables (e.g., `a`i_`j`), only the first pair is merged. The second `TICK_IDENT` remains as a separate token, causing a parse error.

### Reproduction

```slip
module m () {
    `for (`i = 0; `i < 2; `i = `i + 1) {
        `for (`j = 0; `j < 2; `j = `j + 1) {
            assign a`i_`j = `i + `j;  // ← parse error here
        }
    }
}
```

### Token Trace

```
Source: a`i_`j

Raw tokens:       IDENT(a), BACKTICK, IDENT(i_), BACKTICK, IDENT(j)
After tick merge: IDENT(a), TICK_IDENT(`i_), TICK_IDENT(`j)
After template:   IDENT(a`i_), TICK_IDENT(`j)  ← second merge missed!
```

The merge loop processes `i=0`: merges `IDENT(a)` + `TICK_IDENT(`i_)` → `IDENT(a`i_)`, advances `i` by 2. Then at `i=2` (the old position), the token is `TICK_IDENT(`j)` which is not preceded by an IDENT, so it's left unmerged.

### Expected

`a`i_`j` should tokenize as a single `IDENT` token: `a`i_`j`. The `gen_expand._sub_name` function already handles multiple substitutions correctly (it calls `.replace()` iteratively), so the only issue is in the lexer.

### Affected Patterns

| Pattern | Tokens Produced | Expected |
|---------|----------------|----------|
| `a`i_`j` | `IDENT(a`i_)` + `TICK_IDENT(`j)` | `IDENT(a`i_`j)` |
| `data`i`j` | `IDENT(data`i)` + `TICK_IDENT(`j)` | `IDENT(data`i`j)` |
| `` `i`j `` | `TICK_IDENT(`i)` + `TICK_IDENT(`j)` | `TICK_IDENT(`i`j)` |

### Fix

Change `_merge_template_idents` to loop until no more merges occur, or process the merged result in the same pass:

```python
def _merge_template_idents(tokens: list[Token]) -> list[Token]:
    changed = True
    while changed:
        changed = False
        result: list[Token] = []
        i = 0
        while i < len(tokens):
            if (
                i + 1 < len(tokens)
                and tokens[i].type == TokenType.IDENT
                and tokens[i + 1].type == TokenType.TICK_IDENT
            ):
                result.append(Token(TokenType.IDENT,
                                    tokens[i].value + tokens[i + 1].value,
                                    tokens[i].line, tokens[i].col))
                i += 2
                changed = True
            else:
                result.append(tokens[i])
                i += 1
        tokens = result
    return tokens
```

---

## BUG-008: `gen_expand._expand_stmt` doesn't handle `BlockStmt` and `ForStmt`

**Severity:** MEDIUM
**File:** `src/slip/semantic/gen_expand.py` line 306-309, 335-338
**Test:** (no dedicated test — code paths exist but are unreachable in current pipeline)

### Description

`_expand_stmt` handles `GenForStmt`, `GenIfStmt`, `AssignStmt`, `SignalDecl`, `InstanceStmt`, `SeqBlock`, `CombBlock`, `IfStmt`, and `LocalParamDecl`. But it has code for `BlockStmt` (lines 306-309) and `ForStmt` (lines 335-338) that are never reached because:

1. `BlockStmt` doesn't appear at the module body level — it's always inside `SeqBlock.body`, `CombBlock.body`, or `IfStmt.then_body/else_body`, which are handled by the `SeqBlock`/`CombBlock`/`IfStmt` branches.
2. `ForStmt` at the module body level is handled by the `build()` function in `ir_builder.py`, not by `gen_expand`. The `ForStmt` branch in `_expand_stmt` (lines 335-338) can only be reached if a `ForStmt` appears inside a `BlockStmt` that's being expanded, but `BlockStmt` itself is unreachable (see point 1).

### Impact

Dead code — the branches exist but can't be reached with the current parser output. If the language grammar changes to allow these constructs at different nesting levels, the code would silently not expand metaprogramming constructs inside them.

### Fix

Either remove the dead branches or add a defensive error:
```python
if isinstance(stmt, BlockStmt):
    raise SlipSemanticError(stmt.loc, "unexpected BlockStmt in _expand_stmt")
if isinstance(stmt, ForStmt):
    raise SlipSemanticError(stmt.loc, "unexpected ForStmt in _expand_stmt")
```

---

## BUG-009: Integer literal regex accepts invalid digits per radix

**Severity:** HIGH
**File:** `src/slip/lexer/tokenizer.py` line 70
**Test:** `TestLexerIntegerLiteralValidation`

### Description

The regex for Verilog-style integer literals (`4'b1010`) accepts any hex digit regardless of radix. Binary literals accept `A-F`, octal accept `8-9`, decimal accept `A-F`.

### Reproduction

```slip
module m (y) { assign y = 4'bABCD; }  // should be error: hex digits in binary
module m (y) { assign y = 4'o888; }   // should be error: 8/9 in octal
module m (y) { assign y = 4'dFF; }    // should be error: hex in decimal
```

### Expected

Lexer should reject digits outside the valid range for each radix.

### Actual

All variants lex successfully. Invalid digits are silently accepted.

---

## BUG-010: Underscore-only digit sequences accepted

**Severity:** HIGH
**File:** `src/slip/lexer/tokenizer.py` line 70
**Test:** `TestLexerIntegerLiteralValidation`

### Description

The integer literal regex accepts digit sequences consisting entirely of underscores (e.g., `4'b_`, `4'd___`). The regex requires at least one `[0-9a-fA-F_]` character, and underscores satisfy that requirement.

### Reproduction

```slip
module m (y) { assign y = 4'b_; }     // should be error: no actual digits
module m (y) { assign y = 4'd___; }   // should be error: no actual digits
```

---

## BUG-011: Replication syntax `{n{expr}}` completely broken

**Severity:** HIGH
**File:** `src/slip/parser/pratt.py` line 190-204
**Test:** `TestReplicationSyntax`

### Description

The `{n{expr}}` replication syntax (e.g., `{4{1'b0}}`) fails to parse. `ReplicationExpr` exists in the AST but the parser never constructs it — the `LBRACE` handler tries to parse it as a concatenation and fails when it encounters the inner braces.

### Reproduction

```slip
module m (y) { logic [15:0] y; assign y = {4{1'b0}}; }
```

### Expected

`{4{1'b0}}` should produce `ReplicationExpr(count=4, inner=IntLiteralExpr("1'b0"))`.

### Actual

Parse error: "expected expression" or "expected RBRACE".

---

## BUG-012: Missing arithmetic shift operators `<<<`, `>>>`

**Severity:** HIGH
**File:** `src/slip/lexer/token.py`, `src/slip/lexer/tokenizer.py`, `src/slip/parser/pratt.py`
**Test:** `TestArithmeticShift`

### Description

The lexer and parser don't support `<<<` (arithmetic left shift) and `>>>` (arithmetic right shift). These are standard SystemVerilog operators needed for signed arithmetic.

### Reproduction

```slip
module m (y) { assign y = 8'sb1000 >>> 1; }  // should be arithmetic shift
module m (y) { assign y = 8'sb0001 <<< 1; }  // should be arithmetic shift
```

---

## BUG-013: No undefined-signal check — typos silently create implicit 1-bit signals

**Severity:** HIGH
**File:** `src/slip/semantic/ir_builder.py` line 99-111
**Test:** `TestUndefinedSignalSilent`

### Description

When an identifier appears in an expression but was never declared, `ir_builder` silently creates an implicit 1-bit signal declaration. This means typos in signal names are never caught.

### Reproduction

```slip
module m (data_out) {
    logic [7:0] data_in;
    logic [7:0] data_out;
    assign data_out = data_ouut;  // typo: 'ouut' instead of 'out'
}
```

### Expected

Semantic error: "undefined signal 'data_ouut'".

### Actual

Compiles successfully. `data_ouut` becomes an implicit 1-bit signal.

---

## BUG-014: No multi-driver detection

**Severity:** HIGH
**File:** `src/slip/semantic/driver_analysis.py` line 23-25
**Test:** `TestMultiDriver`

### Description

Driver analysis tracks which signals are driven but never checks for multiple drivers. A signal driven in both an `always_ff` and `always_comb` block (or two `always_ff` blocks) passes silently.

### Reproduction

```slip
module m (clk, a, q) {
    logic [7:0] a; logic [7:0] q;
    seq (clk) { q = a; }
    comb { q = a; }  // multi-driver: q driven in both seq and comb
}
```

### Expected

Semantic error: "signal 'q' driven by multiple always blocks".

### Actual

Compiles without warning.

---

## BUG-015: No combinational loop detection

**Severity:** HIGH
**File:** `src/slip/semantic/driver_analysis.py`
**Test:** `TestCombLoop`

### Description

No analysis detects combinational feedback loops. `a = b; b = a;` in a `comb` block creates an infinite combinational loop that would cause simulation hangs.

### Reproduction

```slip
module m (a, b) {
    logic a; logic b;
    comb { a = b; b = a; }
}
```

---

## BUG-016: `assign foo <= bar;` is illegal SystemVerilog

**Severity:** HIGH
**File:** `src/slip/codegen/fragment.py` line 51-52, `src/slip/ir/assignment.py` line 10-12
**Test:** `TestAssignNonblocking`

### Description

`HDLAssignment.to_sv()` always prepends `assign`, and the fragment `assign_stmt()` does the same. When `is_nonblocking=True`, this produces `assign q <= d;` which is illegal SV — nonblocking assignments can only appear inside procedural blocks.

### Reproduction

```slip
module m (clk, d, q) {
    logic [7:0] d; logic [7:0] q;
    seq (clk) { q = d; }  // seq_correction changes = to <=
}
```

### Actual Output

```systemverilog
assign q <= d;  // ILLEGAL — should be inside always_ff
```

---

## BUG-017: Missing required ports not checked for explicit instance connections

**Severity:** HIGH
**File:** `src/slip/semantic/instance_resolve.py` line 42-43
**Test:** `TestMissingRequiredPort`

### Description

When an instance uses explicit `.port(signal)` connections, there's no check that all required ports of the target module are connected. Missing ports are silently left unconnected.

### Reproduction

```slip
module child (a, b, y) { ... }
module parent (x) {
    logic x;
    child u1 { .a(x) };  // missing .b and .y
}
```

---

## BUG-018: Missing `**` (exponentiation) operator

**Severity:** MEDIUM
**File:** `src/slip/lexer/token.py`, `src/slip/parser/pratt.py`
**Test:** `TestMissingExponentiation`

### Description

The `**` exponentiation operator is not supported in the lexer or parser. This is a standard SystemVerilog operator used for parameterized widths.

### Reproduction

```slip
module m #(param N = 3) (y) { assign y = 2 ** N; }
```

---

## BUG-019: Missing `===`/`!==` (four-state identity) operators

**Severity:** MEDIUM
**File:** `src/slip/lexer/token.py`, `src/slip/parser/pratt.py`
**Test:** `TestMissingFourStateOps`

### Description

Four-state case equality (`===`) and case inequality (`!==`) operators are not supported. These are essential for comparing values that may contain `x` or `z`.

### Reproduction

```slip
module m (y) { assign y = (a === b); }
module m (y) { assign y = (a !== b); }
```

---

## BUG-020: Missing width-cast syntax `8'(expr)`

**Severity:** MEDIUM
**File:** `src/slip/parser/pratt.py` line 206-226
**Test:** `TestMissingWidthCast`

### Description

The width-cast syntax `width'(expr)` (e.g., `8'(x + y)`) is not supported. Only `signed'` and `unsigned'` casts are implemented.

### Reproduction

```slip
module m (y) { assign y = 8'(x + 1); }
```

---

## BUG-021: For-loop step limited to `IDENT = expr`

**Severity:** MEDIUM
**File:** `src/slip/parser/parser.py` line 337-339
**Test:** `TestForStepLimited`

### Description

The for-loop step clause only accepts `IDENT = expr`. Increment operators (`i++`, `i += 1`) and other step patterns are rejected.

### Reproduction

```slip
module m (y) {
    for (i = 0; i < 8; i++) { assign y = i; }        // fails
    for (i = 0; i < 8; i += 1) { assign y = i; }     // fails
}
```

---

## BUG-022: Port width parser inconsistent with signal width parser

**Severity:** MEDIUM
**File:** `src/slip/parser/parser.py` line 137-144
**Test:** (documented in plan, no dedicated test)

### Description

Port declarations parse width differently from signal declarations. Port `[7:0]` may not produce the same IR as signal `[7:0]`.

---

## BUG-023: Bare identifier fallthrough produces misleading errors

**Severity:** MEDIUM
**File:** `src/slip/parser/parser.py` line 187-188
**Test:** (documented in BUG-004)

### Description

When `_parse_statement` encounters an IDENT that doesn't match any pattern, it falls through to `_parse_signal_decl`. This can produce confusing error messages — e.g., `a + b;` tries to parse `a` as a signal declaration.

---

## BUG-024: No duplicate declaration detection

**Severity:** MEDIUM
**File:** `src/slip/semantic/symbol_collector.py` line 79-100
**Test:** `TestDuplicateDeclaration`

### Description

Slip's semantic analysis doesn't detect duplicate signal declarations. Two `logic x;` statements in the same module are both accepted. pyslang catches this at codegen time, but the error message is a pyslang diagnostic, not a friendly Slip error.

### Reproduction

```slip
module m (y) { logic x; logic x; assign y = x; }
```

---

## BUG-025: No port width mismatch check on instance connections

**Severity:** MEDIUM
**File:** `src/slip/semantic/instance_resolve.py` line 126-176
**Test:** (no dedicated test)

### Description

When connecting an 8-bit port to a 1-bit signal (or vice versa), no width mismatch warning is emitted.

---

## BUG-026: Non-regex instance target module existence not validated

**Severity:** MEDIUM
**File:** `src/slip/semantic/instance_resolve.py` line 42-43
**Test:** `TestInstanceModuleExistence`

### Description

When an instance references a module by name (non-regex), the semantic phase doesn't check that the target module exists. A typo in the module name only fails at codegen time with a pyslang error.

### Reproduction

```slip
module child (a) { logic a; }
module parent (x) { logic x; child_typo u1 { .a(x) }; }
```

---

## BUG-027: `inout` never inferred despite documented possibility

**Severity:** MEDIUM
**File:** `src/slip/semantic/driver_analysis.py` line 121-146
**Test:** (no dedicated test)

### Description

Port direction inference only produces `input` or `output`. A port that is both read and written should be inferred as `inout` but is instead assigned one direction based on priority.

---

## BUG-028: Reset polarity inconsistency not detected

**Severity:** MEDIUM
**File:** `src/slip/semantic/ir_builder.py` line 203-211
**Test:** (no dedicated test)

### Description

If a module uses `neg: rst_n` in one seq block and `rst_n` (positive) in another, no error is raised about inconsistent reset polarity.

---

## BUG-029: `always_latch` emitted with spurious sensitivity list

**Severity:** MEDIUM
**File:** `src/slip/codegen/fragment.py` line 57-60
**Test:** `TestAlwaysLatch`

### Description

Per IEEE 1800, `always_latch` should not have an explicit sensitivity list. The codegen emits `always_latch @(*) begin` which, while not illegal, is non-standard and triggers warnings in some tools.

### Actual Output

```systemverilog
always_latch @(*) begin  // should be: always_latch begin
```

---

## BUG-030: `UndeclaredIdentifier` suppression too broad

**Severity:** MEDIUM
**File:** `src/slip/codegen/emitter.py` line 8-13
**Test:** `TestDiagnosticSuppression`

### Description

The emitter suppresses `UndeclaredIdentifier` and `CouldNotResolve` pyslang diagnostics. This is needed because Slip creates implicit signals, but it also hides real typos in SV expressions that pyslang would otherwise catch.

---

## BUG-031: pyslang `ImportError` silently swallowed

**Severity:** MEDIUM
**File:** `src/slip/codegen/emitter.py` line 74-75
**Test:** (documented in plan)

### Description

If pyslang is not installed, the `ImportError` is caught and validation is silently skipped. No warning is emitted, so users may think their code is valid when it isn't.

---

## BUG-032: `HDLAssignment.to_sv()` always prepends `assign`

**Severity:** MEDIUM
**File:** `src/slip/ir/assignment.py` line 10-12
**Test:** `TestHDLAssignmentToSV`

### Description

`HDLAssignment.to_sv()` always produces `assign target op value;`. Inside procedural blocks (always_ff, always_comb), the `assign` keyword should not appear. The fragment code (`_emit_block_item`) correctly omits `assign`, but `to_sv()` itself is wrong.

---

## BUG-033: `type_: HDLType = None` missing `Optional` annotation

**Severity:** LOW
**File:** `src/slip/ir/signal.py` line 9, `src/slip/ir/port.py` line 10
**Test:** `TestIRTypeAnnotations`

### Description

`HDLSignal.type_` and `HDLPort.type_` are annotated as `HDLType` but default to `None`. The annotation should be `HDLType | None` or `Optional[HDLType]`.

---

## BUG-034: `LogicBlock.kind` and `HDLPort.direction` are unconstrained strings

**Severity:** LOW
**File:** `src/slip/ir/logic_block.py` line 15, `src/slip/ir/port.py` line 9
**Test:** `TestIRUnconstrainedStrings`

### Description

`LogicBlock.kind` accepts any string (e.g., `"always_wrong"`). `HDLPort.direction` accepts any string (e.g., `"banana"`). These should be constrained to valid values via `Literal` types or enums.

---

## BUG-035: `HDLInstance.regex_rules` defined but never consumed by emitter

**Severity:** LOW
**File:** `src/slip/ir/instance.py` line 10
**Test:** `TestInstanceRegexRules`

### Description

`HDLInstance` has a `regex_rules` field that is populated during instance resolution but never referenced by the codegen emitter or fragment code. The regex rules are consumed during semantic analysis (instance_resolve) and don't need to be in the IR, or the emitter should use them.

---

# Feature Gaps

These are standard HDL features that Slip does not support.

| ID | Feature | Decision |
|----|---------|----------|
| FEAT-001 | case/casez/casex | Implement |
| FEAT-002 | inside operator | Implement |
| FEAT-003 | compound assignment (+=, etc.) | Implement |
| FEAT-004 | wire/reg distinction | WON'T FIX — `logic` is fine |
| FEAT-005 | generate blocks | WON'T FIX — compile-time expand替代 |
| FEAT-006 | initial blocks | Implement |
| FEAT-007 | procedural for/while in IR | Implement |
| FEAT-008 | case statements in IR | Implement (跟 FEAT-001) |
| FEAT-009 | width mismatch warning | Implement — warning only |
| FEAT-010 | clock domain check | WON'T FIX — 非编译器职责 |
| FEAT-011 | module topological sort | Implement |
| FEAT-012 | validation.py dead code | Code quality |

## FEAT-001: No `case`/`casez`/`casex` statement support

**Area:** Parser, IR, Codegen

The parser has no support for `case`, `casez`, or `casex` statements. These are fundamental SystemVerilog constructs for multiplexers and state machines.

---

## FEAT-002: No `inside` operator and set membership

**Area:** Parser

The `inside` operator (`x inside {1, 2, 3}`) is not supported. This is a SystemVerilog 2009 feature for set membership testing.

**Decision:** Implement.

---

## FEAT-003: No compound assignment operators (`+=`, `|=`, etc.)

**Area:** Parser

Compound assignment operators (`+=`, `-=`, `*=`, `/=`, `%=`, `&=`, `|=`, `^=`, `<<=`, `>>=`, `<<<=`, `>>>=`) are not supported.

---

## FEAT-004: ~~No `wire`/`reg` type distinction~~ (WON'T FIX)

**Area:** Codegen

~~All signals are emitted as `logic`. There is no way to declare `wire` (for continuous assignments) or `reg` (for procedural assignments).~~

**Decision:** Not implementing. Modern SystemVerilog uses `logic` universally. wire/reg distinction is a style preference, not a correctness issue.

---

## FEAT-005: ~~No generate blocks~~ (WON'T FIX)

**Area:** IR, Codegen

~~The IR has no representation for generate blocks.~~

**Decision:** Not implementing. Slip's compile-time `` `for ``/`` `if `` expansion serves the same purpose. `generate`/`endgenerate` are optional in modern SV.

---

## FEAT-006: No `initial` blocks

**Area:** IR, Codegen

`initial` blocks (used in testbenches) are not supported. `LogicBlock.kind` only supports `always_ff`, `always_comb`, and `always_latch`.

**Decision:** Implement. Design engineers may write testbenches in Slip.

---

## FEAT-007: No `for`/`while` loops in procedural block IR

**Area:** IR

The IR `LogicBlock.body` only contains `HDLAssignment` and `HDLIfBlock`. There is no `HDLForLoop` or `HDLWhileLoop` for procedural `for`/`while` statements. The `ForStmt` in the AST is either expanded by gen_expand or dropped by ir_builder (BUG-001).

---

## FEAT-008: No case statements in IR

**Area:** IR

There is no `HDLCaseBlock` in the IR. Case statements cannot be represented or emitted.

---

## FEAT-009: No type/width mismatch detection in assignments

**Area:** Semantic

No check that the left and right sides of an assignment have compatible widths. `logic [7:0] a; logic [3:0] b; assign a = b;` compiles without warning.

**Decision:** Implement — should emit warning (not error) on width mismatch.

---

## FEAT-010: ~~No clock domain consistency check~~ (WON'T FIX)

**Area:** Semantic

~~No analysis verifies that signals used in a `seq` block are driven by the same clock domain.~~

**Decision:** Not implementing. Slip's target users are experienced hardware engineers who handle CDC themselves. Adding CDC linting would be over-engineering for Slip's positioning as a convenience tool, not a verification tool.

---

## FEAT-011: No dependency ordering between modules (topological sort)

**Area:** Generator

When generating multiple modules, the output order is arbitrary. If module A instantiates module B, some tools require B to be defined before A. A topological sort of module dependencies is needed.

---

## FEAT-012: Dead code: `validation.py` never called by production code

**Area:** Validation

`slang_integration.validation.validate_sv` is exported but never called. The emitter has its own inline pyslang validation with different behavior. See BUG-003.
