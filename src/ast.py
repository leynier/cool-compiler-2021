"""AST node definitions for COOL."""

from __future__ import annotations


class Node:
    __slots__ = ()


class Program(Node):
    __slots__ = ("classes",)

    def __init__(self, classes: list[ClassDecl]):
        self.classes = classes


class ClassDecl(Node):
    __slots__ = ("name", "parent", "features", "line", "col")

    def __init__(self, name: str, parent: str | None, features: list, line: int, col: int):
        self.name = name
        self.parent = parent
        self.features = features
        self.line = line
        self.col = col


class Method(Node):
    __slots__ = ("name", "formals", "return_type", "body", "line", "col")

    def __init__(self, name, formals, return_type, body, line, col):
        self.name = name
        self.formals = formals
        self.return_type = return_type
        self.body = body
        self.line = line
        self.col = col


class Attribute(Node):
    __slots__ = ("name", "type", "init", "line", "col")

    def __init__(self, name, type, init, line, col):
        self.name = name
        self.type = type
        self.init = init
        self.line = line
        self.col = col


class Formal(Node):
    __slots__ = ("name", "type", "line", "col")

    def __init__(self, name, type, line, col):
        self.name = name
        self.type = type
        self.line = line
        self.col = col


# --- Expressions --------------------------------------------------------


class Expr(Node):
    __slots__ = ("line", "col")

    def __init__(self, line: int, col: int):
        self.line = line
        self.col = col


class Assign(Expr):
    __slots__ = ("name", "expr")

    def __init__(self, name, expr, line, col):
        super().__init__(line, col)
        self.name = name
        self.expr = expr


class Dispatch(Expr):
    __slots__ = ("callee", "method", "args")

    def __init__(self, callee, method, args, line, col):
        super().__init__(line, col)
        self.callee = callee
        self.method = method
        self.args = args


class StaticDispatch(Expr):
    __slots__ = ("callee", "static_type", "method", "args")

    def __init__(self, callee, static_type, method, args, line, col):
        super().__init__(line, col)
        self.callee = callee
        self.static_type = static_type
        self.method = method
        self.args = args


class SelfDispatch(Expr):
    __slots__ = ("method", "args")

    def __init__(self, method, args, line, col):
        super().__init__(line, col)
        self.method = method
        self.args = args


class If(Expr):
    __slots__ = ("cond", "then", "els")

    def __init__(self, cond, then, els, line, col):
        super().__init__(line, col)
        self.cond = cond
        self.then = then
        self.els = els


class While(Expr):
    __slots__ = ("cond", "body")

    def __init__(self, cond, body, line, col):
        super().__init__(line, col)
        self.cond = cond
        self.body = body


class Block(Expr):
    __slots__ = ("exprs",)

    def __init__(self, exprs, line, col):
        super().__init__(line, col)
        self.exprs = exprs


class LetBinding(Node):
    __slots__ = ("name", "type", "init", "line", "col")

    def __init__(self, name, type, init, line, col):
        self.name = name
        self.type = type
        self.init = init
        self.line = line
        self.col = col


class Let(Expr):
    __slots__ = ("bindings", "body")

    def __init__(self, bindings, body, line, col):
        super().__init__(line, col)
        self.bindings = bindings
        self.body = body


class CaseBranch(Node):
    __slots__ = ("name", "type", "expr", "line", "col")

    def __init__(self, name, type, expr, line, col):
        self.name = name
        self.type = type
        self.expr = expr
        self.line = line
        self.col = col


class Case(Expr):
    __slots__ = ("expr", "branches")

    def __init__(self, expr, branches, line, col):
        super().__init__(line, col)
        self.expr = expr
        self.branches = branches


class New(Expr):
    __slots__ = ("type",)

    def __init__(self, type, line, col):
        super().__init__(line, col)
        self.type = type


class IsVoid(Expr):
    __slots__ = ("expr",)

    def __init__(self, expr, line, col):
        super().__init__(line, col)
        self.expr = expr


class BinaryOp(Expr):
    __slots__ = ("op", "left", "right")

    def __init__(self, op, left, right, line, col):
        super().__init__(line, col)
        self.op = op
        self.left = left
        self.right = right


class UnaryOp(Expr):
    __slots__ = ("op", "expr")

    def __init__(self, op, expr, line, col):
        super().__init__(line, col)
        self.op = op
        self.expr = expr


class Identifier(Expr):
    __slots__ = ("name",)

    def __init__(self, name, line, col):
        super().__init__(line, col)
        self.name = name


class Integer(Expr):
    __slots__ = ("value",)

    def __init__(self, value, line, col):
        super().__init__(line, col)
        self.value = value


class String(Expr):
    __slots__ = ("value",)

    def __init__(self, value, line, col):
        super().__init__(line, col)
        self.value = value


class Boolean(Expr):
    __slots__ = ("value",)

    def __init__(self, value, line, col):
        super().__init__(line, col)
        self.value = value
