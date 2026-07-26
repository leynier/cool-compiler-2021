"""COOL parser (LALR) built on top of PLY yacc.

Produces an :mod:`ast` from a token stream.  Syntax errors are reported in the
expected ``(line, column) - SyntacticError: ERROR at or near "X"`` format and
abort parsing immediately (no error recovery) so that only the first syntax
error is reported -- which matches the behaviour of the test-suite.
"""

from __future__ import annotations

import logging

import ply.yacc as yacc

from . import ast
from .errors import ErrorCollection


class ParseError(Exception):
    pass


VALUE_TOKENS = {"OBJECTID", "TYPEID", "INT_CONST", "STR_CONST", "BOOL_CONST", "ERROR"}


def token_text(tok) -> str:
    """Return the textual representation of a token used in error messages."""
    if tok is None:
        return "EOF"
    if tok.type in VALUE_TOKENS:
        v = tok.value
        if isinstance(v, bool):
            return "true" if v else "false"
        return str(v)
    return tok.type


class Parser:
    tokens = (
        "OBJECTID",
        "TYPEID",
        "INT_CONST",
        "STR_CONST",
        "BOOL_CONST",
        "ERROR",
        "ASSIGN",
        "LE",
        "DARROW",
        "CLASS",
        "ELSE",
        "FI",
        "IF",
        "IN",
        "INHERITS",
        "ISVOID",
        "LET",
        "LOOP",
        "POOL",
        "THEN",
        "WHILE",
        "CASE",
        "ESAC",
        "NEW",
        "OF",
        "NOT",
    )

    precedence = (
        # ``IN`` is given the lowest precedence so that the ``let`` body
        # (rule ``LET let_decls IN expr``) greedily absorbs any following
        # operator.  This resolves the only shift/reduce conflict that the
        # flat expression grammar would otherwise produce, without changing
        # the (correct) default-shift behaviour.
        ("right", "IN"),
        ("right", "ASSIGN"),
        ("left", "NOT"),
        ("nonassoc", "<", "=", "LE"),
        ("left", "+", "-"),
        ("left", "*", "/"),
        ("left", "ISVOID"),
        ("left", "~"),
        ("left", "@"),
        ("left", "."),
    )

    # --- program / class --------------------------------------------------

    def p_program(self, p):
        "program : class_list"
        p[0] = ast.Program(p[1])

    def p_class_list_single(self, p):
        "class_list : class"
        p[0] = [p[1]]

    def p_class_list_more(self, p):
        "class_list : class_list class"
        p[0] = p[1] + [p[2]]

    def p_class(self, p):
        "class : CLASS TYPEID inherits_opt '{' feature_list '}' ';'"
        tok = p.slice[2]
        p[0] = ast.ClassDecl(p[2], p[3], p[5], tok.line, tok.col)

    def p_inherits_opt_empty(self, p):
        "inherits_opt :"
        p[0] = None

    def p_inherits_opt(self, p):
        "inherits_opt : INHERITS TYPEID"
        p[0] = p[2]

    def p_feature_list_empty(self, p):
        "feature_list :"
        p[0] = []

    def p_feature_list_more(self, p):
        "feature_list : feature_list feature ';'"
        p[0] = p[1] + [p[2]]

    def p_feature_method(self, p):
        "feature : OBJECTID '(' formals_opt ')' ':' TYPEID '{' expr '}'"
        tok = p.slice[1]
        p[0] = ast.Method(p[1], p[3], p[6], p[8], tok.line, tok.col)

    def p_feature_attribute(self, p):
        "feature : OBJECTID ':' TYPEID init_opt"
        tok = p.slice[1]
        p[0] = ast.Attribute(p[1], p[3], p[4], tok.line, tok.col)

    def p_formals_opt_empty(self, p):
        "formals_opt :"
        p[0] = []

    def p_formals_opt(self, p):
        "formals_opt : formal_list"
        p[0] = p[1]

    def p_formal_list_single(self, p):
        "formal_list : formal"
        p[0] = [p[1]]

    def p_formal_list_more(self, p):
        "formal_list : formal_list ',' formal"
        p[0] = p[1] + [p[3]]

    def p_formal(self, p):
        "formal : OBJECTID ':' TYPEID"
        tok = p.slice[1]
        p[0] = ast.Formal(p[1], p[3], tok.line, tok.col)

    def p_init_opt_empty(self, p):
        "init_opt :"
        p[0] = None

    def p_init_opt(self, p):
        "init_opt : ASSIGN expr"
        p[0] = p[2]

    # --- expressions ------------------------------------------------------

    def p_expr_assign(self, p):
        "expr : OBJECTID ASSIGN expr"
        tok = p.slice[1]
        p[0] = ast.Assign(p[1], p[3], tok.line, tok.col)

    def p_expr_dispatch(self, p):
        "expr : expr '.' OBJECTID '(' args_opt ')'"
        p[0] = ast.Dispatch(p[1], p[3], p[5], p.slice[2].line, p.slice[2].col)

    def p_expr_static_dispatch(self, p):
        "expr : expr '@' TYPEID '.' OBJECTID '(' args_opt ')'"
        # positions: 1=expr 2='@' 3=TYPEID 4='.' 5=OBJECTID 6='(' 7=args 8=')'
        p[0] = ast.StaticDispatch(p[1], p[3], p[5], p[7], p.slice[2].line, p.slice[2].col)

    def p_expr_self_dispatch(self, p):
        "expr : OBJECTID '(' args_opt ')'"
        tok = p.slice[1]
        p[0] = ast.SelfDispatch(p[1], p[3], tok.line, tok.col)

    def p_expr_if(self, p):
        "expr : IF expr THEN expr ELSE expr FI"
        p[0] = ast.If(p[2], p[4], p[6], p.slice[1].line, p.slice[1].col)

    def p_expr_while(self, p):
        "expr : WHILE expr LOOP expr POOL"
        p[0] = ast.While(p[2], p[4], p.slice[1].line, p.slice[1].col)

    def p_expr_block(self, p):
        "expr : '{' block_list '}'"
        p[0] = ast.Block(p[2], p.slice[1].line, p.slice[1].col)

    def p_block_list_single(self, p):
        "block_list : expr ';'"
        p[0] = [p[1]]

    def p_block_list_more(self, p):
        "block_list : block_list expr ';'"
        p[0] = p[1] + [p[2]]

    def p_expr_let(self, p):
        "expr : LET let_decls IN expr"
        p[0] = ast.Let(p[2], p[4], p.slice[1].line, p.slice[1].col)

    def p_let_decls_single(self, p):
        "let_decls : let_decl"
        p[0] = [p[1]]

    def p_let_decls_more(self, p):
        "let_decls : let_decls ',' let_decl"
        p[0] = p[1] + [p[3]]

    def p_let_decl(self, p):
        "let_decl : OBJECTID ':' TYPEID init_opt"
        tok = p.slice[1]
        p[0] = ast.LetBinding(p[1], p[3], p[4], tok.line, tok.col)

    def p_expr_case(self, p):
        "expr : CASE expr OF case_branches ESAC"
        p[0] = ast.Case(p[2], p[4], p.slice[1].line, p.slice[1].col)

    def p_case_branches_single(self, p):
        "case_branches : case_branch"
        p[0] = [p[1]]

    def p_case_branches_more(self, p):
        "case_branches : case_branches case_branch"
        p[0] = p[1] + [p[2]]

    def p_case_branch(self, p):
        "case_branch : OBJECTID ':' TYPEID DARROW expr ';'"
        tok = p.slice[1]
        p[0] = ast.CaseBranch(p[1], p[3], p[5], tok.line, tok.col)

    def p_expr_new(self, p):
        "expr : NEW TYPEID"
        p[0] = ast.New(p[2], p.slice[1].line, p.slice[1].col)

    def p_expr_isvoid(self, p):
        "expr : ISVOID expr"
        p[0] = ast.IsVoid(p[2], p.slice[1].line, p.slice[1].col)

    def p_expr_binop(self, p):
        """expr : expr '+' expr
        | expr '-' expr
        | expr '*' expr
        | expr '/' expr
        | expr '<' expr
        | expr LE expr
        | expr '=' expr"""
        p[0] = ast.BinaryOp(p[2], p[1], p[3], p.slice[2].line, p.slice[2].col)

    def p_expr_neg(self, p):
        "expr : '~' expr"
        p[0] = ast.UnaryOp("~", p[2], p.slice[1].line, p.slice[1].col)

    def p_expr_not(self, p):
        "expr : NOT expr"
        p[0] = ast.UnaryOp("not", p[2], p.slice[1].line, p.slice[1].col)

    def p_expr_paren(self, p):
        "expr : '(' expr ')'"
        p[0] = p[2]

    def p_expr_object(self, p):
        "expr : OBJECTID"
        tok = p.slice[1]
        p[0] = ast.Identifier(p[1], tok.line, tok.col)

    def p_expr_int(self, p):
        "expr : INT_CONST"
        tok = p.slice[1]
        p[0] = ast.Integer(p[1], tok.line, tok.col)

    def p_expr_str(self, p):
        "expr : STR_CONST"
        tok = p.slice[1]
        p[0] = ast.String(p[1], tok.line, tok.col)

    def p_expr_bool(self, p):
        "expr : BOOL_CONST"
        tok = p.slice[1]
        p[0] = ast.Boolean(p[1], tok.line, tok.col)

    def p_args_opt_empty(self, p):
        "args_opt :"
        p[0] = []

    def p_args_opt(self, p):
        "args_opt : arg_list"
        p[0] = p[1]

    def p_arg_list_single(self, p):
        "arg_list : expr"
        p[0] = [p[1]]

    def p_arg_list_more(self, p):
        "arg_list : arg_list ',' expr"
        p[0] = p[1] + [p[3]]

    def p_error(self, p):
        if p is None:
            line, col, near = 0, 0, "EOF"
        else:
            line = getattr(p, "line", 0)
            col = getattr(p, "col", 0)
            near = token_text(p)
        self.errors.add(line, col, "SyntacticError", f'ERROR at or near "{near}"')
        raise ParseError()

    def __init__(self):
        self.errors = ErrorCollection()
        self.parser = yacc.yacc(module=self, write_tables=False, debug=False, errorlog=_silent)

    def parse(self, tokens):
        self.errors = ErrorCollection()
        stream = _TokenStream(tokens)
        try:
            result = self.parser.parse("", lexer=stream)
        except ParseError:
            return None
        return result


class _TokenStream:
    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0

    def token(self):
        if self.i < len(self.tokens):
            t = self.tokens[self.i]
            self.i += 1
            return t
        return None

    # PLY may call ``input``; provide a no-op for safety.
    def input(self, *_args, **_kwargs):
        pass


# Silence PLY's noisy parser-table warnings (e.g. the unavoidable
# shift/reduce conflict produced by the single-token-lookahead of `let`).
_logger = logging.getLogger("ply")
_logger.addHandler(logging.NullHandler())
_logger.setLevel(logging.CRITICAL)
_silent = _logger


_parser_singleton: Parser | None = None


def parse(tokens):
    global _parser_singleton
    if _parser_singleton is None:
        _parser_singleton = Parser()
    return _parser_singleton.parse(tokens), _parser_singleton.errors
