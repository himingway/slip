"""Tests for the error hierarchy."""

import pytest

from slip.errors import SlipError, SlipSyntaxError, SlipSemanticError, SlipCodegenError


class TestSlipError:
    def test_format(self):
        err = SlipError("test.slip", 10, 5, "something went wrong")
        assert "test.slip" in str(err)
        assert "10" in str(err)
        assert "5" in str(err)
        assert "something went wrong" in str(err)

    def test_str_equals_format(self):
        err = SlipError("f.slip", 1, 1, "msg")
        assert str(err) == err.format()

    def test_format_prefix(self):
        err = SlipError("f.slip", 1, 1, "msg")
        assert str(err).startswith("Error at")


class TestSlipSyntaxError:
    def test_inheritance(self):
        assert issubclass(SlipSyntaxError, SlipError)

    def test_construction(self):
        err = SlipSyntaxError("test.slip", 5, 10, "unexpected token")
        assert err.file == "test.slip"
        assert err.line == 5
        assert err.col == 10
        assert "unexpected token" in str(err)

    def test_is_exception(self):
        assert issubclass(SlipSyntaxError, Exception)


class TestSlipSemanticError:
    def test_inheritance(self):
        assert issubclass(SlipSemanticError, SlipError)

    def test_construction(self):
        err = SlipSemanticError("test.slip", 3, 7, "undeclared identifier")
        assert err.file == "test.slip"
        assert err.line == 3
        assert err.col == 7
        assert "undeclared identifier" in str(err)


class TestSlipCodegenError:
    def test_inheritance(self):
        assert issubclass(SlipCodegenError, SlipError)

    def test_construction(self):
        err = SlipCodegenError("out.sv", 0, 0, "validation failed")
        assert err.file == "out.sv"
        assert "validation failed" in str(err)


class TestErrorRaising:
    def test_syntax_error_raises(self):
        with pytest.raises(SlipSyntaxError):
            raise SlipSyntaxError("f.slip", 1, 1, "bad syntax")

    def test_semantic_error_raises(self):
        with pytest.raises(SlipSemanticError):
            raise SlipSemanticError("f.slip", 1, 1, "bad semantics")

    def test_codegen_error_raises(self):
        with pytest.raises(SlipCodegenError):
            raise SlipCodegenError("f.sv", 1, 1, "bad codegen")

    def test_catch_base_error(self):
        with pytest.raises(SlipError):
            raise SlipSemanticError("f.slip", 1, 1, "msg")
