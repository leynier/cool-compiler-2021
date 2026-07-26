"""MIPS code generation for the COOL abstract syntax tree."""

from __future__ import annotations

from collections import defaultdict

from . import ast
from ._runtime_template import runtime_assembly
from .semantic import BASIC_CLASSES, Checker

BASIC_ORDER = ("Object", "IO", "Int", "Bool", "String")
BASIC_PARENT = {
    "Object": None,
    "IO": "Object",
    "Int": "Object",
    "Bool": "Object",
    "String": "Object",
}
BASIC_METHOD_LABELS = {
    "Object": {
        "abort": "Object.abort",
        "type_name": "Object.type_name",
        "copy": "Object.copy",
    },
    "IO": {
        "out_string": "IO.out_string",
        "out_int": "IO.out_int",
        "in_string": "IO.in_string",
        "in_int": "IO.in_int",
    },
    "Int": {},
    "Bool": {},
    "String": {
        "length": "String.length",
        "concat": "String.concat",
        "substr": "String.substr",
    },
}


class CodeGenerator:
    def __init__(self, program: ast.Program, checker: Checker):
        self.program = program
        self.checker = checker
        self.classes = {node.name: node for node in program.classes}
        self.parents = dict(BASIC_PARENT)
        self.parents.update({node.name: node.parent or "Object" for node in program.classes})
        self.children: dict[str, list[str]] = defaultdict(list)
        for name in BASIC_ORDER[1:]:
            self.children["Object"].append(name)
        for node in program.classes:
            self.children[node.parent or "Object"].append(node.name)

        self.class_order: list[str] = []
        self.tags: dict[str, int] = {}
        self.subtree_max: dict[str, int] = {}
        self._assign_tags("Object")
        self.depths = {name: self._class_depth(name) for name in self.class_order}

        self.method_names: list[str] = []
        for class_name in BASIC_ORDER:
            for method_name in BASIC_METHOD_LABELS[class_name]:
                self._add_method_name(method_name)
        for node in program.classes:
            for feature in node.features:
                if isinstance(feature, ast.Method):
                    self._add_method_name(feature.name)
        self.method_slots = {name: i for i, name in enumerate(self.method_names)}
        self.method_tables: dict[str, dict[str, str]] = {}
        self._build_method_tables()

        self.attr_layouts: dict[str, list] = {name: [] for name in BASIC_ORDER}
        self.attr_offsets: dict[str, dict[str, int]] = {name: {} for name in BASIC_ORDER}
        self._build_attribute_layouts()

        self.string_values: list[str] = []
        self.string_labels: dict[str, str] = {}
        for name in self.class_order:
            self._add_string(name)
        self._add_string("")
        self._collect_strings(program)

        self.lines: list[str] = []
        self.label_counter = 0
        self.stack_words = 0
        self.current_class = "Object"

    def _assign_tags(self, name: str):
        self.tags[name] = len(self.class_order)
        self.class_order.append(name)
        for child in self.children.get(name, []):
            self._assign_tags(child)
        self.subtree_max[name] = len(self.class_order) - 1

    def _class_depth(self, name: str) -> int:
        depth = 0
        while self.parents.get(name) is not None:
            depth += 1
            parent = self.parents[name]
            assert parent is not None
            name = parent
        return depth

    def _add_method_name(self, name: str):
        if name not in self.method_names:
            self.method_names.append(name)

    def _build_method_tables(self):
        for name in self.class_order:
            parent = self.parents.get(name)
            table = dict(self.method_tables[parent]) if parent else {}
            table.update(BASIC_METHOD_LABELS.get(name, {}))
            node = self.classes.get(name)
            if node:
                for feature in node.features:
                    if isinstance(feature, ast.Method):
                        table[feature.name] = f"{name}.{feature.name}"
            self.method_tables[name] = table

    def _build_attribute_layouts(self):
        for name in self.class_order:
            if name in BASIC_CLASSES:
                continue
            parent = self.parents[name]
            assert parent is not None
            layout = list(self.attr_layouts[parent])
            layout.extend(self.checker.classes[name].own_attrs)
            self.attr_layouts[name] = layout
            self.attr_offsets[name] = {attr.name: 12 + 4 * i for i, attr in enumerate(layout)}

    def _add_string(self, value: str):
        if value not in self.string_labels:
            label = f"str_const{len(self.string_values)}"
            self.string_labels[value] = label
            self.string_values.append(value)

    def _collect_strings(self, value):
        if isinstance(value, ast.String):
            self._add_string(value.value)
            return
        if isinstance(value, ast.Node):
            for cls in type(value).__mro__:
                for slot in getattr(cls, "__slots__", ()):
                    if slot not in {"line", "col"}:
                        self._collect_strings(getattr(value, slot))
        elif isinstance(value, (list, tuple)):
            for item in value:
                self._collect_strings(item)

    def new_label(self, prefix: str) -> str:
        self.label_counter += 1
        return f"{prefix}_{self.label_counter}"

    def emit(self, line: str = ""):
        self.lines.append(line)

    def push(self, register: str = "$a0") -> int:
        self.emit("\taddiu $sp $sp -4")
        self.emit(f"\tsw {register} 0($sp)")
        self.stack_words += 1
        return -4 * self.stack_words

    def pop(self, register: str):
        self.emit(f"\tlw {register} 0($sp)")
        self.emit("\taddiu $sp $sp 4")
        self.stack_words -= 1

    def generate(self) -> str:
        self._emit_data()
        self.emit(runtime_assembly(self.tags).strip())
        self._emit_entrypoint()
        self._emit_constructors()
        self._emit_methods()
        return "\n".join(self.lines) + "\n"

    def _emit_data(self):
        self.emit(".data")
        self.emit(".align 2")
        self.emit('abort_prefix: .asciiz "Abort called from class "')
        self.emit('newline_cstr: .asciiz "\\n"')
        self.emit('dispatch_abort_msg: .asciiz "Dispatch on void\\n"')
        self.emit('div_abort_msg: .asciiz "Division by zero\\n"')
        self.emit(".align 2")
        self.emit("input_buffer: .space 4096")
        self.emit(".align 2")

        for value in self.string_values:
            encoded = value.encode("utf-8")
            size_words = 4 + (len(encoded) + 1 + 3) // 4
            self.emit(f"{self.string_labels[value]}:")
            self.emit(f"\t.word {self.tags['String']}")
            self.emit(f"\t.word {size_words}")
            self.emit("\t.word String_dispTab")
            self.emit(f"\t.word {len(encoded)}")
            bytes_text = ", ".join(str(byte) for byte in encoded + b"\0")
            self.emit(f"\t.byte {bytes_text}")
            self.emit("\t.align 2")

        self.emit("int_const0:")
        self.emit(f"\t.word {self.tags['Int']}, 4, Int_dispTab, 0")
        self.emit("bool_const0:")
        self.emit(f"\t.word {self.tags['Bool']}, 4, Bool_dispTab, 0")
        self.emit("bool_const1:")
        self.emit(f"\t.word {self.tags['Bool']}, 4, Bool_dispTab, 1")

        self.emit("class_nameTab:")
        for name in self.class_order:
            self.emit(f"\t.word {self.string_labels[name]}")
        self.emit("class_newTab:")
        for name in self.class_order:
            self.emit(f"\t.word {name}_new")

        for name in self.class_order:
            self.emit(f"{name}_dispTab:")
            table = self.method_tables[name]
            for method_name in self.method_names:
                self.emit(f"\t.word {table.get(method_name, '_dispatch_abort')}")
        self.emit("")

    def _emit_entrypoint(self):
        main_slot = self.method_slots["main"] * 4
        self.emit(".globl main")
        self.emit("main:")
        self.emit("\tjal Main_new")
        self.emit("\taddiu $sp $sp -4")
        self.emit("\tsw $a0 0($sp)")
        self.emit("\tlw $t0 8($a0)")
        self.emit(f"\tlw $t1 {main_slot}($t0)")
        self.emit("\tjalr $t1")
        self.emit("\taddiu $sp $sp 4")
        self.emit("\tli $v0 10")
        self.emit("\tsyscall")
        self.emit("")

    def _default_label(self, type_name: str) -> str | None:
        if type_name == "Int":
            return "int_const0"
        if type_name == "Bool":
            return "bool_const0"
        if type_name == "String":
            return self.string_labels[""]
        return None

    def _emit_constructors(self):
        for name in self.class_order:
            attrs = self.attr_layouts.get(name, [])
            if name == "Int" or name == "Bool":
                size_words = 4
            elif name == "String":
                size_words = 5
            else:
                size_words = 3 + len(attrs)
            self.emit(f"{name}_new:")
            self.emit(f"\tli $a0 {size_words * 4}")
            self.emit("\tli $v0 9")
            self.emit("\tsyscall")
            self.emit("\tmove $t0 $v0")
            self.emit(f"\tli $t1 {self.tags[name]}")
            self.emit("\tsw $t1 0($t0)")
            self.emit(f"\tli $t1 {size_words}")
            self.emit("\tsw $t1 4($t0)")
            self.emit(f"\tla $t1 {name}_dispTab")
            self.emit("\tsw $t1 8($t0)")
            if name in {"Int", "Bool", "String"}:
                self.emit("\tsw $zero 12($t0)")
                if name == "String":
                    self.emit("\tsb $zero 16($t0)")
            else:
                for i, attr in enumerate(attrs):
                    label = self._default_label(attr.type)
                    offset = 12 + i * 4
                    if label:
                        self.emit(f"\tla $t1 {label}")
                        self.emit(f"\tsw $t1 {offset}($t0)")
                    else:
                        self.emit(f"\tsw $zero {offset}($t0)")
            self.emit("\taddiu $sp $sp -8")
            self.emit("\tsw $t0 0($sp)")
            self.emit("\tsw $ra 4($sp)")
            self.emit("\tmove $a0 $t0")
            self.emit(f"\tjal {name}_init")
            self.emit("\tlw $ra 4($sp)")
            self.emit("\taddiu $sp $sp 8")
            self.emit("\tjr $ra")
            self.emit("")

            self.emit(f"{name}_init:")
            self._prologue()
            parent = self.parents.get(name)
            if parent:
                self.emit("\tmove $a0 $s0")
                self.emit(f"\tjal {parent}_init")
            node = self.classes.get(name)
            if node:
                self.current_class = name
                self.stack_words = 0
                env: dict[str, int] = {}
                for feature in node.features:
                    if isinstance(feature, ast.Attribute) and feature.init is not None:
                        self.gen_expr(feature.init, env)
                        offset = self.attr_offsets[name][feature.name]
                        self.emit(f"\tsw $a0 {offset}($s0)")
            self.emit("\tmove $a0 $s0")
            self._epilogue()
            self.emit("")

    def _prologue(self):
        self.emit("\taddiu $sp $sp -12")
        self.emit("\tsw $fp 8($sp)")
        self.emit("\tsw $s0 4($sp)")
        self.emit("\tsw $ra 0($sp)")
        self.emit("\tmove $fp $sp")
        self.emit("\tmove $s0 $a0")

    def _epilogue(self):
        self.emit("\tmove $sp $fp")
        self.emit("\tlw $ra 0($sp)")
        self.emit("\tlw $s0 4($sp)")
        self.emit("\tlw $fp 8($sp)")
        self.emit("\taddiu $sp $sp 12")
        self.emit("\tjr $ra")

    def _emit_methods(self):
        for node in self.program.classes:
            self.current_class = node.name
            for feature in node.features:
                if not isinstance(feature, ast.Method):
                    continue
                self.emit(f"{node.name}.{feature.name}:")
                self._prologue()
                self.stack_words = 0
                count = len(feature.formals)
                env = {
                    formal.name: 12 + 4 * (count - 1 - i)
                    for i, formal in enumerate(feature.formals)
                }
                self.gen_expr(feature.body, env)
                self._epilogue()
                self.emit("")

    def _load_default(self, type_name: str):
        label = self._default_label(type_name)
        if label:
            self.emit(f"\tla $a0 {label}")
        else:
            self.emit("\tmove $a0 $zero")

    def _variable_offset(self, name: str, env: dict[str, int]):
        if name in env:
            return "$fp", env[name]
        return "$s0", self.attr_offsets[self.current_class][name]

    def gen_expr(self, expr, env: dict[str, int]):
        if isinstance(expr, ast.Integer):
            self.emit(f"\tli $a0 {expr.value}")
            self.emit("\tjal cool_box_int")
        elif isinstance(expr, ast.String):
            self.emit(f"\tla $a0 {self.string_labels[expr.value]}")
        elif isinstance(expr, ast.Boolean):
            self.emit(f"\tla $a0 bool_const{int(expr.value)}")
        elif isinstance(expr, ast.Identifier):
            if expr.name == "self":
                self.emit("\tmove $a0 $s0")
            else:
                base, offset = self._variable_offset(expr.name, env)
                self.emit(f"\tlw $a0 {offset}({base})")
        elif isinstance(expr, ast.Assign):
            self.gen_expr(expr.expr, env)
            base, offset = self._variable_offset(expr.name, env)
            self.emit(f"\tsw $a0 {offset}({base})")
        elif isinstance(expr, ast.Block):
            for item in expr.exprs:
                self.gen_expr(item, env)
        elif isinstance(expr, ast.If):
            else_label = self.new_label("if_else")
            end_label = self.new_label("if_end")
            self.gen_expr(expr.cond, env)
            self.emit("\tlw $t0 12($a0)")
            self.emit(f"\tbeq $t0 $zero {else_label}")
            self.gen_expr(expr.then, env)
            self.emit(f"\tj {end_label}")
            self.emit(f"{else_label}:")
            self.gen_expr(expr.els, env)
            self.emit(f"{end_label}:")
        elif isinstance(expr, ast.While):
            loop_label = self.new_label("loop")
            end_label = self.new_label("loop_end")
            self.emit(f"{loop_label}:")
            self.gen_expr(expr.cond, env)
            self.emit("\tlw $t0 12($a0)")
            self.emit(f"\tbeq $t0 $zero {end_label}")
            self.gen_expr(expr.body, env)
            self.emit(f"\tj {loop_label}")
            self.emit(f"{end_label}:")
            self.emit("\tmove $a0 $zero")
        elif isinstance(expr, ast.Let):
            self._gen_let(expr, env)
        elif isinstance(expr, ast.Case):
            self._gen_case(expr, env)
        elif isinstance(expr, ast.New):
            if expr.type == "SELF_TYPE":
                self.emit("\tlw $t0 0($s0)")
                self.emit("\tsll $t0 $t0 2")
                self.emit("\tla $t1 class_newTab")
                self.emit("\taddu $t1 $t1 $t0")
                self.emit("\tlw $t1 0($t1)")
                self.emit("\tjalr $t1")
            else:
                self.emit(f"\tjal {expr.type}_new")
        elif isinstance(expr, ast.IsVoid):
            self.gen_expr(expr.expr, env)
            true_label = self.new_label("isvoid_true")
            end_label = self.new_label("isvoid_end")
            self.emit(f"\tbeq $a0 $zero {true_label}")
            self.emit("\tla $a0 bool_const0")
            self.emit(f"\tj {end_label}")
            self.emit(f"{true_label}:")
            self.emit("\tla $a0 bool_const1")
            self.emit(f"{end_label}:")
        elif isinstance(expr, ast.BinaryOp):
            self._gen_binary(expr, env)
        elif isinstance(expr, ast.UnaryOp):
            self.gen_expr(expr.expr, env)
            self.emit("\tlw $t0 12($a0)")
            if expr.op == "~":
                self.emit("\tsubu $a0 $zero $t0")
                self.emit("\tjal cool_box_int")
            else:
                false_label = self.new_label("not_false")
                end_label = self.new_label("not_end")
                self.emit("\txori $t0 $t0 1")
                self.emit(f"\tbeq $t0 $zero {false_label}")
                self.emit("\tla $a0 bool_const1")
                self.emit(f"\tj {end_label}")
                self.emit(f"{false_label}:")
                self.emit("\tla $a0 bool_const0")
                self.emit(f"{end_label}:")
        elif isinstance(expr, ast.SelfDispatch):
            self._gen_dispatch(expr.method, expr.args, env, None, self.current_class, True)
        elif isinstance(expr, ast.Dispatch):
            self._gen_dispatch(expr.method, expr.args, env, expr.callee, None, True)
        elif isinstance(expr, ast.StaticDispatch):
            self._gen_dispatch(expr.method, expr.args, env, expr.callee, expr.static_type, False)

    def _gen_let(self, expr: ast.Let, env: dict[str, int]):
        local = dict(env)
        count = 0
        for binding in expr.bindings:
            if binding.init is None:
                self._load_default(binding.type)
            else:
                self.gen_expr(binding.init, local)
            local[binding.name] = self.push()
            count += 1
        self.gen_expr(expr.body, local)
        if count:
            self.emit(f"\taddiu $sp $sp {count * 4}")
            self.stack_words -= count

    def _gen_case(self, expr: ast.Case, env: dict[str, int]):
        self.gen_expr(expr.expr, env)
        self.emit("\tbeq $a0 $zero cool_dispatch_abort")
        value_offset = self.push()
        end_label = self.new_label("case_end")
        branches = sorted(expr.branches, key=lambda branch: self.depths[branch.type], reverse=True)
        for branch in branches:
            next_label = self.new_label("case_next")
            self.emit(f"\tlw $t0 {value_offset}($fp)")
            self.emit("\tlw $t0 0($t0)")
            self.emit(f"\tli $t1 {self.tags[branch.type]}")
            self.emit(f"\tblt $t0 $t1 {next_label}")
            self.emit(f"\tli $t1 {self.subtree_max[branch.type]}")
            self.emit(f"\tbgt $t0 $t1 {next_label}")
            local = dict(env)
            local[branch.name] = value_offset
            self.gen_expr(branch.expr, local)
            self.emit(f"\tj {end_label}")
            self.emit(f"{next_label}:")
        self.emit("\tj cool_dispatch_abort")
        self.emit(f"{end_label}:")
        self.emit("\taddiu $sp $sp 4")
        self.stack_words -= 1

    def _gen_binary(self, expr: ast.BinaryOp, env: dict[str, int]):
        self.gen_expr(expr.left, env)
        self.push()
        self.gen_expr(expr.right, env)
        self.pop("$t0")
        if expr.op == "=":
            self.emit("\tmove $a1 $a0")
            self.emit("\tmove $a0 $t0")
            self.emit("\tjal cool_equal")
            return
        self.emit("\tlw $t0 12($t0)")
        self.emit("\tlw $t1 12($a0)")
        if expr.op == "+":
            self.emit("\taddu $a0 $t0 $t1")
        elif expr.op == "-":
            self.emit("\tsubu $a0 $t0 $t1")
        elif expr.op == "*":
            self.emit("\tmul $a0 $t0 $t1")
        elif expr.op == "/":
            self.emit("\tbeq $t1 $zero cool_div_abort")
            self.emit("\tdiv $t0 $t1")
            self.emit("\tmflo $a0")
        else:
            true_label = self.new_label("compare_true")
            end_label = self.new_label("compare_end")
            instruction = "blt" if expr.op == "<" else "ble"
            self.emit(f"\t{instruction} $t0 $t1 {true_label}")
            self.emit("\tla $a0 bool_const0")
            self.emit(f"\tj {end_label}")
            self.emit(f"{true_label}:")
            self.emit("\tla $a0 bool_const1")
            self.emit(f"{end_label}:")
            return
        self.emit("\tjal cool_box_int")

    def _gen_dispatch(
        self,
        method: str,
        args: list,
        env: dict[str, int],
        callee,
        static_type: str | None,
        dynamic: bool,
    ):
        for arg in args:
            self.gen_expr(arg, env)
            self.push()
        if callee is None:
            self.emit("\tmove $a0 $s0")
        else:
            self.gen_expr(callee, env)
        self.emit("\tbeq $a0 $zero cool_dispatch_abort")
        if dynamic:
            self.emit("\tlw $t0 8($a0)")
            self.emit(f"\tlw $t1 {self.method_slots[method] * 4}($t0)")
            self.emit("\tjalr $t1")
        else:
            assert static_type is not None
            label = self.method_tables[static_type][method]
            self.emit(f"\tjal {label}")
        if args:
            self.emit(f"\taddiu $sp $sp {len(args) * 4}")
            self.stack_words -= len(args)


def generate(program: ast.Program, checker: Checker) -> str:
    return CodeGenerator(program, checker).generate()
