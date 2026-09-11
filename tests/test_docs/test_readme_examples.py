"""Compile the examples shown in README.md and README_CN.md.

The README's quick example is the project's front door; if the documented
output drifts from what the compiler emits, readers are misled about the
language's semantics.  These tests extract the ``slip`` and
``systemverilog`` code blocks from the quick example and assert that the
generated SV matches the documented one line for line.
"""

import re
from pathlib import Path

import pytest

from conftest import compile_source

REPO = Path(__file__).resolve().parents[2]


def _extract_quick_example(readme: Path) -> tuple[str, str]:
    """Return (slip_source, documented_sv) from the README quick example."""
    text = readme.read_text(encoding="utf-8")
    blocks = re.findall(r"```(slip|systemverilog)\n(.*?)```", text, re.DOTALL)
    assert blocks, f"no code blocks found in {readme}"
    slip_src = next(b for lang, b in blocks if lang == "slip")
    documented = next(b for lang, b in blocks if lang == "systemverilog")
    return slip_src, documented


@pytest.mark.parametrize("readme", ["README.md", "README_CN.md"])
def test_quick_example_matches_generated_sv(readme):
    slip_src, documented = _extract_quick_example(REPO / readme)
    generated = compile_source(slip_src)["pipeline"]

    def norm(text):
        return [ln.rstrip() for ln in text.strip().splitlines() if ln.strip()]

    def is_annotation(line):
        return line.strip().startswith("//")

    # Documented output omits the review annotations the compiler adds
    gen_lines = [ln for ln in norm(generated) if not is_annotation(ln)]
    doc_lines = norm(documented)

    assert gen_lines == doc_lines, (
        f"{readme}: documented output does not match generated output\n"
        f"--- generated ---\n" + "\n".join(gen_lines) +
        "\n--- documented ---\n" + "\n".join(doc_lines)
    )


@pytest.mark.parametrize("readme", ["README.md", "README_CN.md"])
def test_quick_example_is_a_real_pipeline(readme):
    """Every stage must sample the previous stage (a true shift register)."""
    slip_src, _ = _extract_quick_example(REPO / readme)
    sv = compile_source(slip_src)["pipeline"]
    assert "stage[0] <= din;" in sv
    assert "stage[1] <= stage[0];" in sv
    assert "stage[2] <= stage[1];" in sv
    # the old (wrong) self-decrement must not appear
    assert "stage_1 - 1" not in sv
