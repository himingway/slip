# Practical project improvements

This checklist tracks the complete requested scope. An unchecked item is not
claimed complete. Existing inferred-declaration annotations must be retained.

- [x] Generated output ownership: unchanged RTL/metadata keep timestamps, a
  dedicated success stamp advances, and stale owned
  files are removed without deleting user files, generated filelist and Make
  dependencies include external sources, headers, filelists and project config.
- [x] Filelists: quoted paths, environment variables, nested lists, library
  directories/files/extensions, useful diagnostics for unsupported options.
- [x] Projects: explicit top, top parameter overrides, named profiles and
  deterministic precedence between defaults, profiles and CLI options.
- [x] Diagnostics: per-code severity, reasoned local suppression, separate
  controls for implicit ports and internal signals.
- [x] RTL ergonomics: signed literals, common declaration forms and actionable
  diagnostics for runtime versus compile-time loops.
- [x] SV interoperability: package-qualified types, type parameters, interface
  arrays and synthesis attributes.
- [x] Debugging: exported generated-line source maps with expansion bindings;
  signal queries show drivers, uses and inference provenance.
- [x] Editor support: syntax highlighting, save diagnostics, instance-port
  completion, formatting and a working LSP integration.
- [x] Documentation, examples, focused regression checks and full validation.

Implementation and verification notes are recorded here as work progresses.

## Delivered

- Output ownership, unchanged timestamps, stale cleanup, safe destination checks,
  generated `sources.f`, `slip.d`, `source-map.json`.
- Filelist quoting/variables/libraries/options, including round trips for paths
  containing spaces, plus signs, dollar signs and hashes.
- `--top`, `--param`/`-P`, `[profile.NAME]` and CLI precedence.
- Per-code warning policy, reasoned local waivers, independent implicit controls.
- Signed literals, common loop forms, multi-name declarations and targeted errors.
- `inspect --signal MODULE.NAME`, driver/use references and source provenance.
- New user guide: `docs/practical-projects.md`; TeX/PDF regenerated successfully.
- Package types, ordinary and generation-dependent type parameters, synthesis
  attributes and multidimensional interface arrays are implemented. ANSI emission
  is used when types are visible in the header; local typedef ports retain scope.
- The interop example and Verilator test verify package structs, generic types,
  parameterized arrays and element connections for 256 input values.
- A standard-library Python LSP server and dependency-free VS Code adapter provide
  highlighting, save checks, completion, navigation, hover, symbols and formatting.
  Real protocol/compiler and adapter tests pass. The final local VSIX package
  contains the current sources and excludes generated Python caches.

## Completion audit before the Vim/Neovim addition

All eight requirements have been checked against current source, generated output
and runtime evidence:

| Requirement | Implementation | Verification |
| --- | --- | --- |
| Managed outputs | `src/outputs.cpp`, `Result` metadata | Unchanged timestamps, safe stale cleanup, modified/symlink destination protection, generated filelist round trips, physical header/config dependencies, and a real Make comment-only rebuild check. The success stamp advances without rewriting unchanged SV. |
| Filelists | `src/sources.cpp` | Nested lists, quotes, environment expansion/unset errors, library options/extensions, unsupported-option locations, special-character path round trips and Verilator consumption. |
| Tops and profiles | `src/project.cpp`, CLI, `Specializer` | Default/profile/CLI precedence, numeric and type overrides before expansion, pruning unused roots, unknown top/parameter/profile errors. |
| Warning policy | `src/diagnostics.cpp`, scoped implicit options | Per-code severity, global promotion/demotion, reasoned local and region waivers, malformed-waiver errors, independent implicit ports/signals and scoped CLI overrides. |
| RTL ergonomics | `src/frontend.cpp` | Signed literals, malformed literal termination, multi-name declarations, procedural/compile-time loop steps and targeted misuse diagnostics. |
| SV interoperability | Frontend, IR, compiler and slang backend | Package type identity, attributes, native arrays and multidimensional per-element checks, type-dependent generation through wrappers, width dependency freezing, downstream override rejection, and 256-value Verilator simulation. |
| Debugging | Exported maps, signal references, `inspect --signal` | Absolute source origins (including relative CLI input), virtual labels and expansion bindings, drivers and consumers, inferred widths/types, constructor-input versus module-input provenance, static uses, JSON/text queries and unknown-query diagnostics. |
| Editors | `editors/vscode` and installed `slip-lsp` | Real stdio protocol/compiler tests, real server behind the VS Code provider adapter, save diagnostics, incomplete local/external instance completion, UTF-16 positions, navigation/hover/symbols, token-preserving formatting, VSIX package/source identity and installed formatter smoke check. |

Final native Release build succeeded. `ctest --preset release --parallel 2 --output-on-failure` passed **181/181** checks, including six behavior tests and
both editor integration tests. Test log: `/tmp/slip-project-improvements-tests.log`.
The installed compiler also compiled with an empty PATH; the optional installed
LSP script matched the source and formatted the interop example successfully.
`git diff --check` and JavaScript syntax checks passed.

The local VS Code artifact is `build/artifacts/slip-language-0.1.0.vsix`; its
bundled server and adapter were compared byte-for-byte with the current sources.
TeX/PDF were rebuilt and the added documentation was visually checked. This
audit preceded the subsequent Vim/Neovim and release work.

## Vim/Neovim addition

The subsequent editor request adds `editors/vim`: shared file detection,
highlighting/indentation, background check/build/inspect with quickfix, current
buffer formatting and optional UltiSnips snippets. Neovim uses its native LSP
client; Vim can register the shared server through vim-lsp. Installation and
settings are documented in English, Chinese and Vim help, with links from the
root READMEs and project guide. The TeX/PDF manual includes this runtime.

The formatter CLI now accepts `--tab-size` and `--use-tabs` for the buffer's
indentation settings. The VS Code package is refreshed with this shared server.
The 181-check result above belongs to the preceding audit; no plugin tests were
run for this addition. The updated 77-page PDF builds successfully and
`git diff --check` is clean.
