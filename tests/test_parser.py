import pytest
from slip.lexer import Lexer
from slip.parser import Parser
from slip.ast import *


def parse(source: str):
    tokens = Lexer(source, "test.slip").tokenize()
    return Parser(tokens, "test.slip").parse()


class TestModuleParsing:
    def test_empty_module(self):
        modules = parse("module foo {}")
        assert len(modules) == 1
        assert modules[0].name == "foo"

    def test_module_with_params(self):
        modules = parse("module foo #(param W = 8) {}")
        assert len(modules[0].params) == 1
        assert modules[0].params[0].name == "W"

    def test_module_with_ports(self):
        modules = parse("module foo (clk, rst) {}")
        assert len(modules[0].ports) == 2
        assert modules[0].ports[0].name == "clk"

    def test_module_with_port_width(self):
        modules = parse("module foo (data[8]) {}")
        assert modules[0].ports[0].width is not None

    def test_module_with_params_and_ports(self):
        modules = parse("module foo #(param W = 8, param D = 16) (clk, data) {}")
        assert len(modules[0].params) == 2
        assert len(modules[0].ports) == 2


class TestStatementParsing:
    def test_signal_decl(self):
        modules = parse("module m { logic [7:0] data; }")
        stmt = modules[0].body[0]
        assert isinstance(stmt, SignalDecl)
        assert stmt.name == "data"
        assert stmt.width is not None

    def test_signal_signed(self):
        modules = parse("module m { signed [15:0] val; }")
        stmt = modules[0].body[0]
        assert isinstance(stmt, SignalDecl)
        assert stmt.is_signed
        assert stmt.name == "val"

    def test_assign_stmt(self):
        modules = parse("module m { assign y = a & b; }")
        stmt = modules[0].body[0]
        assert isinstance(stmt, AssignStmt)
        assert stmt.target.name == "y"

    def test_seq_block(self):
        modules = parse("module m { seq (clk, neg: rst_n) { count = 0; } }")
        stmt = modules[0].body[0]
        assert isinstance(stmt, SeqBlock)
        assert stmt.clock == "clk"
        assert stmt.reset == ("neg", "rst_n")

    def test_seq_block_no_reset(self):
        modules = parse("module m { seq (clk) { count = 0; } }")
        stmt = modules[0].body[0]
        assert isinstance(stmt, SeqBlock)
        assert stmt.reset is None

    def test_if_stmt(self):
        modules = parse("module m { if (a) { count = 1; } }")
        stmt = modules[0].body[0]
        assert isinstance(stmt, IfStmt)
        assert stmt.else_body is None

    def test_if_else_stmt(self):
        modules = parse("module m { if (a) { count = 1; } else { count = 0; } }")
        stmt = modules[0].body[0]
        assert isinstance(stmt, IfStmt)
        assert stmt.else_body is not None

    def test_for_stmt(self):
        modules = parse("module m { for (i = 0; i < 10; i = i + 1) { x = i; } }")
        stmt = modules[0].body[0]
        assert isinstance(stmt, ForStmt)
        assert stmt.var == "i"

    def test_instance_stmt(self):
        modules = parse('module m { Other #(.W(8)) inst1 { .clk(clk), .data(d) }; }')
        stmt = modules[0].body[0]
        assert isinstance(stmt, InstanceStmt)
        assert stmt.module_name == "Other"
        assert stmt.inst_name == "inst1"
        assert len(stmt.params) == 1
        assert len(stmt.connections) == 2


class TestExpressionParsing:
    def test_binary(self):
        modules = parse("module m { assign y = a + b; }")
        stmt = modules[0].body[0]
        assert isinstance(stmt, AssignStmt)
        assert isinstance(stmt.value, BinaryExpr)
        assert stmt.value.op == "+"

    def test_precedence(self):
        modules = parse("module m { assign y = a + b * c; }")
        stmt = modules[0].body[0]
        expr = stmt.value
        assert isinstance(expr, BinaryExpr)
        assert expr.op == "+"
        assert isinstance(expr.right, BinaryExpr)
        assert expr.right.op == "*"

    def test_ternary(self):
        modules = parse("module m { assign y = a ? b : c; }")
        stmt = modules[0].body[0]
        assert isinstance(stmt.value, TernaryExpr)

    def test_unary(self):
        modules = parse("module m { assign y = !a; }")
        stmt = modules[0].body[0]
        assert isinstance(stmt.value, UnaryExpr)
        assert stmt.value.op == "!"

    def test_indexing(self):
        modules = parse("module m { assign y = a[3:0]; }")
        stmt = modules[0].body[0]
        assert isinstance(stmt.value, IndexExpr)
        assert stmt.value.high is not None

    def test_concatenation(self):
        modules = parse("module m { assign y = {a, b}; }")
        stmt = modules[0].body[0]
        assert isinstance(stmt.value, ConcatExpr)
        assert len(stmt.value.parts) == 2

    def test_parenthesized(self):
        modules = parse("module m { assign y = (a + b) * c; }")
        stmt = modules[0].body[0]
        assert isinstance(stmt.value, BinaryExpr)
        assert isinstance(stmt.value.left, ParenExpr)
