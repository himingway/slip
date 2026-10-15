# Project builds and debugging

## Outputs and dependencies

`slip build` publishes modules only after the entire selected design passes
validation. It also writes the following files into the output directory:

| File | Purpose |
| --- | --- |
| `sources.f` | Absolute, quoted external SV and generated module paths, include paths and defines. Generated modules follow dependency order. |
| `slip.d` | Make dependency rule for generated modules and the output manifest. Includes Slip sources, external SV/header files, nested filelists and the CLI project configuration. Scanned IP/library directories are dependencies too, so adding a source invalidates the build. |
| `source-map.json` | Versioned generated-line to Slip file/line/column map. Compile-time loop bindings appear as `expansion`. Source paths are absolute (except virtual labels); generated paths are relative to this map's directory. |
| `.slip-build-stamp` | Successful generator invocation marker for Make/Ninja. Its timestamp advances even when generated SV is unchanged. |
| `.slip-manifest` | Ownership and content fingerprints for generated files. |

Content-identical SV and metadata outputs keep their timestamps; the success stamp
advances after publication. A later successful build removes
obsolete files only if they are still identical to Slip's recorded contents.
Handwritten files and edited obsolete outputs are preserved and excluded from
`sources.f`. Editing an output that the current build needs to replace reports
`E_OUTPUT_MODIFIED`; move that edit before rebuilding. Use `sources.f` rather than
a wildcard to select downstream sources.

Each changed file is staged and atomically renamed. `.slip-lock` prevents two
publishers from writing the same output directory simultaneously. A process
terminated without cleanup can leave this lock; remove it after checking that no
publisher remains. Compilation into different directories is independent.

A downstream invocation can read the generated list directly, for example:

```sh
verilator --lint-only --top-module top -f build/rtl/sources.f
```

The filelist preserves compilation inputs; tool-specific switches belong in the
downstream command. For Make, use the success stamp as the generator target, and include `slip.d`:

```make
out := $(abspath build/rtl)
all: $(out)/.slip-build-stamp
$(out)/.slip-build-stamp: design.slip
	slip build design.slip -o $(out)
-include $(out)/slip.d
```

This avoids rerunning the generator on every invocation when a source change
produces identical SV. With Ninja, declare the stamp as the first generator output,
list generated modules as additional outputs, consume `slip.d` as a depfile and
enable `restat` so unchanged SV does not retrigger downstream compilation.

## Filelists

Paths are relative to the filelist containing them, including nested `-f` and
`-F` lists. This preserves Slip's existing file-relative `-f` behavior. Quote paths
containing spaces. Quoting also preserves literal `+` within an option value.

```text
+incdir+"headers with spaces"
+define+WIDTH=16+ENABLE=1
-I another/include
-D MODE=2
-f lists/common.f
-v rtl/specific_cell.v
+libext+.v+.sv
-y cells
"${RTL_ROOT}/rtl/top.sv"
```

Both multiple arguments per line and backslash continuations are accepted.
`//`, `#` comments at argument boundaries and `/* ... */` comments are supported.
`$NAME`, `${NAME}` and `$(NAME)` expand environment variables; unset variables
report `E_FILELIST`. Single quotes or `\$` preserve a literal dollar sign.
`-sverilog` and `-sv` are accepted because Slip already parses SV sources.
Unsupported options report their file, line and column instead of being ignored.
Library directories scan regular files with the configured extensions in sorted
order; they do not recursively scan unrelated subdirectories. IP directories
passed using `-ip` retain recursive scanning.

## Tops, parameters and profiles

```ini
entry = rtl/top.slip
out_dir = build/rtl
top = top
param.WIDTH = 8
strict = true
warning.W_LATCH = error
warning.W_UNDRIVEN = error

[profile.fpga]
param.WIDTH = 16
out_dir = build/fpga

[profile.asic]
param.WIDTH = 32
out_dir = build/asic
```

```sh
slip build --project slip.conf --profile fpga
slip inspect --project slip.conf --profile asic -P WIDTH=64 --format=json
slip check rtl/top.slip --top top --param WIDTH=16
```

Defaults apply first, then the selected profile, then CLI overrides. Scalar keys,
individual `param.NAME` and `warning.CODE` keys replace earlier values. `ip_dir`
and `filelist` append in order. Paths remain relative to the configuration file;
CLI paths remain relative to the working directory. Profiles use
`[profile.NAME]`; duplicate sections and unknown selected profiles are errors.
An explicit input with `--profile` loads `./slip.conf` unless `--project` supplies
another path. Without a profile, the existing explicit-input rules still apply.

