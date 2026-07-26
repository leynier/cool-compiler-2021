"""Semantic analyser and type checker for COOL.

The analyser performs:

1. Class registration (duplicates, basic-class redefinition).
2. Inheritance checks (undefined / illegal parents, cycles).
3. Per-class feature checks (attribute/method redefinition, formal-parameter
   duplication, override-signature rules, ``self`` restrictions).
4. Type checking of every expression.

Errors are collected in an :class:`~src.errors.ErrorCollection`.  Since the
test-suite only validates the *first* error's line and type, we gather all
detected errors and let the collection sort them by position.
"""

from __future__ import annotations

from . import ast
from .errors import ErrorCollection

SELF_TYPE = "SELF_TYPE"

BASIC_CLASSES = {"Object", "IO", "Int", "String", "Bool"}
NO_INHERIT = {"Int", "String", "Bool"}


# (formal_types, return_type) for the predefined methods of basic classes.
BASIC_METHODS: dict[str, dict[str, tuple[list[str], str]]] = {
    "Object": {
        "abort": ([], "Object"),
        "type_name": ([], "String"),
        "copy": ([], SELF_TYPE),
    },
    "IO": {
        "out_string": (["String"], SELF_TYPE),
        "out_int": (["Int"], SELF_TYPE),
        "in_string": ([], "String"),
        "in_int": ([], "Int"),
    },
    "String": {
        "length": ([], "Int"),
        "concat": (["String"], "String"),
        "substr": (["Int", "Int"], "String"),
    },
    "Int": {},
    "Bool": {},
}

BASIC_PARENT = {
    "Object": None,
    "IO": "Object",
    "Int": "Object",
    "String": "Object",
    "Bool": "Object",
}


class MethodInfo:
    __slots__ = ("name", "formals", "return_type", "line", "col", "defined_in", "body")

    def __init__(self, name, formals, return_type, line, col, defined_in, body):
        self.name = name
        self.formals = formals  # list of (name, type)
        self.return_type = return_type
        self.line = line
        self.col = col
        self.defined_in = defined_in
        self.body = body


class AttrInfo:
    __slots__ = ("name", "type", "init", "line", "col", "defined_in")

    def __init__(self, name, type, init, line, col, defined_in):
        self.name = name
        self.type = type
        self.init = init
        self.line = line
        self.col = col
        self.defined_in = defined_in


class ClassInfo:
    __slots__ = (
        "name",
        "parent",
        "node",
        "own_attrs",
        "own_methods",
        "all_attrs",
        "all_methods",
        "valid",
    )

    def __init__(self, name, parent, node):
        self.name = name
        self.parent = parent
        self.node = node
        self.own_attrs: list[AttrInfo] = []
        self.own_methods: dict[str, MethodInfo] = {}
        self.all_attrs: dict[str, AttrInfo] = {}
        self.all_methods: dict[str, MethodInfo] = {}
        self.valid = True


