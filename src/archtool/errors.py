# Copyright (C) 2026 Evert van de Waal
#
# This file is part of archtool, the architecting tool.
#
# archtool is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# archtool is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with archtool. If not, see
# <https://www.gnu.org/licenses/>.

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
