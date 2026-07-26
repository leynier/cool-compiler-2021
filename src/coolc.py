"""Command-line entry point for the COOL compiler."""

from __future__ import annotations

import sys
from pathlib import Path

from .codegen import generate
from .errors import ErrorCollection
from .lexer import tokenize
from .parser import parse
from .semantic import Checker


def report(errors: ErrorCollection) -> int:
    for line in errors.lines():
        print(line)
    return 1


def compile_file(input_path: Path, output_path: Path) -> int:
    if not input_path.is_file():
        errors = ErrorCollection()
        errors.add(0, 0, "CompilerError", f"Input file does not exist: {input_path}")
        return report(errors)

    try:
        source = input_path.read_text(encoding="utf-8")
    except OSError as exc:
        errors = ErrorCollection()
        errors.add(0, 0, "CompilerError", str(exc))
        return report(errors)

    tokens, lexical_errors = tokenize(source)
    if lexical_errors.has_errors():
        return report(lexical_errors)

    program, syntax_errors = parse(tokens)
    if syntax_errors.has_errors() or program is None:
        return report(syntax_errors)

    checker = Checker(program)
    semantic_errors = checker.check()
    if semantic_errors.has_errors():
        return report(semantic_errors)

    try:
        output_path.write_text(generate(program, checker), encoding="utf-8")
    except OSError as exc:
        errors = ErrorCollection()
        errors.add(0, 0, "CompilerError", str(exc))
        return report(errors)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        errors = ErrorCollection()
        errors.add(0, 0, "CompilerError", "No input file specified")
        return report(errors)
    input_path = Path(args[0])
    output_path = Path(args[1]) if len(args) > 1 else input_path.with_suffix(".mips")
    return compile_file(input_path, output_path)


if __name__ == "__main__":
    raise SystemExit(main())