class Checker:
    def __init__(self, program: ast.Program):
        self.program = program
        self.errors = ErrorCollection()
        self.classes: dict[str, ClassInfo] = {}
        self.source_order: list[str] = []
        self.source_index: dict[str, int] = {}

    # --- helpers ----------------------------------------------------------

    def is_defined(self, name: str) -> bool:
        return name in self.classes or name in BASIC_CLASSES

    def parent_of(self, name: str):
        if name in self.classes:
            return self.classes[name].parent or "Object"
        return BASIC_PARENT.get(name)

    def is_subclass(self, sub, sup) -> bool:
        """True iff ``sub`` conforms to ``sup`` (both concrete class names)."""
        if sub == sup:
            return True
        cur = sub
        seen = set()
        while cur is not None:
            if cur == sup:
                return True
            if cur in seen:
                return False
            seen.add(cur)
            cur = self.parent_of(cur)
        return False

    def conforms(self, sub, sup, current) -> bool:
        if sub == SELF_TYPE:
            sub = current
        if sup == SELF_TYPE:
            sup = current
        if sub == SELF_TYPE or sup == SELF_TYPE:
            return sub == sup
        return self.is_subclass(sub, sup)

    def join(self, t1, t2, current) -> str:
        if t1 == SELF_TYPE:
            t1 = current
        if t2 == SELF_TYPE:
            t2 = current
        ancestors = set()
        cur = t1
        seen = set()
        while cur is not None and cur not in seen:
            ancestors.add(cur)
            seen.add(cur)
            cur = self.parent_of(cur)
        cur = t2
        seen = set()
        while cur is not None and cur not in seen:
            if cur in ancestors:
                return cur
            seen.add(cur)
            cur = self.parent_of(cur)
        return "Object"

    def method_signature(self, class_name, method_name):
        """Return ``(formal_types, return_type, method_info)`` or ``None``."""
        # search the class and its ancestors
        cur = class_name
        seen = set()
        while cur is not None and cur not in seen:
            seen.add(cur)
            if cur in self.classes:
                info = self.classes[cur]
                if method_name in info.all_methods:
                    m = info.all_methods[method_name]
                    return ([t for _, t in m.formals], m.return_type, m)
            elif cur in BASIC_METHODS and method_name in BASIC_METHODS[cur]:
                ft, rt = BASIC_METHODS[cur][method_name]
                return (ft, rt, None)
            cur = self.parent_of(cur)
        return None

    # --- phase 1: register classes ---------------------------------------

    def register_classes(self):
        seen = {}
        for cls in self.program.classes:
            name = cls.name
            if name in BASIC_CLASSES:
                self.errors.add(
                    cls.line, cls.col, "SemanticError", f"Redefinition of basic class {name}."
                )
                self.classes[name] = ClassInfo(name, cls.parent, cls)
                self.classes[name].valid = False
                continue
            if name in seen:
                self.errors.add(cls.line, cls.col, "SemanticError", "Classes may not be redefined")
                # keep the first definition; skip the duplicate
                self.classes[name].valid = False
                continue
            seen[name] = cls
            info = ClassInfo(name, cls.parent, cls)
            self.classes[name] = info
            self.source_order.append(name)
            self.source_index[name] = len(self.source_order) - 1

    # --- phase 2: inheritance checks -------------------------------------

    def check_inheritance(self):
        # undefined / illegal parents
        for name in self.source_order:
            info = self.classes[name]
            parent = info.parent
            if parent is None:
                continue
            if parent in NO_INHERIT:
                self.errors.add(
                    info.node.line,
                    info.node.col,
                    "SemanticError",
                    f"Class {name} cannot inherit class {parent}.",
                )
                info.valid = False
                continue
            if parent == SELF_TYPE:
                self.errors.add(
                    info.node.line,
                    info.node.col,
                    "SemanticError",
                    f"Class {name} cannot inherit class {parent}.",
                )
                info.valid = False
                continue
            if not self.is_defined(parent):
                self.errors.add(
                    info.node.line,
                    info.node.col,
                    "TypeError",
                    f"Class {name} inherits from an undefined class {parent}.",
                )
                info.parent = "Object"
                info.valid = False

        # cycles: report each cycle once, at its last source-ordered member
        reported: set[frozenset] = set()
        for name in self.source_order:
            cycle = self.find_cycle(name)
            if cycle is None:
                continue
            key = frozenset(cycle)
            if key in reported:
                continue
            reported.add(key)
            last = max(cycle, key=lambda c: self.source_index.get(c, 0))
            last_info = self.classes[last]
            self.errors.add(
                last_info.node.line,
                last_info.node.col,
                "SemanticError",
                f"Class {last}, or an ancestor of {last}, is involved in an inheritance cycle.",
            )
            for c in cycle:
                self.classes[c].valid = False

    def find_cycle(self, name):
        """Return the set of classes forming the cycle reachable from ``name``."""
        path = []
        seen = {}
        cur = name
        while cur is not None:
            if cur in seen:
                idx = path.index(cur) if cur in path else 0
                return set(path[idx:]) if cur in path else {cur}
            if cur not in self.classes and cur not in BASIC_CLASSES:
                return None
            if cur in BASIC_CLASSES:
                return None
            seen[cur] = len(path)
            path.append(cur)
            cur = self.classes[cur].parent
        return None

    # --- phase 3: features -----------------------------------------------

    def collect_features(self):
        for name in self.source_order:
            info = self.classes[name]
            self.collect_one_class(info)

    def collect_one_class(self, info: ClassInfo):
        cls = info.node
        own_attr_names: set[str] = set()
        own_method_names: set[str] = set()
        for feat in cls.features:
            if isinstance(feat, ast.Method):
                self.collect_method(info, feat, own_method_names)
            elif isinstance(feat, ast.Attribute):
                self.collect_attribute(info, feat, own_attr_names)

    def collect_method(self, info: ClassInfo, m: ast.Method, seen: set):
        if m.name in seen:
            self.errors.add(m.line, m.col, "SemanticError", f"Method {m.name} is multiply defined.")
            return
        seen.add(m.name)
        # formal parameter distinctness & 'self' restriction
        formal_names: set[str] = set()
        for f in m.formals:
            if f.name == "self":
                self.errors.add(
                    m.line,
                    m.col,
                    "SemanticError",
                    "'self' cannot be the name of a formal parameter.",
                )
            if f.name in formal_names:
                self.errors.add(
                    f.line,
                    f.col,
                    "SemanticError",
                    f"Formal parameter {f.name} is multiply defined.",
                )
            else:
                formal_names.add(f.name)
            if not self.is_defined(f.type):
                self.errors.add(
                    f.line,
                    f.col,
                    "TypeError",
                    f"Class {f.type} of formal parameter {f.name} is undefined.",
                )
        # return type
        if m.return_type != SELF_TYPE and not self.is_defined(m.return_type):
            self.errors.add(
                m.line,
                m.col,
                "TypeError",
                f"Undefined return type {m.return_type} in method {m.name}.",
            )
        formals = [(f.name, f.type) for f in m.formals]
        method = MethodInfo(m.name, formals, m.return_type, m.line, m.col, info.name, m.body)
        info.own_methods[m.name] = method

    def collect_attribute(self, info: ClassInfo, a: ast.Attribute, seen: set):
        if a.name == "self":
            self.errors.add(
                a.line, a.col, "SemanticError", "'self' cannot be the name of an attribute."
            )
            return
        if a.name in seen:
            self.errors.add(
                a.line, a.col, "SemanticError", f"Attribute {a.name} is multiply defined in class."
            )
            return
        seen.add(a.name)
        if a.type != SELF_TYPE and not self.is_defined(a.type):
            self.errors.add(
                a.line, a.col, "TypeError", f"Class {a.type} of attribute {a.name} is undefined."
            )
        info.own_attrs.append(AttrInfo(a.name, a.type, a.init, a.line, a.col, info.name))

    # --- build full attribute / method tables ----------------------------

    def build_tables(self):
        built: set[str] = set()

        def ensure(name, visiting):
            if name in built or name not in self.classes:
                return
            if name in visiting:
                # cycle -- bail out to avoid infinite recursion
                return
            visiting.add(name)
            info = self.classes[name]
            parent = info.parent or "Object"
            if parent in self.classes and parent not in visiting:
                ensure(parent, visiting)
            self.build_one_table(info)
            built.add(name)
            visiting.discard(name)

        for name in self.source_order:
            ensure(name, set())

    def build_one_table(self, info: ClassInfo):
        parent = info.parent or "Object"
        if parent in self.classes:
            pinfo = self.classes[parent]
            for n, a in pinfo.all_attrs.items():
                info.all_attrs[n] = a
            for n, m in pinfo.all_methods.items():
                info.all_methods[n] = m
        for a in info.own_attrs:
            if a.name in info.all_attrs:
                # redefinition of inherited attribute
                self.errors.add(
                    a.line,
                    a.col,
                    "SemanticError",
                    f"Attribute {a.name} is an attribute of an inherited class.",
                )
            else:
                info.all_attrs[a.name] = a
        for m in info.own_methods.values():
            if m.name in info.all_methods:
                inherited = info.all_methods[m.name]
                self.check_override(inherited, m)
            info.all_methods[m.name] = m

    def check_override(self, inherited: MethodInfo, redef: MethodInfo):
        if len(inherited.formals) != len(redef.formals):
            self.errors.add(
                redef.line,
                redef.col,
                "SemanticError",
                f"Incompatible number of formal parameters in redefined method {redef.name}.",
            )
            return
        for (_an, at), (_bn, bt) in zip(inherited.formals, redef.formals, strict=True):
            if at != bt:
                self.errors.add(
                    redef.line,
                    redef.col,
                    "SemanticError",
                    f"In redefined method {redef.name}, parameter type {bt} "
                    f"is different from original type {at}.",
                )
                return
        if inherited.return_type != redef.return_type:
            self.errors.add(
                redef.line,
                redef.col,
                "SemanticError",
                f"In redefined method {redef.name}, return type {redef.return_type} "
                f"is different from original return type {inherited.return_type}.",
            )

    # --- phase 4: type checking ------------------------------------------

    def attr_type_resolved(self, a: AttrInfo, current: str) -> str:
        return current if a.type == SELF_TYPE else a.type

    def check_expressions(self):
        for name in self.source_order:
            info = self.classes[name]
            self.check_class_expressions(info)

    def check_class_expressions(self, info: ClassInfo):
        # base environment: self + all attributes
        current = info.name
        base = {"self": SELF_TYPE}
        for n, a in info.all_attrs.items():
            base[n] = self.attr_type_resolved(a, current)
        # attribute initialisers
        for a in info.own_attrs:
            if a.init is not None:
                before = self.errors.count()
                t = self.check_expr(a.init, base, current)
                if before != self.errors.count():
                    continue
                declared = current if a.type == SELF_TYPE else a.type
                if declared in BASIC_CLASSES or declared in self.classes:
                    if not self.conforms(t, declared, current):
                        self.errors.add(
                            a.init.line,
                            a.init.col,
                            "TypeError",
                            f"Inferred type {t} of initialization of attribute {a.name} "
                            f"does not conform to declared type {declared}.",
                        )
        # method bodies
        for m in info.own_methods.values():
            self._check_method_return(info, m, base, current)

    def _check_method_return(self, info, m, base, current):
        env = {"self": SELF_TYPE}
        for n, a in info.all_attrs.items():
            env[n] = self.attr_type_resolved(a, current)
        for fname, ftype in m.formals:
            env[fname] = current if ftype == SELF_TYPE else ftype
        before = self.errors.count()
        t = self.check_expr(m.body, env, current)
        if before != self.errors.count():
            return
        declared = m.return_type
        if declared == SELF_TYPE:
            if not self.conforms(t, SELF_TYPE, current):
                self.errors.add(
                    m.body.line,
                    m.body.col,
                    "TypeError",
                    f"Inferred return type {t} of method {m.name} does not conform "
                    f"to declared return type {declared}.",
                )
        else:
            if declared in BASIC_CLASSES or declared in self.classes:
                if not self.conforms(t, declared, current):
                    self.errors.add(
                        m.body.line,
                        m.body.col,
                        "TypeError",
                        f"Inferred return type {t} of method {m.name} does not conform "
                        f"to declared return type {declared}.",
                    )

    def check_expr(self, e, env, current) -> str:
        t = self._dispatch(e, env, current)
        return t

    def _dispatch(self, e, env, current) -> str:
        if isinstance(e, ast.Integer):
            return "Int"
        if isinstance(e, ast.String):
            return "String"
        if isinstance(e, ast.Boolean):
            return "Bool"
        if isinstance(e, ast.Identifier):
            if e.name == "self":
                return SELF_TYPE
            if e.name in env:
                return env[e.name]
            self.errors.add(e.line, e.col, "NameError", f"Undeclared identifier {e.name}.")
            return "Object"
        if isinstance(e, ast.Assign):
            return self.check_assign(e, env, current)
        if isinstance(e, ast.SelfDispatch):
            return self.check_dispatch(e, env, current, SELF_TYPE, None)
        if isinstance(e, ast.Dispatch):
            return self.check_dispatch(e, env, current, None, e.callee)
        if isinstance(e, ast.StaticDispatch):
            return self.check_static_dispatch(e, env, current)
        if isinstance(e, ast.If):
            return self.check_if(e, env, current)
        if isinstance(e, ast.While):
            return self.check_while(e, env, current)
        if isinstance(e, ast.Block):
            return self.check_block(e, env, current)
        if isinstance(e, ast.Let):
            return self.check_let(e, env, current)
        if isinstance(e, ast.Case):
            return self.check_case(e, env, current)
        if isinstance(e, ast.New):
            return self.check_new(e, env, current)
        if isinstance(e, ast.IsVoid):
            self.check_expr(e.expr, env, current)
            return "Bool"
        if isinstance(e, ast.BinaryOp):
            return self.check_binop(e, env, current)
        if isinstance(e, ast.UnaryOp):
            return self.check_unop(e, env, current)
        return "Object"

    def check_assign(self, e: ast.Assign, env, current) -> str:
        if e.name == "self":
            self.errors.add(e.line, e.col, "SemanticError", "Cannot assign to 'self'.")
            self.check_expr(e.expr, env, current)
            return SELF_TYPE
        if e.name not in env:
            self.errors.add(e.line, e.col, "NameError", f"Undeclared identifier {e.name}.")
            self.check_expr(e.expr, env, current)
            return "Object"
        declared = env[e.name]
        before = self.errors.count()
        t = self.check_expr(e.expr, env, current)
        if before == self.errors.count() and not self.conforms(t, declared, current):
            self.errors.add(
                e.line,
                e.col,
                "TypeError",
                f"Inferred type {t} of assignment to {e.name} does not conform "
                f"to declared type {declared}.",
            )
        return t

    def check_block(self, e: ast.Block, env, current) -> str:
        result = "Object"
        for sub in e.exprs:
            result = self.check_expr(sub, env, current)
        return result

    def check_if(self, e: ast.If, env, current) -> str:
        before = self.errors.count()
        ct = self.check_expr(e.cond, env, current)
        if ct != "Bool" and before == self.errors.count():
            self.errors.add(
                e.line, e.col, "TypeError", "Predicate of 'if' does not have type Bool."
            )
        tt = self.check_expr(e.then, env, current)
        et = self.check_expr(e.els, env, current)
        return self.join(tt, et, current)

    def check_while(self, e: ast.While, env, current) -> str:
        before = self.errors.count()
        ct = self.check_expr(e.cond, env, current)
        if ct != "Bool" and before == self.errors.count():
            self.errors.add(e.line, e.col, "TypeError", "Loop condition does not have type Bool.")
        self.check_expr(e.body, env, current)
        return "Object"

    def check_let(self, e: ast.Let, env, current) -> str:
        local = dict(env)
        for b in e.bindings:
            if b.name == "self":
                self.errors.add(
                    b.line, b.col, "SemanticError", "'self' cannot be bound in a 'let' expression."
                )
            declared = current if b.type == SELF_TYPE else b.type
            if b.type != SELF_TYPE and not self.is_defined(b.type):
                self.errors.add(
                    b.line,
                    b.col,
                    "TypeError",
                    f"Class {b.type} of let-bound identifier {b.name} is undefined.",
                )
            if b.init is not None:
                before = self.errors.count()
                it = self.check_expr(b.init, local, current)
                ok = before == self.errors.count()
                if ok and (declared in BASIC_CLASSES or declared in self.classes):
                    if not self.conforms(it, declared, current):
                        self.errors.add(
                            b.init.line,
                            b.init.col,
                            "TypeError",
                            f"Inferred type {it} of initialization of {b.name} does not "
                            f"conform to identifier's declared type {declared}.",
                        )
            local[b.name] = declared
        return self.check_expr(e.body, local, current)

    def check_case(self, e: ast.Case, env, current) -> str:
        self.check_expr(e.expr, env, current)
        seen_types: set[str] = set()
        result = None
        for br in e.branches:
            if br.type != SELF_TYPE and not self.is_defined(br.type):
                self.errors.add(
                    br.line, br.col, "TypeError", f"Class {br.type} of case branch is undefined."
                )
            if br.type in seen_types:
                self.errors.add(
                    br.line,
                    br.col,
                    "SemanticError",
                    f"Duplicate branch {br.type} in case statement.",
                )
            seen_types.add(br.type)
            local = dict(env)
            local[br.name] = current if br.type == SELF_TYPE else br.type
            bt = self.check_expr(br.expr, local, current)
            result = bt if result is None else self.join(result, bt, current)
        return result if result is not None else "Object"

    def check_new(self, e: ast.New, env, current) -> str:
        t = e.type
        if t == SELF_TYPE:
            return SELF_TYPE
        if not self.is_defined(t):
            self.errors.add(e.line, e.col, "TypeError", f"'new' used with undefined class {t}.")
        return t

    def check_binop(self, e: ast.BinaryOp, env, current) -> str:
        before = self.errors.count()
        lt = self.check_expr(e.left, env, current)
        rt = self.check_expr(e.right, env, current)
        if before != self.errors.count():
            return "Int" if e.op in ("+", "-", "*", "/") else "Bool"
        op = e.op
        if op in ("+", "-", "*", "/"):
            if lt != "Int" or rt != "Int":
                self.errors.add(e.line, e.col, "TypeError", f"non-Int arguments: {lt} {op} {rt}")
            return "Int"
        if op in ("<", "<="):
            if lt != "Int" or rt != "Int":
                self.errors.add(e.line, e.col, "TypeError", f"non-Int arguments: {lt} {op} {rt}")
            return "Bool"
        basics = {"Int", "String", "Bool"}
        if lt in basics or rt in basics:
            if lt != rt:
                self.errors.add(e.line, e.col, "TypeError", "Illegal comparison with a basic type.")
        return "Bool"

    def check_unop(self, e: ast.UnaryOp, env, current) -> str:
        t = self.check_expr(e.expr, env, current)
        if e.op == "~":
            if t != "Int":
                self.errors.add(
                    e.line, e.col, "TypeError", f"Argument of '~' has type {t} instead of Int."
                )
            return "Int"
        # not
        if t != "Bool":
            self.errors.add(
                e.line, e.col, "TypeError", f"Argument of 'not' has type {t} instead of Bool."
            )
        return "Bool"

    def check_dispatch(self, e, env, current, callee_self, callee_expr) -> str:
        if callee_self is not None:
            t0 = SELF_TYPE
            lookup = current
        else:
            t0 = self.check_expr(callee_expr, env, current)
            lookup = current if t0 == SELF_TYPE else t0
        return self.finish_dispatch(e.line, e.col, e.method, e.args, lookup, t0, env, current)

    def check_static_dispatch(self, e: ast.StaticDispatch, env, current) -> str:
        t0 = self.check_expr(e.callee, env, current)
        static_type = e.static_type
        if not self.is_defined(static_type):
            self.errors.add(
                e.line, e.col, "TypeError", f"Static dispatch to undefined class {static_type}."
            )
        else:
            t0_resolved = current if t0 == SELF_TYPE else t0
            if not self.conforms(t0_resolved, static_type, current):
                self.errors.add(
                    e.line,
                    e.col,
                    "TypeError",
                    f"Expression type {t0_resolved} does not conform to declared "
                    f"static dispatch type {static_type}.",
                )
        return self.finish_dispatch(e.line, e.col, e.method, e.args, static_type, t0, env, current)

    def finish_dispatch(self, line, col, method_name, args, lookup_class, t0_raw, env, current):
        sig = self.method_signature(lookup_class, method_name)
        arg_types = [self.check_expr(a, env, current) for a in args]
        if sig is None:
            self.errors.add(
                line, col, "AttributeError", f"Dispatch to undefined method {method_name}."
            )
            return "Object"
        formal_types, return_type, _info = sig
        if len(formal_types) != len(args):
            self.errors.add(
                line,
                col,
                "SemanticError",
                f"Method {method_name} called with wrong number of arguments.",
            )
        else:
            for i, (at, ft) in enumerate(zip(arg_types, formal_types, strict=True)):
                if not self.conforms(at, ft, current):
                    # find the formal name if available
                    fname = f"arg{i}"
                    minfo = self.method_signature(lookup_class, method_name)
                    if minfo and minfo[2] is not None and i < len(minfo[2].formals):
                        fname = minfo[2].formals[i][0]
                    self.errors.add(
                        line,
                        col,
                        "TypeError",
                        f"In call of method {method_name}, type {at} of parameter {fname} "
                        f"does not conform to declared type {ft}.",
                    )
        if return_type == SELF_TYPE:
            return t0_raw
        return return_type

    # --- entry point ------------------------------------------------------

    def check_main(self):
        info = self.classes.get("Main")
        if info is None:
            self.errors.add(0, 0, "SemanticError", "Class Main is not defined.")
            return
        method = info.own_methods.get("main")
        if method is None:
            self.errors.add(
                info.node.line,
                info.node.col,
                "SemanticError",
                "No 'main' method in class Main.",
            )
        elif method.formals:
            self.errors.add(
                method.line,
                method.col,
                "SemanticError",
                "'main' method in class Main should have no arguments.",
            )

    def check(self) -> ErrorCollection:
        self.register_classes()
        self.check_inheritance()
        self.collect_features()
        self.build_tables()
        self.check_expressions()
        if not self.errors.has_errors():
            self.check_main()
        return self.errors


def check(program: ast.Program):
    c = Checker(program)
    return c.check()
