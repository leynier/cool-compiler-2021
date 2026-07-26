"""COOL lexer built on top of PLY.

Handles all lexical rules of COOL: integers, identifiers, special notation,
strings (with escape sequences and error handling), nested comments, and
keywords (case-insensitive except for ``true``/``false``).

Positions are tracked via a precomputed list of line starts so that an exact
``(line, column)`` pair (1-based) can be reported for any byte offset.
"""

from __future__ import annotations

import bisect
import re
from typing import Any

import ply.lex as lex

from .errors import ErrorCollection

# Keywords (case-insensitive). ``true``/``false`` are handled separately
# because their first letter must be lowercase.
RESERVED: dict[str, str] = {
    "class": "CLASS",
    "else": "ELSE",
    "fi": "FI",
    "if": "IF",
    "in": "IN",
    "inherits": "INHERITS",
    "isvoid": "ISVOID",
    "let": "LET",
    "loop": "LOOP",
    "pool": "POOL",
    "then": "THEN",
    "while": "WHILE",
    "case": "CASE",
    "esac": "ESAC",
    "new": "NEW",
    "of": "OF",
    "not": "NOT",
}

TRUE_RE = re.compile(r"t[rR][uU][eE]")
FALSE_RE = re.compile(r"f[aA][lL][sS][eE]")

SPECIAL_ESCAPES: dict[str, str] = {"b": "\b", "t": "\t", "n": "\n", "f": "\f"}


class CoolLexer:
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
    ) + tuple(sorted(set(RESERVED.values())))

    literals = "+-*/<=>~.,;:(){}@"

    states = (
        ("string", "exclusive"),
        ("comment", "exclusive"),
    )

    # --- top-level (INITIAL) rules ----------------------------------------

    def t_LE(self, t):
        r"<="
        return t

    def t_ASSIGN(self, t):
        r"<-"
        return t

    def t_DARROW(self, t):
        r"=>"
        return t

    def t_INT_CONST(self, t):
        r"[0-9]+"
        t.value = int(t.value)
        return t

    def t_TYPEID(self, t):
        r"[A-Z][a-zA-Z0-9_]*"
        low = t.value.lower()
        if low in RESERVED:
            t.type = RESERVED[low]
        return t

    def t_OBJECTID(self, t):
        r"[a-z][a-zA-Z0-9_]*"
        v = t.value
        if TRUE_RE.fullmatch(v):
            t.type = "BOOL_CONST"
            t.value = True
        elif FALSE_RE.fullmatch(v):
            t.type = "BOOL_CONST"
            t.value = False
        else:
            low = v.lower()
            if low in RESERVED:
                t.type = RESERVED[low]
        return t

    def t_line_comment(self, t):
        r"--[^\n]*"
        # Line comment: ignored.
        pass

    def t_block_comment_open(self, t):
        r"\(\*"
        self.comment_depth = 1
        t.lexer.begin("comment")

    def t_begin_string(self, t):
        r"\""
        self.string_buf: list[str] = []
        t.lexer.begin("string")

    def t_newline(self, t):
        r"\n+"
        t.lexer.lineno += len(t.value)

    def t_whitespace(self, t):
        r"[ \t\r\f\v]+"
        pass

    def t_error(self, t):
        # Unmatched character: record a lexicographic error and skip it.
        c = t.value[0]
        line, col = self.pos_at(t.lexpos)
        self.errors.add(line, col, "LexicographicError", f'ERROR "{c}"')
        t.lexer.skip(1)

    # --- string state -----------------------------------------------------

    def t_string_end(self, t):
        r"\""
        t.type = "STR_CONST"
        t.value = "".join(self.string_buf)
        t.lexer.begin("INITIAL")
        return t

    def t_string_special_escape(self, t):
        r"\\[btnf]"
        self.string_buf.append(SPECIAL_ESCAPES[t.value[1]])

    def t_string_escape_newline(self, t):
        r"\\\n"
        self.string_buf.append("\n")
        t.lexer.lineno += 1

    def t_string_escape_other(self, t):
        r"\\."
        self.string_buf.append(t.value[1])

    def t_string_null(self, t):
        r"\x00"
        line, col = self.pos_at(t.lexpos)
        self.errors.add(line, col, "LexicographicError", "String contains null character")
        # Skip the null byte but keep building the rest of the string.
        t.lexer.skip(1)

    def t_string_newline(self, t):
        r"\n"
        # A non-escaped newline may not appear in a string.
        line, col = self.pos_at(t.lexpos)
        self.errors.add(line, col, "LexicographicError", "Unterminated string constant")
        t.lexer.lineno += 1
        t.lexer.begin("INITIAL")

    def t_string_char(self, t):
        r"[^\\\"\n\x00]"
        self.string_buf.append(t.value)

    def t_string_error(self, t):
        # Should not happen; skip defensively.
        t.lexer.skip(1)

    # --- comment state ----------------------------------------------------

    def t_comment_open(self, t):
        r"\(\*"
        self.comment_depth += 1

    def t_comment_close(self, t):
        r"\*\)"
        self.comment_depth -= 1
        if self.comment_depth == 0:
            t.lexer.begin("INITIAL")

    def t_comment_newline(self, t):
        r"\n+"
        t.lexer.lineno += len(t.value)

    def t_comment_any(self, t):
        r"[^\n]"
        pass

    def t_comment_error(self, t):
        t.lexer.skip(1)

    # --- construction & helpers ------------------------------------------

    def __init__(self, **kwargs):
        self.lexer = lex.lex(module=self, **kwargs)
        self.errors = ErrorCollection()
        self.comment_depth = 0
        self.string_buf = []
        self._input = ""
        self.line_starts: list[int] = [0]

    def pos_at(self, offset: int) -> tuple[int, int]:
        idx = bisect.bisect_right(self.line_starts, offset) - 1
        if idx < 0:
            idx = 0
        line = idx + 1
        col = offset - self.line_starts[idx] + 1
        return line, col

    def input(self, data: str):
        self._input = data
        self.line_starts = [0]
        for i, c in enumerate(data):
            if c == "\n":
                self.line_starts.append(i + 1)
        self.lexer.lineno = 1
        self.comment_depth = 0
        self.string_buf = []
        self.errors = ErrorCollection()
        self.lexer.begin("INITIAL")
        self.lexer.input(data)

    def tokenize(self) -> list[Any]:
        tokens: list[Any] = []
        while True:
            tok = self.lexer.token()
            if tok is None:
                break
            line, col = self.pos_at(tok.lexpos)
            tok.line = line
            tok.col = col
            tokens.append(tok)

        state = self.lexer.current_state()
        if state == "comment":
            line, col = self.pos_at(len(self._input))
            self.errors.add(line, col, "LexicographicError", "EOF in comment")
        elif state == "string":
            line, col = self.pos_at(len(self._input))
            self.errors.add(line, col, "LexicographicError", "EOF in string constant")
        return tokens


def tokenize(source: str):
    """Run the lexer; return ``(tokens, errors)``."""
    lx = CoolLexer()
    lx.input(source)
    tokens = lx.tokenize()
    return tokens, lx.errors
