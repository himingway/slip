"""The manual's code listings must show code that actually works.

``lstlisting`` is a verbatim environment: LaTeX escapes written inside it
are printed literally.  Writing ``\\$upper(\\\\1)`` — the text-mode
spelling used elsewhere in the document — therefore reached the PDF as
literal backslashes, and a reader copying the example got a replacement
string that produces an illegal identifier (``logic \\X;``).

These tests pin both halves of that problem:

* a lint over the .tex source: no text-mode escapes inside verbatim
  listings, in the manual or the README code fences;
* a compile check: the regex/defun examples the docs show must compile to
  the documented result.
"""

import re
from pathlib import Path

import pytest

from conftest import compile_source

REPO = Path(__file__).resolve().parents[2]
MANUAL = REPO / "docs" / "tex" / "user-manual.tex"


def _listing_lines(text: str):
    """Yield (line number, line) for verbatim *content* lines.

    ``\\begin{lstlisting}}[...]`` options may span several lines and are
    LaTeX code, not listing content, so they are skipped.
    """
    in_listing = False
    in_options = False
    for n, line in enumerate(text.splitlines(), 1):
        if "\\begin{lstlisting}" in line:
            in_listing = True
            # Options either close on this line or continue on following ones
            rest = line.split("lstlisting", 1)[1]
            in_options = rest.strip().startswith("[") and "]" not in rest
            continue
        if "\\end{lstlisting}" in line:
            in_listing = False
            in_options = False
            continue
        if in_listing and in_options:
            if "]" in line:
                in_options = False
            continue
        if in_listing:
            yield n, line


# Escapes that mean something in text mode but are printed as-is verbatim.
_TEXT_MODE_ESCAPES = {
    "\\$": "$ (text mode escape; verbatim prints the backslash)",
    "\\\\": "\\ (text mode escape; verbatim prints both backslashes)",
    "\\_": "_ (text mode escape; verbatim prints the backslash)",
    "\\#": "# (text mode escape; verbatim prints the backslash)",
}


def test_manual_listings_have_no_text_mode_escapes():
    offenders = []
    for n, line in _listing_lines(MANUAL.read_text(encoding="utf-8")):
        for esc, why in _TEXT_MODE_ESCAPES.items():
            if esc in line:
                offenders.append(f"user-manual.tex:{n}: contains {esc!r} — {why}\n    {line.strip()}")
    assert not offenders, (
        "text-mode escapes inside verbatim listings render literally:\n"
        + "\n".join(offenders)
    )


@pytest.mark.parametrize("readme", ["README.md", "README_CN.md"])
def test_readme_fences_have_no_doubled_backreferences(readme):
    """Markdown fences are literal too: `\\\\1` reaches the reader as `\\\\1`."""
    text = (REPO / readme).read_text(encoding="utf-8")
    fences = re.findall(r"```[a-z]*\n(.*?)```", text, re.DOTALL)
    offenders = [
        ln for block in fences for ln in block.splitlines() if "\\\\1" in ln or "\\\\2" in ln
    ]
    assert not offenders, f"{readme}: doubled backslash in a code fence:\n" + "\n".join(offenders)


class TestDocumentedExamplesCompile:
    """Regex/defun snippets from the docs compile to the documented result."""

    def test_single_backslash_replacement_works(self):
        sv = compile_source(
            "module child (clk, data_x) { logic clk; logic data_x; }\n"
            'module m (clk, X) { logic clk; logic X;\n'
            '  child u1 { .clk, "data_(.*)" => "$upper(\\1)" }; }'
        )["m"]
        assert ".data_x(X)" in sv

    def test_doubled_backslash_is_not_valid(self, tmp_path):
        """The old doc spelling must not silently produce a broken name.

        It yields a literal backslash in the identifier, which pyslang
        rejects — so a reader copying it gets a compile error, not silent
        wrong output.
        """
        from slip.errors.codegen import SlipCodegenError
        with pytest.raises(SlipCodegenError):
            compile_source(
                "module child (clk, data_x) { logic clk; logic data_x; }\n"
                'module m (clk, X) { logic clk; logic X;\n'
                '  child u1 { .clk, "data_(.*)" => "$upper(\\\\1)" }; }'
            )

    def test_manual_regex_function_example(self):
        """The §18.5.1 example compiles to the documented port names."""
        sv = compile_source(
            "module child (clk, data_a, ch_5) { logic clk; logic data_a; logic ch_5; }\n"
            "module m (clk, bus_A, port_6) { logic clk; logic bus_A; logic port_6;\n"
            '  child u1 { .clk,\n'
            '    "data_(.*)" => "bus_$upper(\\1)",\n'
            '    "ch_(.*)"   => "port_$add(\\1, 1)" };\n'
            "}"
        )["m"]
        assert ".data_a(bus_A)" in sv
        assert ".ch_5(port_6)" in sv  # $add captures the numeric group

    def test_arithmetic_function_requires_numeric_capture(self):
        """$add on a non-numeric capture is a located error, not silent junk."""
        from slip.errors.semantic import SlipSemanticError
        with pytest.raises(SlipSemanticError, match="regex port mapping error"):
            compile_source(
                "module child (clk, ch_b) { logic clk; logic ch_b; }\n"
                'module m (clk, port_c) { logic clk; logic port_c;\n'
                '  child u1 { .clk, "ch_(.*)" => "port_$add(\\1, 1)" }; }'
            )

    def test_manual_prefix_function_suffix_example(self):
        sv = compile_source(
            "module child (clk, port_x) { logic clk; logic port_x; }\n"
            "module m (clk, pre_X_post) { logic clk; logic pre_X_post;\n"
            '  child u1 { .clk, "port_(.*)" => "pre_$upper(\\1)_post" }; }'
        )["m"]
        assert ".port_x(pre_X_post)" in sv
