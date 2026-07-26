"""Error model and collection for the COOL compiler."""


class CompilerError:
    __slots__ = ("line", "column", "error_type", "message")

    def __init__(self, line: int, column: int, error_type: str, message: str):
        self.line = line
        self.column = column
        self.error_type = error_type
        self.message = message

    def format(self) -> str:
        return f"({self.line}, {self.column}) - {self.error_type}: {self.message}"

    def sort_key(self):
        # Order by (line, column); keep insertion order on ties via an index.
        return (self.line, self.column)


# Phase priority used to break ties (lower comes first).
PHASE_PRIORITY = {
    "LexicographicError": 0,
    "SyntacticError": 1,
    "CompilerError": 2,
    "NameError": 3,
    "AttributeError": 3,
    "TypeError": 3,
    "SemanticError": 3,
}


class ErrorCollection:
    def __init__(self):
        self._items: list[tuple[CompilerError, int, int]] = []
        self._seq = 0

    def add(self, line: int, column: int, error_type: str, message: str):
        err = CompilerError(line, column, error_type, message)
        prio = PHASE_PRIORITY.get(error_type, 9)
        self._items.append((err, prio, self._seq))
        self._seq += 1

    def has_errors(self) -> bool:
        return bool(self._items)

    def count(self) -> int:
        return len(self._items)

    def sorted(self) -> list[CompilerError]:
        return [
            e for e, _prio, _seq in sorted(self._items, key=lambda t: (t[0].sort_key(), t[1], t[2]))
        ]

    def lines(self) -> list[str]:
        return [e.format() for e in self.sorted()]