`--top` selects a Slip module and emits only reachable modules. Unused definitions
are parsed but not elaborated. Top parameter overrides require an explicit top;
unknown parameters are errors. Overrides take effect before compile-time expansion
and specialization, so structural parameters work as well as ordinary RTL ones.
Without `--top`, Slip retains its existing all-modules compilation behavior.

## Warning policy and local waivers

```sh
slip check design.slip --warning W_LATCH=error --warning W_UNCONNECTED=error
slip check design.slip --warnings-as-errors --warning W_WIDTH=warning
slip check design.slip --no-implicit-ports --allow-implicit-signals
```

Known warning codes are `W_IMPLICIT`, `W_WIDTH`, `W_LATCH`, `W_UNDRIVEN`,
`W_UNCONNECTED`, `W_REGEX_UNUSED` and `W_SEQ_CONVERSION`. Per-code levels are
`error`, `warning` and `off`; a per-code setting takes precedence over the global
`--warnings-as-errors`. `--warnings-as-warnings` overrides a project-wide promotion
setting; per-code settings still take precedence. Unknown codes and levels are configuration errors.
Promoted warnings fail compilation before outputs are published, with
`E_WARNING_AS_ERROR` and the original warning codes in the message.

`no_implicit_ports` and `no_implicit_signals` are independent project booleans,
with matching `--no-implicit-*` and `--allow-implicit-*` flags. `--no-implicit`
rejects both categories; a later scoped allowance overrides it for that category. Listing a name in the module header counts as an
explicit port. These controls do not require explicit direction or type.

Source comments can waive warnings when they include a reason:

```slip
module low_bits(a, y) {
    logic [7:0] a;
    logic [3:0] y;
    // slip: waive W_WIDTH -- the protocol intentionally keeps the low nibble
    assign y = a;
}
```

`waive` applies to the same executable line or the next executable line. For a
multiline region, use `// slip: disable W_WIDTH -- reason` and
`// slip: enable W_WIDTH`. Multiple codes may be comma-separated. A disable lasts
to the matching enable or the end of that source file; it never leaks into an
included file. Waivers apply before promotion. They do not suppress syntax or
semantic errors, including `--strict` errors. Misspelled codes, missing reasons
and unpaired enables report `E_DIAGNOSTIC_CONFIG`.

## RTL convenience and actionable errors

Sized and unsized based constants accept the SV signed marker: `8'shff`,
`16'sd123`, `'shff`. Fill constants include `'0`, `'1`, `'x` and `'z`.
Comma-separated declarations share type and packed width, while each name has its
own unpacked dimensions: `logic [7:0] a, b[0:3];`.

Procedural loops accept `for (int i=0; i<N; i++)`, `integer`, decrement and
compound steps. Compile-time loops also accept increment/decrement and compound
steps, but require backticks on the keyword and variable. Mixing ordinary `for`
with a backtick variable gives a diagnostic explaining the two forms. Ordinary
module-level `for`/`if` errors suggest the compile-time spelling.

## Signal inspection

```sh
slip inspect design.slip --signal top.internal_data
slip inspect design.slip --signal top.internal_data --format=json
```

A signal report includes its declaration, explicit/inferred direction and type,
width origin, drivers and uses. `drivers` and `uses` are also present on each
signal in full JSON inspection. Each reference has a `kind`, `expression` and
`location`; generated loop locations retain their expansion bindings. References
cover assignments, conditions, loop controls, clocks/resets, assertions and
instance connections within that module. Instance boundaries identify the
connected port; the report does not claim to flatten external IP implementation
or trace transitively through it. Struct member access is attributed to its root
signal, with the referenced expression retained.

## SV interoperability and editors

The [native interface guide](native-interfaces.md) covers package-qualified types,
type parameters, attributes and interface arrays. The complete
[interop example](../examples/interop/slip.conf) connects parameterized arrays of
interfaces carrying a packed package struct. Type parameters used by generation
controls are specialized, including propagation through wrappers; ordinary RTL
type parameters remain overridable in generated SV.

The [VS Code and LSP package](../editors/vscode/README.md) provides highlighting,
snippets, save diagnostics, completion, navigation, hover, symbols and formatting.
The [Vim / Neovim package](../editors/vim/README.md) adds syntax, indentation,
background `:SlipCheck` / `:SlipBuild`, readable `:SlipInspect` and `:SlipFormat`.
Neovim uses its native LSP client for completion/navigation; Vim can use vim-lsp.
Both share the same server and project/profile settings.
For external port discovery without a valid Slip design, use:

```sh
slip inspect --interface external_ip --project slip.conf --format=json
```

It reflects default parameters and ports independently of design validation.
This is also how the editor completes a newly written external instance.
