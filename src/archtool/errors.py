"""Errors reported while reading model files."""

from pathlib import Path


class FormatError(Exception):
    """An error in a file, with the position where it was found.

    Lines and columns are counted from 1.
    """

    def __init__(self, path: Path | str, line: int, column: int, message: str) -> None:
        super().__init__(f"{path}:{line}:{column}: {message}")
        self.path = str(path)
        self.line = line
        self.column = column
        self.message = message


class LexicalError(Exception):
    """An error within a piece of text, at an offset counted from 0.

    Raised by the low-level parsing functions, which do not know the file and
    line they are parsing; their callers convert it into a FormatError.
    """

    def __init__(self, offset: int, message: str) -> None:
        super().__init__(f"at offset {offset}: {message}")
        self.offset = offset
        self.message = message

    def shifted(self, offset: int) -> "LexicalError":
        """The same error, for text that starts `offset` characters further on."""
        return LexicalError(self.offset + offset, self.message)
